"""Independent sample collector (Phase 3).

Records samples for entities assigned to configured storage units, derived from
the backend's single Home Assistant WebSocket connection. Only assigned entities
are recorded. Values are normalized and stored with quality flags; unavailable /
unknown / invalid readings are kept as gaps, never zeroed.

Deduplication strategy (also enforced at the DB level by
``UNIQUE(entity_assignment_id, event_timestamp)``):

* An in-memory ``last_event_ts`` per assignment (seeded from the DB on refresh)
  is the high-water mark. Incoming events with ``event_timestamp <= last_event_ts``
  are skipped. This makes reconnect reconciliation idempotent (the current state
  carries its existing ``last_changed`` which is not newer than what we stored)
  and drops out-of-order / replayed events safely.
* If a state genuinely changed during a disconnect, its ``last_changed`` is newer
  than the high-water mark, so the post-disconnect value is captured on reconnect.
* The UNIQUE constraint is a hard backstop across restarts/races; an
  IntegrityError is treated as a duplicate and ignored.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import (
    NUMERIC_ROLES,
    EntityAssignment,
    Quality,
    SampleSource,
    SensorSample,
    StateSample,
    StorageUnit,
)
from .normalization import normalize_bool, normalize_numeric
from .settings_store import get_collector_settings

log = logging.getLogger("collector")

_NUMERIC_ROLE_VALUES = {r.value for r in NUMERIC_ROLES}


@dataclass
class AssignmentTarget:
    entity_id: str
    storage_unit_id: int
    entity_assignment_id: int
    role: str
    invert_state: bool
    plausible_min_c: float | None
    plausible_max_c: float | None
    numeric: bool


def _as_utc(ts: datetime | None) -> datetime | None:
    """Coerce a (possibly tz-naive, e.g. from SQLite) datetime to UTC-aware."""
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _event_timestamp(state: dict[str, Any]) -> datetime:
    return (
        _parse_ts(state.get("last_updated"))
        or _parse_ts(state.get("last_changed"))
        or datetime.now(UTC)
    )


class Collector:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._index: dict[str, list[AssignmentTarget]] = {}
        self._last_ts: dict[int, datetime | None] = {}
        # Last STORED value/quality per assignment (for min-delta and
        # state-change-only suppression). Numeric -> float; state -> bool.
        self._last_value: dict[int, float | bool | None] = {}
        self._last_quality: dict[int, str | None] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_interval = 300
        self._min_temp_delta = 0.1
        # Emergency storage mode suspends heartbeat samples (set by maintenance).
        self.suspend_heartbeat = False

    @property
    def monitored_entities(self) -> set[str]:
        return set(self._index.keys())

    @property
    def heartbeat_interval(self) -> int:
        return self._heartbeat_interval

    async def refresh_index(self) -> None:
        """(Re)build the assignment index and seed per-assignment high-water marks."""
        index: dict[str, list[AssignmentTarget]] = {}
        last_ts: dict[int, datetime | None] = {}
        last_value: dict[int, float | bool | None] = {}
        last_quality: dict[int, str | None] = {}

        async with self._session_factory() as session:
            settings = await get_collector_settings(session)
            self._heartbeat_interval = settings.heartbeat_interval_seconds
            self._min_temp_delta = settings.min_temp_delta_c

            result = await session.execute(
                select(EntityAssignment, StorageUnit)
                .join(StorageUnit, EntityAssignment.storage_unit_id == StorageUnit.id)
                .where(EntityAssignment.enabled.is_(True))
                .where(StorageUnit.enabled.is_(True))
            )
            for assignment, unit in result.all():
                target = AssignmentTarget(
                    entity_id=assignment.entity_id,
                    storage_unit_id=unit.id,
                    entity_assignment_id=assignment.id,
                    role=assignment.role,
                    invert_state=assignment.invert_state,
                    plausible_min_c=unit.plausible_min_c,
                    plausible_max_c=unit.plausible_max_c,
                    numeric=assignment.role in _NUMERIC_ROLE_VALUES,
                )
                index.setdefault(assignment.entity_id, []).append(target)

                # Seed high-water mark + last stored value/quality from the DB.
                table = SensorSample if target.numeric else StateSample
                value_col = (
                    SensorSample.normalized_value_c
                    if target.numeric
                    else StateSample.normalized_bool
                )
                row = (
                    await session.execute(
                        select(table.event_timestamp, value_col, table.quality)
                        .where(table.entity_assignment_id == assignment.id)
                        .order_by(table.event_timestamp.desc())
                        .limit(1)
                    )
                ).first()
                if row is not None:
                    last_ts[assignment.id] = _as_utc(row[0])
                    last_value[assignment.id] = row[1]
                    last_quality[assignment.id] = row[2]
                else:
                    last_ts[assignment.id] = None

        async with self._lock:
            self._index = index
            self._last_ts = last_ts
            self._last_value = last_value
            self._last_quality = last_quality
        log.info(
            "collector: monitoring %d entities (heartbeat %ds)",
            len(index),
            self._heartbeat_interval,
        )

    # -- event handling ---------------------------------------------------- #

    async def handle_state(
        self, entity_id: str, state: dict[str, Any] | None, source: SampleSource
    ) -> int:
        """Process a single entity state for all its assignments. Returns #stored."""
        targets = self._index.get(entity_id)
        if not targets or state is None:
            return 0

        event_ts = _event_timestamp(state)
        raw_state = state.get("state")
        attrs = state.get("attributes") or {}
        unit = attrs.get("unit_of_measurement")
        context_id = (state.get("context") or {}).get("id")

        stored = 0
        async with self._session_factory() as session:
            for target in targets:
                if await self._store_one(
                    session, target, event_ts, raw_state, unit, context_id, source
                ):
                    stored += 1
            await session.commit()
        return stored

    async def _store_one(
        self,
        session: AsyncSession,
        target: AssignmentTarget,
        event_ts: datetime,
        raw_state: Any,
        unit: str | None,
        context_id: str | None,
        source: SampleSource,
    ) -> bool:
        aid = target.entity_assignment_id
        high = self._last_ts.get(aid)
        if high is not None and event_ts <= high:
            return False  # duplicate / out-of-order

        raw_str = None if raw_state is None else str(raw_state)
        last_q = self._last_quality.get(aid)
        last_v = self._last_value.get(aid)

        if target.numeric:
            res = normalize_numeric(
                raw_str,
                unit,
                plausible_min_c=target.plausible_min_c,
                plausible_max_c=target.plausible_max_c,
            )
            # Bounded recording: keep quality/availability transitions; for stable
            # valid values, only store when the change >= the minimum delta.
            quality_changed = res.quality.value != last_q
            if (
                source is not SampleSource.reconcile
                and res.quality == Quality.valid
                and not quality_changed
                and isinstance(last_v, (int, float))
                and res.normalized_value_c is not None
                and abs(res.normalized_value_c - last_v) < self._min_temp_delta
            ):
                return False  # sub-threshold change suppressed
            if res.quality != Quality.valid and not quality_changed:
                return False  # repeated unavailable/unknown — record transition only
            row: SensorSample | StateSample = SensorSample(
                storage_unit_id=target.storage_unit_id,
                entity_assignment_id=aid,
                entity_id=target.entity_id,
                role=target.role,
                event_timestamp=event_ts,
                received_timestamp=datetime.now(UTC),
                raw_value=res.raw_value,
                numeric_value=res.numeric_value,
                normalized_value_c=res.normalized_value_c,
                original_unit=res.original_unit,
                quality=res.quality.value,
                source=source.value,
                source_context_id=context_id,
            )
        else:
            res_b = normalize_bool(raw_str, invert=target.invert_state)
            # Binary roles: store state changes only (incl. quality transitions).
            if (
                source is not SampleSource.reconcile
                and res_b.normalized_bool == last_v
                and res_b.quality.value == last_q
            ):
                return False
            row = StateSample(
                storage_unit_id=target.storage_unit_id,
                entity_assignment_id=aid,
                entity_id=target.entity_id,
                role=target.role,
                event_timestamp=event_ts,
                received_timestamp=datetime.now(UTC),
                raw_state=res_b.raw_state,
                normalized_bool=res_b.normalized_bool,
                quality=res_b.quality.value,
                source=source.value,
                source_context_id=context_id,
            )

        session.add(row)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return False

        self._last_ts[aid] = event_ts
        if target.numeric:
            self._last_value[aid] = res.normalized_value_c
            self._last_quality[aid] = res.quality.value
        else:
            self._last_value[aid] = res_b.normalized_bool
            self._last_quality[aid] = res_b.quality.value
        return True

    async def reconcile(self, states: list[dict[str, Any]]) -> int:
        """After (re)connect: process current states for monitored entities only."""
        stored = 0
        monitored = self.monitored_entities
        for state in states:
            entity_id = state.get("entity_id")
            if entity_id in monitored:
                stored += await self.handle_state(entity_id, state, SampleSource.reconcile)
        if stored:
            log.info("collector: reconcile stored %d new samples", stored)
        return stored

    # -- heartbeat --------------------------------------------------------- #

    async def heartbeat_tick(self, get_entity: Callable[[str], Any]) -> int:
        """Store heartbeat samples for stable, valid numeric entities once the
        interval has elapsed since their last sample.

        ``get_entity(entity_id)`` returns the current cached HAEntity (or None).
        """
        if self.suspend_heartbeat:
            return 0  # emergency storage mode: keep only essential event recording
        now = datetime.now(UTC)
        stored = 0
        async with self._session_factory() as session:
            for entity_id, targets in list(self._index.items()):
                entity = get_entity(entity_id)
                if entity is None or not entity.available:
                    continue
                for target in targets:
                    if not target.numeric:
                        continue
                    high = self._last_ts.get(target.entity_assignment_id)
                    if high and (now - high).total_seconds() < self._heartbeat_interval:
                        continue
                    res = normalize_numeric(
                        entity.state,
                        entity.unit_of_measurement,
                        plausible_min_c=target.plausible_min_c,
                        plausible_max_c=target.plausible_max_c,
                    )
                    if res.quality != Quality.valid:
                        continue
                    session.add(
                        SensorSample(
                            storage_unit_id=target.storage_unit_id,
                            entity_assignment_id=target.entity_assignment_id,
                            entity_id=entity_id,
                            role=target.role,
                            event_timestamp=now,
                            received_timestamp=now,
                            raw_value=res.raw_value,
                            numeric_value=res.numeric_value,
                            normalized_value_c=res.normalized_value_c,
                            original_unit=res.original_unit,
                            quality=Quality.valid.value,
                            source=SampleSource.heartbeat.value,
                            source_context_id=None,
                        )
                    )
                    try:
                        await session.flush()
                        self._last_ts[target.entity_assignment_id] = now
                        stored += 1
                    except IntegrityError:
                        await session.rollback()
            await session.commit()
        return stored
