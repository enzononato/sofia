"""
Regression tests for the "staff audio poisons the AI prompt" bug.

`POST /contacts/{id}/messages/media` used to store the whole base64 data URI in
`messages.content` and leave `media_type` NULL. `ai.py::_history_text_for` keys
off `media_type`, so with it NULL it fell through to `return msg.content` and
handed the ENTIRE blob to Gemini as plain text on every later turn for that
contact — inflating cost until the context limit blew and Sofia silently stopped
replying to that patient.

Two independent layers are covered here:
  1. `_history_text_for` never emits a `data:` blob, even for legacy rows that
     are already in the database (the migration repairs them, but a row written
     by an older worker mid-deploy must not poison the prompt either);
  2. `_parse_data_uri_meta` extracts the metadata the route now stores, so new
     rows take the media branch instead.
"""

from types import SimpleNamespace

from app.api.v1.routes.contacts import _parse_data_uri_meta
from app.services.ai import _history_text_for


def _msg(content, media_type=None):
    return SimpleNamespace(content=content, media_type=media_type)


class TestHistoryTextForNeverLeaksDataUri:
    def test_legacy_audio_blob_in_content_becomes_a_short_marker(self):
        blob = "data:audio/webm;base64," + ("A" * 50_000)
        out = _history_text_for(_msg(blob))
        assert out == "[áudio]"
        assert "base64" not in out
        assert len(out) < 30

    def test_legacy_image_blob_in_content_becomes_a_short_marker(self):
        out = _history_text_for(_msg("data:image/jpeg;base64," + ("B" * 10_000)))
        assert out == "[imagem]"

    def test_unknown_data_uri_kind_still_never_leaks(self):
        out = _history_text_for(_msg("data:application/pdf;base64," + ("C" * 10_000)))
        assert "base64" not in out
        assert out.startswith("[")

    def test_properly_tagged_media_still_uses_its_label_and_caption(self):
        assert _history_text_for(_msg("olha minha pele", "image")) == "[imagem: olha minha pele]"
        assert _history_text_for(_msg("", "audio")) == "[áudio]"

    def test_plain_text_is_untouched(self):
        assert _history_text_for(_msg("quero marcar uma limpeza")) == "quero marcar uma limpeza"

    def test_text_merely_mentioning_data_is_untouched(self):
        # Only a real data: URI prefix triggers the guard.
        assert _history_text_for(_msg("meus dados estão certos?")) == "meus dados estão certos?"


class TestParseDataUriMeta:
    def test_extracts_mime_and_decoded_size(self):
        # "AAAA" base64-decodes to 3 bytes.
        mime, size = _parse_data_uri_meta("data:audio/webm;base64,AAAA")
        assert mime == "audio/webm"
        assert size == 3

    def test_handles_a_missing_or_non_data_uri(self):
        assert _parse_data_uri_meta("") == (None, None)
        assert _parse_data_uri_meta("https://example.com/a.mp3") == (None, None)

    def test_handles_a_malformed_data_uri_without_raising(self):
        assert _parse_data_uri_meta("data:audio/webm;base64") == (None, None)
