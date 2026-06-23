"""Incident engine (Phase 4).

Evaluates each storage unit's conditions against the configured limits and timing
rules, persisting incidents and their lifecycle events. The timing decisions live
in :mod:`app.incident_logic` (pure, unit-tested). This module handles condition
derivation, persistence, extreme tracking, defrost overlap and the audit trail.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from .incident_logic import Decision, EvalResult, decide
from .models import (
    OPEN_INCIDENT_STATES,
    AuditEvent,
    EntityRole,
    Incident,
    IncidentEvent,
    IncidentState,
    IncidentType,
    Quality,
    StorageUnit,
)
from .normalization import normalize_bool, normalize_numeric

log = logging.getLogger("incident_engine")

# Grace period before a Home-Assistant disconnect becomes an active incident.
DISCONNECT_GRACE_SECONDS = 60


@dataclass
class UnitReading:
    """Snapshot used to evaluate one unit's incident conditions."""

    storage_unit_id: int
    now: datetime
    connected: bool
    has_room: bool
    room_exists: bool
    quality: str | None
    normalized_c: float | None
    last_update: datetime | None
    defrost_on: bool | None
    lower: float | None
    upper: float | None
    warning_margin: float
    violation_delay: int
    recovery_delay: int
    offline_delay: int


@dataclass
class _Cond:
    type: IncidentType
    result: EvalResult
    value_c: float | None
    limit_c: float | None
    violation_delay: int
    recovery_delay: int


def _temp_result(r: UnitReading, *, high: bool) -> EvalResult:
    if not r.connected or r.quality != Quality.valid.value or r.normalized_c is None:
        return EvalResult.UNKNOWN
    limit = r.upper if high else r.lower
    if limit is None:
        return EvalResult.CLEAR
    crossed = r.normalized_c > limit if high else r.normalized_c < limit
    return EvalResult.ACTIVE if crossed else EvalResult.CLEAR


def _conditions(r: UnitReading) -> list[_Cond]:
    conds: list[_Cond] = []

    if r.upper is not None:
        conds.append(
            _Cond(
                IncidentType.temperature_high,
                _temp_result(r, high=True),
                r.normalized_c,
                r.upper,
                r.violation_delay,
                r.recovery_delay,
            )
        )
    if r.lower is not None:
        conds.append(
            _Cond(
                IncidentType.temperature_low,
                _temp_result(r, high=False),
                r.normalized_c,
                r.lower,
                r.violation_delay,
                r.recovery_delay,
            )
        )

    # Sensor data-quality conditions (only meaningful while connected).
    if not r.connected:
        unavailable = invalid = stale = EvalResult.UNKNOWN
    else:
        unavailable = (
            EvalResult.ACTIVE
            if r.quality in (Quality.unavailable.value, Quality.unknown.value)
            else EvalResult.CLEAR
        )
        invalid = EvalResult.ACTIVE if r.quality == Quality.invalid.value else EvalResult.CLEAR
        if r.quality == Quality.valid.value and r.last_update is not None:
            age = (r.now - r.last_update).total_seconds()
            stale = EvalResult.ACTIVE if age > max(r.offline_delay, 60) else EvalResult.CLEAR
        else:
            stale = EvalResult.CLEAR

    od, rd = r.offline_delay, r.recovery_delay
    conds.append(_Cond(IncidentType.sensor_unavailable, unavailable, None, None, od, rd))
    conds.append(_Cond(IncidentType.sensor_invalid, invalid, None, None, od, rd))
    conds.append(_Cond(IncidentType.sensor_stale, stale, None, None, od, rd))
    return conds


def _update_extreme(incident: Incident, cond: _Cond, now: datetime) -> None:
    if cond.value_c is None:
        return
    high = cond.type == IncidentType.temperature_high
    cur = incident.extreme_value_c
    if cur is None or (cond.value_c > cur if high else cond.value_c < cur):
        incident.extreme_value_c = cond.value_c
        incident.extreme_at = now


class IncidentEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def evaluate_readings(self, readings: list[UnitReading], *, connected: bool) -> None:
        """Evaluate explicit readings (used by tests with crafted timestamps)."""
        async with self._session_factory() as session:
            for reading in readings:
                await self._evaluate_unit(session, reading)
            await self._evaluate_disconnect(session, connected, _now())
            await session.commit()

    async def run(self, get_entity: Callable[[str], object], *, connected: bool) -> None:
        """Build readings from the DB + live entity cache and evaluate them."""
        async with self._session_factory() as session:
            readings = await self._build_readings(session, get_entity, connected)
            for reading in readings:
                await self._evaluate_unit(session, reading)
            await self._evaluate_disconnect(session, connected, _now())
            await session.commit()

    async def _build_readings(
        self, session: AsyncSession, get_entity: Callable[[str], object], connected: bool
    ) -> list[UnitReading]:
        now = _now()
        units = (
            await session.scalars(
                select(StorageUnit)
                .where(StorageUnit.enabled.is_(True))
                .options(selectinload(StorageUnit.assignments))
            )
        ).all()

        readings: list[UnitReading] = []
        for unit in units:
            by_role = {a.role: a for a in unit.assignments}
            room = by_role.get(EntityRole.room_temperature.value)
            quality: str | None = None
            normalized_c: float | None = None
            last_update: datetime | None = None
            room_exists = False
            if room is not None:
                entity = get_entity(room.entity_id)
                if entity is not None:
                    room_exists = True
                    res = normalize_numeric(
                        getattr(entity, "state", None),
                        getattr(entity, "unit_of_measurement", None),
                        plausible_min_c=unit.plausible_min_c,
                        plausible_max_c=unit.plausible_max_c,
                    )
                    quality = res.quality.value
                    normalized_c = res.normalized_value_c
                    last_update = _utc(
                        getattr(entity, "last_updated", None)
                        or getattr(entity, "last_changed", None)
                    )

            defrost_on: bool | None = None
            defrost = by_role.get(EntityRole.defrost.value)
            if defrost is not None:
                d_entity = get_entity(defrost.entity_id)
                if d_entity is not None:
                    defrost_on = normalize_bool(
                        getattr(d_entity, "state", None), invert=defrost.invert_state
                    ).normalized_bool

            readings.append(
                UnitReading(
                    storage_unit_id=unit.id,
                    now=now,
                    connected=connected,
                    has_room=room is not None,
                    room_exists=room_exists,
                    quality=quality,
                    normalized_c=normalized_c,
                    last_update=last_update,
                    defrost_on=defrost_on,
                    lower=unit.lower_limit_c,
                    upper=unit.upper_limit_c,
                    warning_margin=unit.warning_margin_c,
                    violation_delay=unit.violation_delay_seconds,
                    recovery_delay=unit.recovery_delay_seconds,
                    offline_delay=unit.offline_delay_seconds,
                )
            )
        return readings

    async def _open_incidents(
        self, session: AsyncSession, storage_unit_id: int | None
    ) -> dict[str, Incident]:
        stmt = (
            select(Incident)
            .where(Incident.state.in_([s.value for s in OPEN_INCIDENT_STATES]))
            .options(selectinload(Incident.events))
        )
        if storage_unit_id is None:
            stmt = stmt.where(Incident.storage_unit_id.is_(None))
        else:
            stmt = stmt.where(Incident.storage_unit_id == storage_unit_id)
        rows = (await session.scalars(stmt)).all()
        return {i.type: i for i in rows}

    async def _evaluate_unit(self, session: AsyncSession, r: UnitReading) -> None:
        open_by_type = await self._open_incidents(session, r.storage_unit_id)
        for cond in _conditions(r):
            existing = open_by_type.get(cond.type.value)
            if existing is not None:
                _update_extreme(existing, cond, r.now)
                if r.defrost_on:
                    existing.defrost_overlap = True
                self._apply(session, existing, cond, r.now)
            elif cond.result == EvalResult.ACTIVE:
                self._open(session, r.storage_unit_id, cond, r.now, defrost_on=r.defrost_on)

    async def _evaluate_disconnect(
        self, session: AsyncSession, connected: bool, now: datetime
    ) -> None:
        open_by_type = await self._open_incidents(session, None)
        existing = open_by_type.get(IncidentType.home_assistant_disconnected.value)
        cond = _Cond(
            IncidentType.home_assistant_disconnected,
            EvalResult.CLEAR if connected else EvalResult.ACTIVE,
            None,
            None,
            DISCONNECT_GRACE_SECONDS,
            0,
        )
        if existing is not None:
            self._apply(session, existing, cond, now)
        elif cond.result == EvalResult.ACTIVE:
            self._open(session, None, cond, now, defrost_on=None)

    # -- persistence helpers ---------------------------------------------- #

    def _open(
        self,
        session: AsyncSession,
        storage_unit_id: int | None,
        cond: _Cond,
        now: datetime,
        *,
        defrost_on: bool | None,
    ) -> None:
        incident = Incident(
            storage_unit_id=storage_unit_id,
            type=cond.type.value,
            state=IncidentState.pending_violation.value,
            opened_at=now,
            limit_value_c=cond.limit_c,
            extreme_value_c=cond.value_c,
            extreme_at=now if cond.value_c is not None else None,
            defrost_overlap=bool(defrost_on),
        )
        session.add(incident)
        incident.events.append(
            IncidentEvent(
                timestamp=now,
                kind="transition",
                from_state=None,
                to_state=IncidentState.pending_violation.value,
                value_c=cond.value_c,
                detail="opened",
            )
        )
        session.add(
            AuditEvent(
                component="incident_engine",
                action="incident_opened",
                object_type="incident_type",
                object_id=cond.type.value,
                detail=f"unit={storage_unit_id}",
            )
        )
        log.info(
            "incident: opened %s for unit %s", cond.type.value, storage_unit_id
        )

    def _apply(
        self, session: AsyncSession, incident: Incident, cond: _Cond, now: datetime
    ) -> None:
        decision: Decision = decide(
            state=IncidentState(incident.state),
            now=now,
            opened_at=_utc(incident.opened_at),
            confirmed_at=_utc(incident.confirmed_at),
            recovering_at=_utc(incident.recovering_at),
            result=cond.result,
            violation_delay=cond.violation_delay,
            recovery_delay=cond.recovery_delay,
        )
        if not decision.changed:
            return

        from_state = incident.state
        incident.state = decision.state.value
        incident.confirmed_at = decision.confirmed_at
        incident.recovering_at = decision.recovering_at
        if decision.closed_at is not None:
            incident.closed_at = decision.closed_at

        incident.events.append(
            IncidentEvent(
                timestamp=now,
                kind="transition",
                from_state=from_state,
                to_state=decision.state.value,
                value_c=cond.value_c,
            )
        )
        action = (
            "incident_confirmed"
            if decision.state == IncidentState.active_violation
            else "incident_closed"
            if decision.state == IncidentState.closed
            else "incident_transition"
        )
        session.add(
            AuditEvent(
                component="incident_engine",
                action=action,
                object_type="incident",
                object_id=str(incident.id),
                detail=f"{from_state}->{decision.state.value}",
            )
        )
        log.info(
            "incident: %s %s -> %s (unit %s)",
            cond.type.value,
            from_state,
            decision.state.value,
            incident.storage_unit_id,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
