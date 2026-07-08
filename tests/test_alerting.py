"""
Unit tests for app.core.alerting.EmailAlertHandler.

The handler sends off-thread (daemon Thread) and throttles duplicate alerts.
smtplib.SMTP / SMTP_SSL are replaced with an in-memory fake that records what
would have been sent, so no real network/SMTP call ever happens.
"""

import logging
import smtplib
import time

import pytest

from app.config import settings
from app.core.alerting import EmailAlertHandler

_POLL_TIMEOUT = 2.0
_POLL_INTERVAL = 0.02


class _FakeSMTP:
    """Records calls; usable as `with FakeSMTP(...) as server: ...`."""

    sent_messages: list = []  # class-level — shared across instances in a test

    def __init__(self, host, port, timeout=15):
        self.host = host
        self.port = port
        self.starttls_called = False
        self.login_args = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, em):
        _FakeSMTP.sent_messages.append(em)


@pytest.fixture(autouse=True)
def _reset_fake_smtp(monkeypatch):
    _FakeSMTP.sent_messages = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    yield
    _FakeSMTP.sent_messages = []


@pytest.fixture(autouse=True)
def _configure_alert_settings(monkeypatch):
    monkeypatch.setattr(settings, "ALERT_SMTP_HOST", "smtp.test.local")
    monkeypatch.setattr(settings, "ALERT_SMTP_PORT", 587)
    monkeypatch.setattr(settings, "ALERT_SMTP_USER", None)
    monkeypatch.setattr(settings, "ALERT_SMTP_PASSWORD", None)
    monkeypatch.setattr(settings, "ALERT_SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "ALERT_SMTP_USE_SSL", False)
    monkeypatch.setattr(settings, "ALERT_EMAIL_FROM", "sofia-alerts@example.com")
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", "team@example.com,ops@example.com")


def _make_record(logger_name: str, level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name=logger_name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )


def _wait_for(predicate, timeout=_POLL_TIMEOUT, interval=_POLL_INTERVAL):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_info_level_never_sends():
    handler = EmailAlertHandler(min_interval_seconds=0)
    record = _make_record("test.logger", logging.INFO, "just some info")
    handler.emit(record)
    # No thread should even be spawned for a sub-ERROR record; give it a beat
    # anyway in case emit() misbehaved and spawned one.
    time.sleep(0.1)
    assert _FakeSMTP.sent_messages == []


def test_error_level_sends_email():
    handler = EmailAlertHandler(min_interval_seconds=0)
    record = _make_record("test.logger", logging.ERROR, "something broke")
    handler.emit(record)

    assert _wait_for(lambda: len(_FakeSMTP.sent_messages) == 1)
    em = _FakeSMTP.sent_messages[0]
    assert "team@example.com" in em["To"]
    assert "ops@example.com" in em["To"]


def test_duplicate_error_within_throttle_window_sends_once():
    handler = EmailAlertHandler(min_interval_seconds=300)
    record1 = _make_record("test.logger", logging.ERROR, "duplicate failure")
    record2 = _make_record("test.logger", logging.ERROR, "duplicate failure")

    handler.emit(record1)
    assert _wait_for(lambda: len(_FakeSMTP.sent_messages) == 1)

    handler.emit(record2)
    time.sleep(0.2)  # give a stray second thread a chance to land, if any
    assert len(_FakeSMTP.sent_messages) == 1


def test_different_errors_both_send_with_both_recipients():
    handler = EmailAlertHandler(min_interval_seconds=300)
    record1 = _make_record("test.logger", logging.ERROR, "failure A")
    record2 = _make_record("test.logger", logging.ERROR, "failure B")

    handler.emit(record1)
    handler.emit(record2)

    assert _wait_for(lambda: len(_FakeSMTP.sent_messages) == 2)
    for em in _FakeSMTP.sent_messages:
        assert em["To"] == "team@example.com, ops@example.com"
