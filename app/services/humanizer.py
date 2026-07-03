"""
Human-like conversation helpers: splitting long replies into natural chunks
and computing randomized, length-proportional typing delays.

Pure functions only (no I/O) so they're trivially testable and side-effect free.
The orchestration (sending presence, sleeping, dispatching) lives in the webhook
pipeline; this module just decides *what* the parts are and *how long* to "type".
"""

import random
import re

from app.config import settings

# Delimiter the model is instructed to insert between message parts. Chosen to be
# extremely unlikely to appear in natural Portuguese text.
SPLIT_MARKER = "[[BREAK]]"

# Hard ceiling on parts for ANY reply (marker-based or fallback). A human doesn't
# send 5 WhatsApp bubbles in a row for one answer — beyond this, parts are merged
# back together (favors one longer message over a spammy burst).
MAX_PARTS = 3

# A part shorter than this reads as an orphaned fragment (e.g. a lone "Combinado!"
# or a trailing question by itself) rather than an intentional separate thought.
# Fallback splitting merges such tails into the previous part.
MIN_PART_CHARS = 20


def split_reply(text: str) -> list[str]:
    """
    Split an AI reply into the parts that should be sent as separate WhatsApp
    messages.

    Strategy:
      1. If the model used SPLIT_MARKER, honor it (primary path).
      2. Otherwise, if splitting is enabled and the text is long, fall back to a
         paragraph/sentence-aware split bounded by RESPONSE_SPLIT_MAX_CHARS.
      3. Always return at least one non-empty part and never leak the marker.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return [""]

    # Primary path: explicit marker from the model.
    if SPLIT_MARKER in cleaned:
        parts = [p.strip() for p in cleaned.split(SPLIT_MARKER)]
        parts = [p for p in parts if p]
        return _normalize_parts(parts) if parts else [cleaned.replace(SPLIT_MARKER, " ").strip()]

    if not settings.RESPONSE_SPLIT_ENABLED:
        return [cleaned]

    # Fallback: only split when the message is meaningfully long.
    if len(cleaned) <= settings.RESPONSE_SPLIT_MAX_CHARS:
        return [cleaned]

    return _normalize_parts(_split_by_length(cleaned, settings.RESPONSE_SPLIT_MAX_CHARS))


def _normalize_parts(parts: list[str]) -> list[str]:
    """
    Post-process split parts so they read like intentional separate thoughts,
    not mechanical fragments:
      1. Merge any part shorter than MIN_PART_CHARS into its neighbor — a lone
         short tail (e.g. a trailing "Quer agendar?") reads as an orphaned
         fragment, not a deliberate second message.
      2. Cap the total at MAX_PARTS by merging from the end inward — a human
         doesn't send a 5-message burst for one answer.
    """
    if len(parts) <= 1:
        return parts

    merged = [parts[0]]
    for part in parts[1:]:
        if len(part) < MIN_PART_CHARS or len(merged[-1]) < MIN_PART_CHARS:
            merged[-1] = f"{merged[-1]}\n{part}"
        else:
            merged.append(part)

    while len(merged) > MAX_PARTS:
        # Merge the last two parts first — the tail is where over-splitting
        # (e.g. a model that got marker-happy) tends to accumulate.
        tail = merged.pop()
        merged[-1] = f"{merged[-1]}\n{tail}"

    return merged


def _split_by_length(text: str, max_chars: int) -> list[str]:
    """
    Greedily pack paragraphs/sentences into chunks no larger than max_chars
    (unless a single unit already exceeds it). Paragraph boundaries are preferred,
    then sentence boundaries.
    """
    # First break on blank lines (paragraphs), preserving meaning.
    units = [u.strip() for u in re.split(r"\n\s*\n", text) if u.strip()]
    # Further break overly long paragraphs into sentences.
    expanded: list[str] = []
    for unit in units:
        if len(unit) <= max_chars:
            expanded.append(unit)
        else:
            expanded.extend(_split_sentences(unit, max_chars))

    chunks: list[str] = []
    current = ""
    for unit in expanded:
        if not current:
            current = unit
        elif len(current) + 1 + len(unit) <= max_chars:
            current = f"{current}\n{unit}"
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)
    return chunks or [text]


def _split_sentences(text: str, max_chars: int) -> list[str]:
    """Split a long paragraph on sentence boundaries, hard-wrapping if needed."""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    out: list[str] = []
    current = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if not current:
            current = s
        elif len(current) + 1 + len(s) <= max_chars:
            current = f"{current} {s}"
        else:
            out.append(current)
            current = s
    if current:
        out.append(current)

    # Hard-wrap any sentence that alone exceeds the limit.
    wrapped: list[str] = []
    for chunk in out:
        while len(chunk) > max_chars:
            wrapped.append(chunk[:max_chars])
            chunk = chunk[max_chars:]
        if chunk:
            wrapped.append(chunk)
    return wrapped or [text]


def typing_delay_seconds(text: str) -> float:
    """
    Compute a human-like typing delay for a message part: proportional to its
    length, bounded by [TYPING_MIN_SECONDS, TYPING_MAX_SECONDS], with ±jitter so
    it's never a fixed value.
    """
    cps = max(settings.TYPING_CHARS_PER_SECOND, 1.0)
    base = len(text or "") / cps
    base = max(settings.TYPING_MIN_SECONDS, min(base, settings.TYPING_MAX_SECONDS))
    jitter = settings.TYPING_JITTER
    factor = random.uniform(1.0 - jitter, 1.0 + jitter)
    return round(base * factor, 2)


def batch_window_seconds() -> float:
    """Random debounce window within the configured [min, max] range."""
    lo = settings.BATCH_WINDOW_MIN_SECONDS
    hi = max(settings.BATCH_WINDOW_MAX_SECONDS, lo)
    return random.uniform(lo, hi)
