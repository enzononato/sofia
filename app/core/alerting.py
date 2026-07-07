"""
Error alerting — email the team when an ERROR-level log fires.

Wired into the root logger by `configure_logging()` when ALERT_EMAIL_ENABLED is
set and the SMTP settings are present. Design constraints:

  - Never block the event loop: the actual SMTP send runs in a daemon thread.
  - Never storm the inbox: identical alerts (same logger + message prefix) are
    throttled to at most one per ALERT_MIN_INTERVAL_SECONDS.
  - Never raise: a failure to send an alert must not break request handling, and
    must not itself log at ERROR (that would loop back into this handler).
"""

import logging
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage

from app.config import settings

_fallback_logger = logging.getLogger(__name__)


class EmailAlertHandler(logging.Handler):
    """Logging handler that emails ERROR+ records, off-thread and throttled."""

    def __init__(self, min_interval_seconds: int) -> None:
        super().__init__(level=logging.ERROR)
        self._min_interval = max(0, min_interval_seconds)
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.ERROR:
                return
            # Dedupe key: same logger + same message head shouldn't re-alert within
            # the throttle window (a single failing dependency can log repeatedly).
            key = f"{record.name}:{record.getMessage()[:120]}"
            now = time.monotonic()
            with self._lock:
                last = self._last_sent.get(key, 0.0)
                if self._min_interval and (now - last) < self._min_interval:
                    return
                self._last_sent[key] = now

            body = self.format(record)
            subject = f"[Sofia ALERTA] {record.levelname}: {record.getMessage()[:100]}"
            threading.Thread(
                target=self._send, args=(subject, body), daemon=True
            ).start()
        except Exception:  # pragma: no cover - handler must never raise
            self.handleError(record)

    def _send(self, subject: str, body: str) -> None:
        try:
            recipients = [
                r.strip() for r in (settings.ALERT_EMAIL_TO or "").split(",") if r.strip()
            ]
            if not (settings.ALERT_SMTP_HOST and settings.ALERT_EMAIL_FROM and recipients):
                return

            em = EmailMessage()
            em["Subject"] = subject
            em["From"] = settings.ALERT_EMAIL_FROM
            em["To"] = ", ".join(recipients)
            em.set_content(body)

            if settings.ALERT_SMTP_USE_SSL:
                server: smtplib.SMTP = smtplib.SMTP_SSL(
                    settings.ALERT_SMTP_HOST, settings.ALERT_SMTP_PORT, timeout=15
                )
            else:
                server = smtplib.SMTP(
                    settings.ALERT_SMTP_HOST, settings.ALERT_SMTP_PORT, timeout=15
                )
            with server:
                if settings.ALERT_SMTP_USE_TLS and not settings.ALERT_SMTP_USE_SSL:
                    server.starttls(context=ssl.create_default_context())
                if settings.ALERT_SMTP_USER:
                    server.login(settings.ALERT_SMTP_USER, settings.ALERT_SMTP_PASSWORD or "")
                server.send_message(em)
        except Exception:
            # Warning (not error) on purpose: logging at ERROR here would feed
            # right back into this handler and loop.
            _fallback_logger.warning("email_alert_send_failed", exc_info=True)


def build_email_alert_handler() -> EmailAlertHandler | None:
    """Return a configured handler, or None if alerting is disabled/misconfigured."""
    if not settings.ALERT_EMAIL_ENABLED:
        return None
    recipients = [r.strip() for r in (settings.ALERT_EMAIL_TO or "").split(",") if r.strip()]
    if not (settings.ALERT_SMTP_HOST and settings.ALERT_EMAIL_FROM and recipients):
        _fallback_logger.warning(
            "email_alerting_enabled_but_unconfigured",
            extra={"have_host": bool(settings.ALERT_SMTP_HOST),
                   "have_from": bool(settings.ALERT_EMAIL_FROM),
                   "have_to": bool(recipients)},
        )
        return None
    handler = EmailAlertHandler(settings.ALERT_MIN_INTERVAL_SECONDS)
    handler.setLevel(logging.ERROR)
    return handler
