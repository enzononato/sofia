"""
Unit tests for app.services.ai._annotate_history() — the "stale block" time
marker logic extracted out of generate_reply() so it's testable without a
real Gemini call or DB session.

Messages are represented by lightweight fakes exposing only `.direction`
(the one attribute the role-mapping reads) — see the extraction docstring in
app/services/ai.py for the exact rules being tested here.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.models.message import MessageDirection
from app.services.ai import _annotate_history

_TZ = ZoneInfo("America/Sao_Paulo")


def _msg(direction: str = MessageDirection.INBOUND.value):
    return SimpleNamespace(direction=direction)


def test_all_messages_now_same_session_no_gap_none_marked():
    now_local = datetime(2026, 7, 6, 12, 0, tzinfo=_TZ)
    usable = [
        (_msg(), "oi", now_local - timedelta(minutes=2)),
        (_msg(), "tudo bem?", now_local - timedelta(seconds=30)),
    ]
    annotated = _annotate_history(usable, now_local, _TZ)
    assert len(annotated) == 2
    for _role, text in annotated:
        assert not text.startswith("[")


def test_first_message_from_previous_day_is_marked():
    now_local = datetime(2026, 7, 6, 9, 0, tzinfo=_TZ)
    old_local = datetime(2026, 7, 3, 15, 0, tzinfo=_TZ)
    usable = [(_msg(), "mensagem antiga", old_local)]
    annotated = _annotate_history(usable, now_local, _TZ)
    assert len(annotated) == 1
    role, text = annotated[0]
    assert text.startswith("[")
    assert "mensagem antiga" in text


def test_five_hour_gap_same_day_marks_both_sides():
    # msg_a at 08:00, msg_b at 13:00 (5h later, same day) — closes msg_a's
    # block and opens msg_b's. now_local is only 1h after msg_b (< 4h gap),
    # so msg_b's "closes" check on its own is false, but it's still marked
    # because it OPENS a new block.
    day = datetime(2026, 7, 6, tzinfo=_TZ)
    msg_a_time = day.replace(hour=8)
    msg_b_time = day.replace(hour=13)
    now_local = day.replace(hour=14)

    usable = [
        (_msg(), "primeira", msg_a_time),
        (_msg(), "segunda", msg_b_time),
    ]
    annotated = _annotate_history(usable, now_local, _TZ)
    assert len(annotated) == 2

    _, text_a = annotated[0]
    _, text_b = annotated[1]
    assert text_a.startswith("["), "message before the >=4h gap should close its block"
    assert text_b.startswith("["), "message after the >=4h gap should open a new block"


def test_message_without_timestamp_is_never_marked():
    now_local = datetime(2026, 7, 6, 9, 0, tzinfo=_TZ)
    # This message would normally be marked (first message, different day from
    # today) if it had a resolvable local timestamp — but local=None disables
    # marking defensively.
    usable = [(_msg(), "sem timestamp", None)]
    annotated = _annotate_history(usable, now_local, _TZ)
    assert len(annotated) == 1
    _, text = annotated[0]
    assert text == "sem timestamp"
    assert not text.startswith("[")


def test_role_mapping_inbound_is_user_outbound_is_model():
    now_local = datetime(2026, 7, 6, 9, 0, tzinfo=_TZ)
    usable = [
        (_msg(MessageDirection.INBOUND.value), "pergunta", now_local - timedelta(minutes=1)),
        (_msg(MessageDirection.OUTBOUND.value), "resposta", now_local - timedelta(seconds=30)),
    ]
    annotated = _annotate_history(usable, now_local, _TZ)
    assert annotated[0][0] == "user"
    assert annotated[1][0] == "model"
