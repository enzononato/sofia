"""
Unit tests for app.services.humanizer.split_reply().

Pure function, no I/O — covers the marker-based split path, the "short text,
no marker" passthrough, the never-empty-parts guarantee, and the MAX_PARTS cap.
"""

from app.services.humanizer import MAX_PARTS, SPLIT_MARKER, split_reply


def test_split_with_marker_separates_parts():
    # Both segments are >= MIN_PART_CHARS so neither gets merged into the other.
    a = "Perfeito, consegui um horario pra voce na quinta as 14h."
    b = "So preciso confirmar o seu nome completo pra fechar, pode ser?"
    parts = split_reply(f"{a}{SPLIT_MARKER}{b}")
    assert parts == [a, b]


def test_split_merges_marker_part_below_min_chars():
    # A short segment (< MIN_PART_CHARS) reads as an orphaned fragment, so the
    # split path merges it back rather than sending a lone tiny bubble.
    text = f"Oi, tudo bem?{SPLIT_MARKER}Posso te ajudar com o seu agendamento hoje?"
    parts = split_reply(text)
    assert len(parts) == 1
    assert "Oi, tudo bem?" in parts[0]
    assert "agendamento" in parts[0]


def test_split_without_marker_short_text_returns_single_part():
    text = "Combinado, te espero quinta às 14h!"
    parts = split_reply(text)
    assert parts == [text]


def test_split_never_returns_blank_or_empty_parts():
    # A marker-split with an empty segment between two markers must not leak
    # a blank/whitespace-only entry into the result. Segments are long enough
    # (>= MIN_PART_CHARS) to survive as two distinct parts.
    a = "Essa e a primeira parte da resposta, bem completa."
    b = "E aqui vai a segunda parte, tambem com conteudo proprio."
    text = f"{a}{SPLIT_MARKER}   {SPLIT_MARKER}{b}"
    parts = split_reply(text)
    assert all(p.strip() for p in parts)
    assert parts == [a, b]


def test_split_respects_max_parts_cap():
    # Build a marker-separated text with more segments than MAX_PARTS allows;
    # each segment is long enough to avoid being merged by the MIN_PART_CHARS
    # short-tail rule, so the only thing capping the count is MAX_PARTS.
    segments = [f"Este e o segmento numero {i} da mensagem, bem detalhado." for i in range(MAX_PARTS + 2)]
    text = SPLIT_MARKER.join(segments)
    parts = split_reply(text)
    assert len(parts) <= MAX_PARTS
    # The overflow content must still be present somewhere (merged into the
    # last part), not silently dropped.
    assert "segmento numero 0" in parts[0]
    assert all(p.strip() for p in parts)


def test_split_empty_input_returns_single_empty_part():
    assert split_reply("") == [""]
    assert split_reply(None) == [""]
