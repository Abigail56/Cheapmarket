"""Logging setup: one line per event, tagged with the current request id.
JSON in staging/production (for log aggregators), readable text locally."""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # anything passed via `extra=` (e.g. status, duration_ms) becomes a field
        entry |= {k: v for k, v in record.__dict__.items()
                  if k not in _STD_ATTRS and k != "request_id"}
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    use_json = settings.LOG_JSON if settings.LOG_JSON is not None else settings.ENVIRONMENT != "local"
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(_JsonFormatter() if use_json else logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.LOG_LEVEL)
    # our access log (app.access) replaces uvicorn's, which has no request id
    logging.getLogger("uvicorn.access").disabled = True


def configure_sentry() -> None:
    if not settings.SENTRY_DSN:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,  # no customer emails/phones/IPs in Sentry
    )
