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

from . import diagnostics as diag
from .incident_logic import Decision, EvalResult, decide
from .learning_service import get_active_model, recompute_learning
from .models import (
    OPEN_DEFROST_STATUSES,
    OPEN_INCIDENT_STATES,
    AuditEvent,
    DefrostClassification,
    DefrostCycle,
    DefrostStatus,
    EntityRole,
    Incident,
    IncidentEvent,
    IncidentState,
    IncidentType,
    Quality,
    StateSample,
    StorageUnit,
)
from .normalization import normalize_bool, normalize_numeric, parse_bool_mapping
from .timeutil import ensure_utc

log = logging.getLogger("incident_engine")

# Grace period before a Home-Assistant disconnect becomes an active incident.
DISCONNECT_GRACE_SECONDS = 60

# Delay before a door-open or hardware-alarm state triggers a new incident.
DOOR_OPEN_DELAY_SECONDS = 300   # 5 min — brief door opens are normal
CONTROLLER_ALARM_DELAY_SECONDS = 60  # 1 min — hardware alarms are urgent


# Conservative built-in bounds for gross-failure detection BEFORE a learned model
# is approved. These detect a stuck defrost / failed recovery but are NEVER used
# to suppress or reclassify an excursion as safe.
FALLBACK_MAX_DEFROST_SECONDS = 2700  # 45 min
FALLBACK_MAX_RECOVERY_SECONDS = 5400  # 90 min

# When a unit has no upper safety limit (e.g. a freezer configured with only a
# lower limit), recovery is considered complete once the room returns to within
# this margin of its pre-defrost baseline temperature.
RECOVERY_BASELINE_MARGIN_C = 1.0


@dataclass
class LearnedEnvelope:
    """Approved, learned operational envelope (gates excursion suppression)."""

    max_room_peak_c: float | None = None
    max_evaporator_peak_c: float | None = None
    max_defrost_seconds: int | None = None
    max_recovery_seconds: int | None = None


@dataclass
class DefrostSettings:
    enabled: bool = False
    # Recovery is "complete" when the room returns to its normal upper safety
    # limit — a configured safety limit, never a learned value.
    recovery_target_c: float | None = None
    abnormal_creates_incident: bool = True
    # Present only when a learned model has been explicitly approved.
    learned: LearnedEnvelope | None = None

    @property
    def has_model(self) -> bool:
        return self.learned is not None

    @property
    def max_defrost_seconds(self) -> int:
        if self.learned and self.learned.max_defrost_seconds:
            return self.learned.max_defrost_seconds
        return FALLBACK_MAX_DEFROST_SECONDS

    @property
    def max_recovery_seconds(self) -> int:
        if self.learned and self.learned.max_recovery_seconds:
            return self.learned.max_recovery_seconds
        return FALLBACK_MAX_RECOVERY_SECONDS

    @property
    def max_room_c(self) -> float | None:
        return self.learned.max_room_peak_c if self.learned else None

    @property
    def max_evaporator_c(self) -> float | None:
        return self.learned.max_evaporator_peak_c if self.learned else None


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
    # Defrost context (Phase 4 defrost). evaporator_c optional.
    evaporator_c: float | None = None
    defrost_entity_id: str | None = None
    defrost_assignment_id: int | None = None
    defrost: DefrostSettings | None = None
    # Door / alarm (Phase 7). None = entity not assigned; True/False = known state.
    door_open: bool | None = None
    alarm_active: bool | None = None


@dataclass
class DefrostContext:
    in_window: bool = False
    suppress_high: bool = False


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

    if r.door_open is not None:
        door_res = EvalResult.ACTIVE if r.door_open else EvalResult.CLEAR
        conds.append(_Cond(IncidentType.door_open, door_res, None, None,
                           DOOR_OPEN_DELAY_SECONDS, rd))

    if r.alarm_active is not None:
        alarm_res = EvalResult.ACTIVE if r.alarm_active else EvalResult.CLEAR
        conds.append(_Cond(IncidentType.controller_alarm, alarm_res, None, None,
                           CONTROLLER_ALARM_DELAY_SECONDS, rd))

    return conds


def _update_extreme(incident: Incident, cond: _Cond, now: datetime) -> None:
    if cond.value_c is None:
        return
    high = cond.type == IncidentType.temperature_high
    cur = incident.extreme_value_c
    if cur is None or (cond.value_c > cur if high else cond.value_c < cur):
        incident.extreme_value_c = cond.value_c
        incident.extreme_at = now


