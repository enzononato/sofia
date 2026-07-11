"""
Unit tests for app.api.v1.routes.webhooks._webhook_secret_valid() — the
fail-closed, constant-time webhook secret check (item 1.6 of the robustness
plan).

Before this change, a tenant with NO webhook_secret stored accepted ANY
request unauthenticated (`if expected_secret and provided_secret !=
expected_secret`). The fix inverts the logic: no stored secret => reject.
Pure function, no DB/network — matches the pattern used elsewhere in this
suite (see test_booking_lead_time.py, test_ai_retry.py).
"""

from app.api.v1.routes.webhooks import _webhook_secret_valid


def test_missing_expected_secret_fails_closed_even_with_no_provided_token():
    # Previously this exact case ("tenant has no secret stored") let ANY
    # request through unauthenticated — now it must be rejected.
    assert _webhook_secret_valid(None, None) is False


def test_missing_expected_secret_fails_closed_even_with_a_provided_token():
    # An attacker guessing/omitting a token must not bypass an unconfigured
    # tenant just because they happened to send *something*.
    assert _webhook_secret_valid(None, "anything") is False


def test_empty_string_expected_secret_fails_closed():
    assert _webhook_secret_valid("", "") is False


def test_wrong_provided_secret_is_rejected():
    assert _webhook_secret_valid("correct-secret", "wrong-secret") is False


def test_no_provided_secret_against_configured_expected_is_rejected():
    assert _webhook_secret_valid("correct-secret", None) is False


def test_correct_provided_secret_is_accepted():
    assert _webhook_secret_valid("correct-secret", "correct-secret") is True


def test_correct_secret_is_case_sensitive():
    assert _webhook_secret_valid("Correct-Secret", "correct-secret") is False
