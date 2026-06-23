"""Targeted, in-memory diagnostics for the event → sample → engine chain.

Two bounded, in-memory structures (no DB/filesystem growth, no arbitrary SQL):

* an always-on **event trace** ring buffer recording what happened to each
  incoming entity event (raw old/new, normalized values, persisted?, result), and
* a **structured log** ring buffer that components write to *only while an
  administrator has enabled the temporary diagnostics mode* (default 30 minutes,
  auto-expiring).

All log messages and fields are passed through :func:`redact` so the Supervisor
token, Authorization headers, cookies, session ids, SMTP/API secrets, private
keys and full environment values can never be disclosed.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger("diagnostics")

# Machine-readable per-event / per-path results.
STORED = "stored"
RECONCILED_ON_RECONNECT = "reconciled_on_reconnect"
IGNORED_DUPLICATE = "duplicate_ignored"
OUT_OF_ORDER_EVENT = "out_of_order_event"
IGNORED_UNCHANGED = "ignored_unchanged"
IGNORED_INVALID_STATE = "ignored_invalid_state"
UNAVAILABLE = "unavailable"
NORMALIZATION_FAILED = "normalization_failed"
MAPPING_MISSING = "mapping_missing"
STORAGE_UNIT_MISSING = "storage_unit_missing"
INVALID_TIMESTAMP = "invalid_timestamp"
PERSIST_FAILED = "persist_failed"
ENGINE_NOT_INVOKED = "engine_not_invoked"
CYCLE_STARTED = "cycle_started"
CYCLE_ENDED = "cycle_ended"

_GLOBAL_CAP = 500
_PER_ENTITY_CAP = 100
_LOG_CAP = 1000  # hard maximum buffered structured log entries
_LOG_RETURN_DEFAULT = 200  # maximum returned entries
MODE_DEFAULT_MINUTES = 30


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #

_REDACT = "«redacted»"
# Field keys whose values are always redacted (case-insensitive substring).
_SECRET_KEYS = (
    "token",
    "authorization",
    "cookie",
    "session",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "bearer",
    "supervisor_token",
)
# Inline patterns in free text.
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")
_ASSIGN_RE = re.compile(
    r"(?i)\b(token|authorization|cookie|session[_-]?id|password|passwd|secret|api[_-]?key"
    r"|private[_-]?key|supervisor_token)\b\s*[=:]\s*\S+"
)


def _is_secret_key(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in _SECRET_KEYS)


def redact_text(value: str) -> str:
    value = _BEARER_RE.sub(f"bearer {_REDACT}", value)
    value = _ASSIGN_RE.sub(lambda m: f"{m.group(1)}={_REDACT}", value)
    return value


def redact(value: Any) -> Any:
    """Recursively redact secrets from strings/dicts/lists for safe display."""
    if value is None:
        return None
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[k] = _REDACT if _is_secret_key(str(k)) else redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EventTrace:
    timestamp: datetime
    entity_id: str
    storage_unit_id: int | None
    role: str | None
    old_raw: str | None
    new_raw: str | None
    normalized_old: str | None
    normalized_new: str | None
    mapping_found: bool
    persisted: bool
    engine_relevant: bool
    result: str


@dataclass(frozen=True)
class LogEntry:
    timestamp: datetime
    severity: str  # debug | info | warning | error
    component: str
    message: str
    storage_unit_id: int | None = None
    entity_id: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModeStatus:
    enabled: bool
    expires_at: datetime | None
    remaining_seconds: int
    enabled_by: str | None
    buffered_logs: int


_SEVERITY_ORDER = {"debug": 0, "info": 1, "warning": 2, "error": 3}


class DiagnosticsRecorder:
    """Bounded, in-memory recorder. Safe to share across the app lifetime."""

    def __init__(self) -> None:
        self._recent: deque[EventTrace] = deque(maxlen=_GLOBAL_CAP)
        self._by_entity: dict[str, deque[EventTrace]] = {}
        self._logs: deque[LogEntry] = deque(maxlen=_LOG_CAP)
        self._mode_expires: datetime | None = None
        self._mode_by: str | None = None

    # -- event trace (always on) ------------------------------------------ #

    def record(
        self,
        *,
        entity_id: str,
        storage_unit_id: int | None,
        role: str | None,
        old_raw: str | None,
        new_raw: str | None,
        normalized_old: str | None,
        normalized_new: str | None,
        mapping_found: bool,
        persisted: bool,
        engine_relevant: bool,
        result: str,
        timestamp: datetime | None = None,
    ) -> None:
        trace = EventTrace(
            timestamp=timestamp or datetime.now(UTC),
            entity_id=entity_id,
            storage_unit_id=storage_unit_id,
            role=role,
            old_raw=old_raw,
            new_raw=new_raw,
            normalized_old=normalized_old,
            normalized_new=normalized_new,
            mapping_found=mapping_found,
            persisted=persisted,
            engine_relevant=engine_relevant,
            result=result,
        )
        self._recent.append(trace)
        buf = self._by_entity.get(entity_id)
        if buf is None:
            buf = deque(maxlen=_PER_ENTITY_CAP)
            self._by_entity[entity_id] = buf
        buf.append(trace)

        # Mirror into the structured log while diagnostics mode is active.
        if self.mode_active():
            self.log(
                "info" if persisted else "debug",
                "collector",
                f"event {old_raw} -> {new_raw} => {result}",
                storage_unit_id=storage_unit_id,
                entity_id=entity_id,
                fields={
                    "normalized_old": normalized_old,
                    "normalized_new": normalized_new,
                    "result": result,
                    "persisted": persisted,
                },
            )

    def recent(self, entity_id: str | None = None, limit: int = 50) -> list[EventTrace]:
        limit = max(1, min(limit, _GLOBAL_CAP))
        src = self._by_entity.get(entity_id, deque()) if entity_id else self._recent
        return list(src)[-limit:][::-1]

    def last_for(self, entity_id: str) -> EventTrace | None:
        buf = self._by_entity.get(entity_id)
        return buf[-1] if buf else None

    # -- structured logs (gated by mode) ---------------------------------- #

    def log(
        self,
        severity: str,
        component: str,
        message: str,
        *,
        storage_unit_id: int | None = None,
        entity_id: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        """Append a redacted structured log entry (only while mode is active)."""
        if not self.mode_active():
            return
        self._logs.append(
            LogEntry(
                timestamp=datetime.now(UTC),
                severity=severity,
                component=component,
                message=redact_text(message),
                storage_unit_id=storage_unit_id,
                entity_id=entity_id,
                fields=redact(fields or {}),
            )
        )

    def query_logs(
        self,
        *,
        component: str | None = None,
        storage_unit_id: int | None = None,
        entity_id: str | None = None,
        severity: str | None = None,
        since: datetime | None = None,
        limit: int = _LOG_RETURN_DEFAULT,
    ) -> list[LogEntry]:
        limit = max(1, min(limit, _LOG_RETURN_DEFAULT))
        min_sev = _SEVERITY_ORDER.get((severity or "").lower(), 0)
        out: list[LogEntry] = []
        for e in reversed(self._logs):  # newest first
            if component and e.component != component:
                continue
            if storage_unit_id is not None and e.storage_unit_id != storage_unit_id:
                continue
            if entity_id and e.entity_id != entity_id:
                continue
            if severity and _SEVERITY_ORDER.get(e.severity, 0) < min_sev:
                continue
            if since is not None and e.timestamp < since:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    # -- diagnostics mode (30 min, admin) --------------------------------- #

    def enable_mode(
        self, *, minutes: int = MODE_DEFAULT_MINUTES, user: str | None = None
    ) -> ModeStatus:
        minutes = max(1, min(minutes, 120))
        self._mode_expires = datetime.now(UTC) + timedelta(minutes=minutes)
        self._mode_by = user
        log.info("diagnostics: mode enabled for %d min by %s", minutes, user or "?")
        return self.mode_status()

    def disable_mode(self) -> ModeStatus:
        if self._mode_expires is not None:
            log.info("diagnostics: mode disabled")
        self._mode_expires = None
        self._mode_by = None
        return self.mode_status()

    def mode_active(self) -> bool:
        if self._mode_expires is None:
            return False
        if datetime.now(UTC) >= self._mode_expires:
            self._mode_expires = None
            self._mode_by = None
            return False
        return True

    def mode_status(self) -> ModeStatus:
        active = self.mode_active()
        remaining = (
            int((self._mode_expires - datetime.now(UTC)).total_seconds())
            if active and self._mode_expires is not None
            else 0
        )
        return ModeStatus(
            enabled=active,
            expires_at=self._mode_expires if active else None,
            remaining_seconds=max(0, remaining),
            enabled_by=self._mode_by if active else None,
            buffered_logs=len(self._logs),
        )