# If the latest persisted "on" defrost sample is older than this when a cycle is
# first observed, the rising edge was missed (restart/gap) → reconstruct.
RECONSTRUCT_THRESHOLD_SECONDS = 120


class IncidentEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        # Optional diagnostics recorder (set by the app at startup).
        self.diagnostics: object | None = None

    def _diag(
        self, entity_id: str | None, unit_id: int | None, result: str, **fields: object
    ) -> None:
        d = self.diagnostics
        if d is None:
            return
        # Structured log (mode-gated) + an engine event-trace entry.
        d.log("info", "defrost_engine", result, storage_unit_id=unit_id,
              entity_id=entity_id, fields=fields)
        if entity_id is not None:
            d.record(
                entity_id=entity_id, storage_unit_id=unit_id, role="defrost",
                old_raw=None, new_raw=None, normalized_old=None, normalized_new=None,
                mapping_found=True, persisted=False, engine_relevant=True, result=result,
            )

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
                    last_update = ensure_utc(
                        getattr(entity, "last_updated", None)
                        or getattr(entity, "last_changed", None)
                    )

            defrost_on: bool | None = None
            defrost_entity_id: str | None = None
            defrost_assignment_id: int | None = None
            defrost = by_role.get(EntityRole.defrost.value)
            if defrost is not None:
                defrost_entity_id = defrost.entity_id
                defrost_assignment_id = defrost.id
                d_entity = get_entity(defrost.entity_id)
                if d_entity is not None:
                    defrost_on = normalize_bool(
                        getattr(d_entity, "state", None),
                        invert=defrost.invert_state,
                        mapping=parse_bool_mapping(defrost.value_mapping_json),
                    ).normalized_bool

            evaporator_c: float | None = None
            evap = by_role.get(EntityRole.evaporator_temperature.value)
            if evap is not None:
                e_entity = get_entity(evap.entity_id)
                if e_entity is not None:
                    e_res = normalize_numeric(
                        getattr(e_entity, "state", None),
                        getattr(e_entity, "unit_of_measurement", None),
                    )
                    if e_res.quality.value == Quality.valid.value:
                        evaporator_c = e_res.normalized_value_c

            door_open: bool | None = None
            door_assignment = by_role.get(EntityRole.door.value)
            if door_assignment is not None:
                d_entity = get_entity(door_assignment.entity_id)
                if d_entity is not None:
                    door_open = normalize_bool(
                        getattr(d_entity, "state", None),
                        invert=door_assignment.invert_state,
                        mapping=parse_bool_mapping(door_assignment.value_mapping_json),
                    ).normalized_bool

            alarm_active: bool | None = None
            alarm_assignment = by_role.get(EntityRole.alarm.value)
            if alarm_assignment is not None:
                a_entity = get_entity(alarm_assignment.entity_id)
                if a_entity is not None:
                    alarm_active = normalize_bool(
                        getattr(a_entity, "state", None),
                        invert=alarm_assignment.invert_state,
                        mapping=parse_bool_mapping(alarm_assignment.value_mapping_json),
                    ).normalized_bool

            learned: LearnedEnvelope | None = None
            if unit.defrost_evaluation_enabled and defrost is not None:
                model = await get_active_model(session, unit.id)
                if model is not None:
                    learned = LearnedEnvelope(
                        max_room_peak_c=model.max_room_peak_c,
                        max_evaporator_peak_c=model.max_evaporator_peak_c,
                        max_defrost_seconds=model.max_defrost_seconds,
                        max_recovery_seconds=model.max_recovery_seconds,
                    )

            defrost_settings = DefrostSettings(
                enabled=unit.defrost_evaluation_enabled and defrost is not None,
                recovery_target_c=unit.upper_limit_c,
                abnormal_creates_incident=unit.abnormal_defrost_creates_incident,
                learned=learned,
            )

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
                    evaporator_c=evaporator_c,
                    defrost_entity_id=defrost_entity_id,
                    defrost_assignment_id=defrost_assignment_id,
                    defrost=defrost_settings,
                    door_open=door_open,
                    alarm_active=alarm_active,
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

        # Defrost-aware context (no-op when no defrost entity / disabled).
        ctx = await self._evaluate_defrost(session, r, open_by_type)

        for cond in _conditions(r):
            # Suppress only a NEW high excursion that meets every expected-defrost
            # condition OR the door is known-open (temp rise expected); an
            # already-open temperature_high keeps progressing in both cases.
            if (
                cond.type == IncidentType.temperature_high
                and cond.result == EvalResult.ACTIVE
                and (ctx.suppress_high or r.door_open is True)
                and open_by_type.get(cond.type.value) is None
            ):
                continue

            # An excursion that falls inside a defrost window but is NOT suppressed
            # is marked "potentially defrost-related" (defrost_overlap) — it stays
            # a real incident; it is never auto-closed or downgraded.
            related = bool(r.defrost_on) or ctx.in_window

            existing = open_by_type.get(cond.type.value)
            if existing is not None:
                _update_extreme(existing, cond, r.now)
                if related:
                    existing.defrost_overlap = True
                self._apply(session, existing, cond, r.now)
            elif cond.result == EvalResult.ACTIVE:
                self._open(session, r.storage_unit_id, cond, r.now, defrost_on=related)

        # Defrost-anomaly incidents (abnormal_defrost / recovery_timeout) are opened
        # directly in active_violation and have no per-condition tick to advance them.
        # Close them once the defrost is physically over and the room has recovered.
        self._resolve_defrost_incidents(session, r, open_by_type, ctx)

    async def _evaluate_defrost(
        self, session: AsyncSession, r: UnitReading, open_by_type: dict[str, Incident]
    ) -> DefrostContext:
        ds = r.defrost
        # No defrost entity configured or evaluation disabled -> normal logic,
        # never suppress or attribute peaks to defrost.
        if ds is None or not ds.enabled or r.defrost_on is None:
            return DefrostContext()

        now = r.now
        cycle = await session.scalar(
            select(DefrostCycle)
            .where(
                DefrostCycle.storage_unit_id == r.storage_unit_id,
                DefrostCycle.status.in_([s.value for s in OPEN_DEFROST_STATUSES]),
            )
            .order_by(DefrostCycle.started_at.desc())
            .limit(1)
        )
        valid_room = r.quality == Quality.valid.value and r.normalized_c is not None

        # Rising edge: open a cycle. If the defrost was already "on" well before
        # this first observation (app restart / WS gap), reconstruct an
        # approximate start from the last persisted "on" sample instead of now.
        if r.defrost_on and cycle is None:
            started_at = now
            reconstructed = False
            if r.defrost_assignment_id is not None:
                prior_on = await session.scalar(
                    select(StateSample)
                    .where(
                        StateSample.entity_assignment_id == r.defrost_assignment_id,
                        StateSample.normalized_bool.is_(True),
                    )
                    .order_by(StateSample.event_timestamp.desc())
                    .limit(1)
                )
                prior_ts = ensure_utc(prior_on.event_timestamp) if prior_on is not None else None
                if (
                    prior_ts is not None
                    and (now - prior_ts).total_seconds() > RECONSTRUCT_THRESHOLD_SECONDS
                ):
                    started_at = prior_ts
                    reconstructed = True
            cycle = DefrostCycle(
                storage_unit_id=r.storage_unit_id,
                source_entity_id=r.defrost_entity_id,
                started_at=started_at,
                status=DefrostStatus.active.value,
                reconstructed=reconstructed,
                triggering_rule="reconstructed_on_restart" if reconstructed else None,
                initial_room_temperature_c=r.normalized_c if valid_room else None,
                peak_room_temperature_c=r.normalized_c if valid_room else None,
                initial_evaporator_temperature_c=r.evaporator_c,
                peak_evaporator_temperature_c=r.evaporator_c,
            )
            session.add(cycle)
            session.add(
                AuditEvent(
                    component="incident_engine",
                    action="defrost_started",
                    object_type="storage_unit",
                    object_id=str(r.storage_unit_id),
                    detail="reconstructed_on_restart" if reconstructed else None,
                )
            )
            self._diag(
                r.defrost_entity_id, r.storage_unit_id, diag.CYCLE_STARTED,
                reconstructed=reconstructed,
            )
            log.info(
                "defrost: cycle %s for unit %s",
                "reconstructed" if reconstructed else "started",
                r.storage_unit_id,
            )

        if cycle is None:
            return DefrostContext()

        # Track peaks (only from valid data).
        if valid_room and (
            cycle.peak_room_temperature_c is None
            or r.normalized_c > cycle.peak_room_temperature_c
        ):
            cycle.peak_room_temperature_c = r.normalized_c
        if r.evaporator_c is not None and (
            cycle.peak_evaporator_temperature_c is None
            or r.evaporator_c > cycle.peak_evaporator_temperature_c
        ):
            cycle.peak_evaporator_temperature_c = r.evaporator_c

        started = ensure_utc(cycle.started_at)
        in_window = False

        if cycle.status == DefrostStatus.active.value:
            in_window = True
            if not r.defrost_on:
                cycle.status = DefrostStatus.recovering.value
                cycle.ended_at = now
                cycle.recovery_started_at = now
                self._diag(r.defrost_entity_id, r.storage_unit_id, diag.CYCLE_ENDED)
            elif (now - started).total_seconds() > ds.max_defrost_seconds:
                self._mark_cycle_abnormal(
                    session, cycle, "defrost_duration_exceeded", r, open_by_type, now
                )
            elif ds.max_room_c is not None and valid_room and r.normalized_c > ds.max_room_c:
                self._mark_cycle_abnormal(
                    session, cycle, "room_envelope_exceeded", r, open_by_type, now
                )
            elif (
                ds.max_evaporator_c is not None
                and r.evaporator_c is not None
                and r.evaporator_c > ds.max_evaporator_c
            ):
                self._mark_cycle_abnormal(
                    session, cycle, "evaporator_envelope_exceeded", r, open_by_type, now
                )

        if cycle.status == DefrostStatus.recovering.value:
            in_window = True
            rec_started = ensure_utc(cycle.recovery_started_at) or now
            # Recovery target: the unit's upper safety limit, or — when none is
            # configured — a return to the pre-defrost baseline. Without this
            # fallback a freezer with only a lower limit could never complete a
            # cycle and would eventually be flagged as a recovery timeout.
            recovery_target = ds.recovery_target_c
            if recovery_target is None and cycle.initial_room_temperature_c is not None:
                recovery_target = cycle.initial_room_temperature_c + RECOVERY_BASELINE_MARGIN_C
            if r.defrost_on:
                cycle.status = DefrostStatus.active.value
                cycle.ended_at = None
                cycle.recovery_started_at = None
            elif (
                valid_room
                and recovery_target is not None
                and r.normalized_c <= recovery_target
            ):
                cycle.recovered_at = now
                cycle.status = DefrostStatus.completed.value
                if cycle.classification is None:
                    cycle.classification = DefrostClassification.expected_defrost.value
                in_window = False
                # A fresh complete cycle is new learning evidence — refresh the
                # suggestion and drift status (never auto-approves anything).
                unit = await session.get(StorageUnit, r.storage_unit_id)
                if unit is not None:
                    await recompute_learning(session, unit, now)
            elif (now - rec_started).total_seconds() > ds.max_recovery_seconds:
                # The hard recovery limit is reached — the cycle must close either
                # way so it never hangs open. What it means depends on the data:
                in_window = False
                if valid_room:
                    # A valid reading proves the room is still above target past
                    # the limit → a genuine recovery failure.
                    cycle.status = DefrostStatus.abnormal.value
                    cycle.classification = DefrostClassification.recovery_timeout.value
                    cycle.triggering_rule = "recovery_timeout"
                    self._open_defrost_incident(
                        session, r, open_by_type, IncidentType.recovery_timeout, now,
                        "recovery_timeout", value=r.normalized_c,
                    )
                else:
                    # No valid room reading for the whole recovery window — we
                    # cannot judge recovery. That is a sensor/connection gap
                    # (surfaced on its own via sensor_unavailable /
                    # home_assistant_disconnected), not a defrost anomaly. Close
                    # the cycle as incomplete rather than raising a false timeout.
                    cycle.status = DefrostStatus.incomplete.value

        # Suppression: a NEW high excursion may be reclassified as an expected
        # defrost excursion ONLY when an APPROVED learned model exists and the
        # excursion stays fully inside its learned envelope and duration. Without
        # an approved model nothing is suppressed — the excursion remains a real
        # incident (flagged potentially-defrost-related upstream).
        suppress = False
        if (
            ds.has_model
            and in_window
            and valid_room
            and r.upper is not None
            and r.normalized_c > r.upper
            and cycle.status in (DefrostStatus.active.value, DefrostStatus.recovering.value)
        ):
            pre_existing = open_by_type.get(IncidentType.temperature_high.value) is not None
            within_envelope = ds.max_room_c is not None and r.normalized_c <= ds.max_room_c
            within_duration = (now - started).total_seconds() <= ds.max_defrost_seconds
            if not pre_existing and within_envelope and within_duration:
                suppress = True
                cycle.classification = DefrostClassification.expected_defrost_excursion.value

        return DefrostContext(in_window=in_window, suppress_high=suppress)

    def _mark_cycle_abnormal(
        self,
        session: AsyncSession,
        cycle: DefrostCycle,
        rule: str,
        r: UnitReading,
        open_by_type: dict[str, Incident],
        now: datetime,
    ) -> None:
        cycle.status = DefrostStatus.abnormal.value
        cycle.classification = DefrostClassification.abnormal_defrost.value
        cycle.triggering_rule = rule
        if r.defrost and r.defrost.abnormal_creates_incident:
            self._open_defrost_incident(
                session, r, open_by_type, IncidentType.abnormal_defrost, now, rule,
                value=cycle.peak_room_temperature_c,
            )

    def _open_defrost_incident(
        self,
        session: AsyncSession,
        r: UnitReading,
        open_by_type: dict[str, Incident],
        itype: IncidentType,
        now: datetime,
        rule: str,
        *,
        value: float | None = None,
    ) -> None:
        if open_by_type.get(itype.value) is not None:
            return  # already open — no duplicate
        inc = Incident(
            storage_unit_id=r.storage_unit_id,
            type=itype.value,
            state=IncidentState.active_violation.value,
            opened_at=now,
            confirmed_at=now,
            extreme_value_c=value,
            extreme_at=now if value is not None else None,
        )
        session.add(inc)
        inc.events.append(
            IncidentEvent(
                timestamp=now,
                kind="transition",
                from_state=None,
                to_state=IncidentState.active_violation.value,
                detail=rule,
            )
        )
        session.add(
            AuditEvent(
                component="incident_engine",
                action="incident_opened",
                object_type="incident_type",
                object_id=itype.value,
                detail=f"unit={r.storage_unit_id} rule={rule}",
            )
        )
        open_by_type[itype.value] = inc
        log.info("incident: opened %s for unit %s (%s)", itype.value, r.storage_unit_id, rule)

    # Defrost-anomaly incident types are point-in-time markers, not progressing
    # conditions: they are opened directly in active_violation and never appear in
    # ``_conditions`` so the normal tick never closes them.
    _DEFROST_INCIDENT_TYPES = (IncidentType.abnormal_defrost, IncidentType.recovery_timeout)

    def _resolve_defrost_incidents(
        self,
        session: AsyncSession,
        r: UnitReading,
        open_by_type: dict[str, Incident],
        ctx: DefrostContext,
    ) -> None:
        open_defrost = [
            open_by_type[t.value]
            for t in self._DEFROST_INCIDENT_TYPES
            if open_by_type.get(t.value) is not None
        ]
        if not open_defrost:
            return
        # Hold while we cannot confirm the anomaly is over: a defrost cycle is still
        # in its active/recovering window, the defrost is still on, or its state is
        # unknown (entity missing / HA disconnected). Never close unverifiable.
        if ctx.in_window or r.defrost_on is None or r.defrost_on:
            return
        valid_room = r.quality == Quality.valid.value and r.normalized_c is not None
        if not valid_room:
            return
        # Recovered = room back within the upper safety limit (when one is configured).
        if r.upper is not None and r.normalized_c > r.upper:
            return
        for inc in open_defrost:
            self._close_incident(session, inc, r.now, "defrost_recovered")

    def _close_incident(
        self, session: AsyncSession, incident: Incident, now: datetime, detail: str
    ) -> None:
        from_state = incident.state
        incident.state = IncidentState.closed.value
        if incident.recovering_at is None:
            incident.recovering_at = now
        incident.closed_at = now
        incident.events.append(
            IncidentEvent(
                timestamp=now,
                kind="transition",
                from_state=from_state,
                to_state=IncidentState.closed.value,
                detail=detail,
            )
        )
        session.add(
            AuditEvent(
                component="incident_engine",
                action="incident_closed",
                object_type="incident",
                object_id=str(incident.id),
                detail=f"{from_state}->closed ({detail})",
            )
        )
        log.info(
            "incident: closed %s for unit %s (%s)",
            incident.type,
            incident.storage_unit_id,
            detail,
        )

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
            opened_at=ensure_utc(incident.opened_at),
            confirmed_at=ensure_utc(incident.confirmed_at),
            recovering_at=ensure_utc(incident.recovering_at),
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


