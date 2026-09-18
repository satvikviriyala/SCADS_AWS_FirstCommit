"""Structured JSON logging.

One JSON object per line, so CloudWatch Logs Insights can query fields directly
(``docs/AWS_DEPLOYMENT.md`` section 8).

The redaction list is not decoration. Presigned URLs are bearer credentials for
an S3 object, raw OCR text is the contents of someone's medicine packet, and a
precise location is exactly what ``docs/SECURITY_PRIVACY.md`` promises not to
retain. Those keys are dropped here rather than relied on not to be passed.
"""

import json
import logging
import sys
from typing import Any, Dict, Optional

_LOGGER_NAME = "scads"

# Never logged, at any level, regardless of caller.
_REDACT_KEYS = frozenset(
    {
        "url", "upload_url", "presigned_url", "signature",
        "token", "admin_token", "authorization", "secret",
        "ocr_text", "full_text", "raw_ocr",
        "lat", "lon", "latitude", "longitude",
        "qr_payload", "image_bytes",
    }
)

_MAX_VALUE_CHARS = 512


def _sanitise(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "<nested>"
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if str(k).lower() in _REDACT_KEYS else _sanitise(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitise(v, depth + 1) for v in value[:20]]
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return value[:_MAX_VALUE_CHARS] + "...<truncated>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_VALUE_CHARS]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "event": record.getMessage(),
        }
        extra = getattr(record, "scads_fields", None)
        if isinstance(extra, dict):
            payload.update(_sanitise(extra))
        if record.exc_info:
            # The type only. A stack trace in logs is fine; the concern is that
            # exception text often carries the very values redacted above.
            payload["exception"] = str(record.exc_info[0].__name__)
        return json.dumps(payload, separators=(",", ":"), default=str)


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # Lambda installs its own root handler; propagating would double every line.
        logger.propagate = False
    return logger


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one structured log line."""
    get_logger().log(level, event, extra={"scads_fields": fields})


def log_error(event: str, **fields: Any) -> None:
    log_event(event, level=logging.ERROR, **fields)


def log_warning(event: str, **fields: Any) -> None:
    log_event(event, level=logging.WARNING, **fields)
