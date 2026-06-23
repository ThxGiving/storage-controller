"""Targeted, in-memory diagnostics for the event → sample → engine chain.

A bounded ring buffer records *what happened* to each incoming entity event:
the raw old/new states, their normalized values, whether the entity was mapped
to a storage unit, whether the sample was persisted, and the machine-readable
result. This is deliberately scoped (no arbitrary DB/SQL access) and never holds
tokens or credentials — only entity ids, states and processing outcomes.

An optional per-entity *trace mode* (admin, auto-expiring) raises logging for a
single entity to aid live debugging.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

log = logging.getLogger("diagnostics")

# Machine-readable per-event results.
STORED = "stored"
IGNORED_DUPLICATE = "ignored_duplicate"
IGNORED_UNCHANGED = "ignored_unchanged"
IGNORED_INVALID_STATE = "ignored_invalid_state"
UNAVAILABLE = "unavailable"
NORMALIZATION_FAILED = "normalization_failed"
MAPPING_MISSING = "mapping_missing"
ERROR = "error"

_GLOBAL_CAP = 500
_PER_ENTITY_CAP = 100
TRACE_TTL_SECONDS = 15 * 60


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
class TraceStatus:
    active: bool
    entity_id: str | None
    expires_at: datetime | None
    remaining_seconds: int


class DiagnosticsRecorder:
    """Bounded, in-memory recorder. Safe to share across the app lifetime."""

    def __init__(self) -> None:
        self._recent: deque[EventTrace] = deque(maxlen=_GLOBAL_CAP)
        self._by_entity: dict[str, deque[EventTrace]] = {}
        self._trace_entity: str | None = None
        self._trace_expires: datetime | None = None

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

        if self._trace_active_for(entity_id, trace.timestamp):
            log.info(
                "trace[%s]: %s -> %s | norm %s -> %s | mapped=%s persisted=%s result=%s",
                entity_id,
                old_raw,
                new_raw,
                normalized_old,
                normalized_new,
                mapping_found,
                persisted,
                result,
            )

    def recent(self, entity_id: str | None = None, limit: int = 50) -> list[EventTrace]:
        limit = max(1, min(limit, _GLOBAL_CAP))
        src = self._by_entity.get(entity_id, deque()) if entity_id else self._recent
        return list(src)[-limit:][::-1]  # newest first

    def last_for(self, entity_id: str) -> EventTrace | None:
        buf = self._by_entity.get(entity_id)
        return buf[-1] if buf else None

    # -- trace mode -------------------------------------------------------- #

    def start_trace(self, entity_id: str, *, user: str | None = None) -> TraceStatus:
        self._trace_entity = entity_id
        self._trace_expires = datetime.now(UTC) + timedelta(seconds=TRACE_TTL_SECONDS)
        log.info("trace: started for %s (15 min) by %s", entity_id, user or "?")
        return self.trace_status()

    def stop_trace(self) -> TraceStatus:
        if self._trace_entity is not None:
            log.info("trace: stopped for %s", self._trace_entity)
        self._trace_entity = None
        self._trace_expires = None
        return self.trace_status()

    def trace_status(self) -> TraceStatus:
        now = datetime.now(UTC)
        if self._trace_expires is not None and now >= self._trace_expires:
            self._trace_entity = None
            self._trace_expires = None
        remaining = (
            int((self._trace_expires - now).total_seconds())
            if self._trace_expires is not None
            else 0
        )
        return TraceStatus(
            active=self._trace_entity is not None,
            entity_id=self._trace_entity,
            expires_at=self._trace_expires,
            remaining_seconds=max(0, remaining),
        )

    def _trace_active_for(self, entity_id: str, now: datetime) -> bool:
        if self._trace_entity != entity_id or self._trace_expires is None:
            return False
        if now >= self._trace_expires:
            self._trace_entity = None
            self._trace_expires = None
            return False
        return True
