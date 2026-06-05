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


class _DevFormatter(logging.Formatter):
    """Human-readable formatter that includes extra={} fields as key=value pairs."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        base = f"{ts} [{record.levelname}] {record.name} — {record.getMessage()}"

        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in _STD_ATTRS and not k.startswith("_")
        }
        if extras:
            parts = " | ".join(f"{k}={v}" for k, v in extras.items())
            base = f"{base}  [{parts}]"

        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    """Install the chosen formatter on the root logger; idempotent."""
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    # Wipe any handlers Uvicorn or third parties may have attached
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(_DevFormatter())
    root.addHandler(handler)

    # Tame noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )
