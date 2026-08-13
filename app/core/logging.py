"""
Structured logging configuration.

Outputs JSON lines (or human-readable text in dev) so logs are immediately
ingestable by Datadog / Loki / CloudWatch without parsers.

Each record includes:
  - timestamp (ISO 8601 UTC)
  - level
  - logger name
  - message
  - any extra={...} fields passed by callers (request_id, tenant_id, etc.)
  - exception info when applicable

Usage:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("inbound webhook", extra={"tenant_id": str(tid), "phone": phone})
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import settings

# Standard LogRecord attributes — anything outside this set was passed via `extra`
_STD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Renders log records as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Promote everything passed via extra=... to top-level keys
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = _safe(value)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info

        return json.dumps(payload, ensure_ascii=False, default=str)


def _safe(value: Any) -> Any:
    """Make non-JSON-serializable values safe for json.dumps."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ── Pretty (human) formatter ─────────────────────────────────────────────────
# ANSI colors, applied only when writing to a real terminal (never in EasyPanel
# container logs, which would otherwise show escape codes as garbage).
_ANSI = {
    "reset": "\033[0m", "dim": "\033[2m", "bold": "\033[1m",
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m", "gray": "\033[90m",
}

# level → (icon, color)
_LEVEL_STYLE = {
    "DEBUG": ("·", "gray"),
    "INFO": ("•", "cyan"),
    "WARNING": ("▲", "yellow"),
    "ERROR": ("✖", "red"),
    "CRITICAL": ("🔥", "red"),
}

# Known event slugs (the log message) → (icon, friendly pt-BR label). Turns the
# raw event stream into something a human can scan: what Sofia is actually doing.
_EVENT_STYLE: dict[str, tuple[str, str]] = {
    "webhook_received": ("📩", "mensagem recebida"),
    "webhook_processed": ("✅", "Sofia respondeu"),
    "webhook_group_skipped": ("🔇", "grupo ignorado"),
    "webhook_nothing_to_answer": ("💤", "nada a responder"),
    "webhook_ai_paused": ("⏸️", "Sofia pausada (atendimento humano)"),
    "webhook_ai_paused_late": ("⏸️", "Sofia pausada (atendimento humano)"),
    # Loop de tool-calling compartilhado (legacy, specialists e copiloto)
    "agent_reply_ready": ("🤖", "resposta gerada"),
    "agent_forced_final_reply": ("🤖", "resposta gerada (final)"),
    "agent_tool_executed": ("🔧", "ferramenta usada"),
    "agent_empty_parts": ("⚠️", "modelo retornou vazio"),
    "agent_tool_loop_exhausted": ("🔁", "loop de ferramentas esgotado"),
    "agent_tool_not_allowed": ("🚫", "ferramenta bloqueada"),
    "agent_forced_final_failed": ("💥", "resposta final forçada falhou"),
    # Chamada ao Gemini (fora do loop)
    "gemini_call_failed_will_retry": ("💥", "falha na chamada ao modelo"),
    "gemini_call_exhausted": ("💥", "modelo falhou em todas as tentativas"),
    "reply_superseded_by_new_message": ("↩️", "resposta adiada (chegou nova msg)"),
    "webhook_media_download_giving_up": ("📎", "falha ao baixar mídia"),
    "webhook_media_too_large": ("📎", "mídia grande demais"),
    "scheduler_started": ("⏰", "agendador iniciado"),
    "user_login": ("🔑", "login"),
    "email_alerting_enabled": ("📧", "alertas de e-mail ativos"),
    # Empty label: HTTP access lines render as just "METHOD /path → status".
    "request_completed": ("🌐", ""),
}

# Extras shown first (curated, in this order) — the rest are appended dim. Noisy
# identifiers are hidden entirely from the pretty view (still in JSON logs).
_EXTRA_PRIORITY = ("phone", "contact_id", "tool", "stage", "reason", "model",
                   "parts", "reply_length", "method", "path", "status", "elapsed_ms")
_EXTRA_HIDDEN = {"request_id", "tenant_id", "taskName", "body_keys", "chatid",
                 "tenant_slug", "result_keys", "iteration", "iterations"}


class _DevFormatter(logging.Formatter):
    """Human-scannable formatter: one clean line per event with an icon and a
    friendly label, key details inline, noise dimmed. Colors only on a TTY."""

    def __init__(self) -> None:
        super().__init__()
        self._color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _c(self, text: str, color: str) -> str:
        if not self._color or not text:
            return text
        return f"{_ANSI.get(color, '')}{text}{_ANSI['reset']}"

    def _short(self, contact_id: str) -> str:
        return contact_id.split("-")[0] if isinstance(contact_id, str) else str(contact_id)

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        lvl_icon, lvl_color = _LEVEL_STYLE.get(record.levelname, ("•", "cyan"))

        raw_msg = record.getMessage()
        ev_icon, label = _EVENT_STYLE.get(raw_msg, ("", raw_msg))
        headline = f"{ev_icon} {label}".strip()
        if record.levelname in ("ERROR", "CRITICAL", "WARNING"):
            headline = self._c(headline, lvl_color)

        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in _STD_ATTRS and not k.startswith("_") and k not in _EXTRA_HIDDEN
        }

        # HTTP access line reads best as "METHOD /path → status (Nms)"
        detail_bits: list[str] = []
        if "method" in extras and "path" in extras:
            status = extras.pop("status", "")
            elapsed = extras.pop("elapsed_ms", None)
            elapsed_txt = f" ({round(elapsed)}ms)" if isinstance(elapsed, (int, float)) else ""
            detail_bits.append(
                self._c(f"{extras.pop('method')} {extras.pop('path')} → {status}{elapsed_txt}", "gray")
            )

        if "contact_id" in extras:
            extras["contact_id"] = self._short(extras["contact_id"])

        for key in _EXTRA_PRIORITY:
            if key in extras:
                detail_bits.append(f"{self._c(key, 'dim')}={extras.pop(key)}")
        for key, val in extras.items():
            detail_bits.append(self._c(f"{key}={val}", "dim"))

        line = f"{self._c(ts, 'gray')} {self._c(lvl_icon, lvl_color)} {headline}"
        if detail_bits:
            line += "  " + "  ".join(str(b) for b in detail_bits)

        if record.exc_info:
            line += "\n" + self._c(self.formatException(record.exc_info), "red")
        return line


def configure_logging() -> None:
    """Install the chosen formatter on the root logger; idempotent."""
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    # Wipe any handlers Uvicorn or third parties may have attached
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter: logging.Formatter = (
        JsonFormatter() if settings.LOG_FORMAT == "json" else _DevFormatter()
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Email alerting on ERROR+ (opt-in; no-op unless configured). Imported lazily
    # so a logging setup never hard-depends on the alerting module.
    from app.core.alerting import build_email_alert_handler

    alert_handler = build_email_alert_handler()
    if alert_handler is not None:
        alert_handler.setFormatter(formatter)
        root.addHandler(alert_handler)
        logging.getLogger(__name__).info("email_alerting_enabled")

    # Tame noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )
