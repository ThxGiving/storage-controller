"""Structured logging with secret redaction.

The Supervisor token and SMTP-style secrets must never appear in logs. A
logging filter scrubs known secret values and obvious token patterns from every
record before it is emitted to stdout/stderr.
"""

from __future__ import annotations

import logging
import os
import re
import sys

_TOKEN_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)
_REDACTED = "***REDACTED***"


def _secret_values() -> list[str]:
    values = []
    for key in ("SUPERVISOR_TOKEN", "HA_TOKEN"):
        val = os.environ.get(key)
        if val:
            values.append(val)
    return values


class SecretRedactionFilter(logging.Filter):
    """Remove known secrets and Bearer tokens from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True

        redacted = message
        for secret in _secret_values():
            if secret and secret in redacted:
                redacted = redacted.replace(secret, _REDACTED)
        redacted = _TOKEN_PATTERN.sub(rf"\1{_REDACTED}", redacted)

        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(SecretRedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Keep access logs quiet; uvicorn already logs requests.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
