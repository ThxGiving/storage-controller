"""Operational dashboard aggregation (Phase 3B).

One request returns everything the dashboard cards need: per-unit current values
(from the live HA cache), server-computed operational status, and a 24h
mini-chart series from the independent sample store. Status is computed in the
backend so the UI and any future logic share one source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..ha.manager import STATUS_CONNECTED, HAConnectionManager
from ..models import (
    NUMERIC_ROLES,
    OPEN_INCIDENT_STATES,
    EntityRole,
    Incident,
    Quality,
    SensorSample,
    StorageUnit,
)
from ..normalization import normalize_bool, normalize_numeric
from ..schemas import (
    DashboardIncident,
    DashboardResponse,
    DashboardRoleValue,
    DashboardSpark,
    DashboardSummary,
    DashboardUnit,
)
from ..status_logic import compute_status
from .deps import get_manager

router = APIRouter(prefix="/api", tags=["dashboard"])

_NUMERIC = {r.value for r in NUMERIC_ROLES}
_SPARK_POINTS = 48


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _role_value(role: str, entity, invert: bool) -> DashboardRoleValue:
    """Build a role value from the current cached HA entity (or a missing one)."""
    if entity is None:
        return DashboardRoleValue(
            role=EntityRole(role),
            entity_id="",
            exists=False,
            available=False,
            quality=Quality.missing.value,
        )
    if role in _NUMERIC:
        res = normalize_numeric(entity.state, entity.unit_of_measurement)
        return DashboardRoleValue(
            role=EntityRole(role),
            entity_id=entity.entity_id,
            exists=True,
            available=entity.available,
            quality=res.quality.value,
            numeric_c=res.normalized_value_c,
            raw=res.raw_value,
            unit=entity.unit_of_measurement,
        )
    res_b = normalize_bool(entity.state, invert=invert)
    return DashboardRoleValue(
        role=EntityRole(role),
        entity_id=entity.entity_id,
        exists=True,
        available=entity.available,
        quality=res_b.quality.value,
        raw=res_b.raw_state,
        unit=entity.unit_of_measurement,
        bool_value=res_b.normalized_bool,
    )


async def _spark(db: AsyncSession, unit_id: int) -> list[DashboardSpark]:
    start = datetime.now(UTC) - timedelta(hours=24)
    rows = (
        await db.execute(
            select(
                SensorSample.event_timestamp,
                SensorSample.normalized_value_c,
                SensorSample.quality,
            )
            .where(
                SensorSample.storage_unit_id == unit_id,
                SensorSample.role == EntityRole.room_temperature.value,
                SensorSample.event_timestamp >= start,
            )
            .order_by(SensorSample.event_timestamp.asc())
        )
    ).all()
    if not rows:
        return []
    if len(rows) <= _SPARK_POINTS:
        return [
            DashboardSpark(
                t=_as_utc(ts),
                v=v if (q == Quality.valid.value and v is not None) else None,
            )
            for ts, v, q in rows
        ]
    bucket = max(int(24 * 3600 / _SPARK_POINTS), 1)
    grouped: dict[int, list[float]] = {}
    for ts, v, q in rows:
        if q != Quality.valid.value or v is None:
            continue
        idx = int((_as_utc(ts) - start).total_seconds() // bucket)
        grouped.setdefault(idx, []).append(v)
    out: list[DashboardSpark] = []
    for idx in range(_SPARK_POINTS + 1):
        center = start + timedelta(seconds=bucket * idx + bucket / 2)
        vals = grouped.get(idx)
        out.append(DashboardSpark(t=center, v=(sum(vals) / len(vals)) if vals else None))
    return out


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    manager: HAConnectionManager = Depends(get_manager),
) -> DashboardResponse:
    connection = manager.status()
    connected = connection.status == STATUS_CONNECTED
    now = datetime.now(UTC)

    units_db = (
        await db.scalars(
            select(StorageUnit)
            .where(StorageUnit.enabled.is_(True))
            .options(selectinload(StorageUnit.assignments))
            .order_by(StorageUnit.sort_order, StorageUnit.id)
        )
    ).all()

    # Open incidents grouped by unit (one query).
    open_incidents = (
        await db.scalars(
            select(Incident)
            .where(Incident.state.in_([s.value for s in OPEN_INCIDENT_STATES]))
            .order_by(Incident.opened_at.asc())
        )
    ).all()
    incidents_by_unit: dict[int, list[DashboardIncident]] = {}
    open_count = unack_count = undoc_count = 0
    for inc in open_incidents:
        documented = bool(inc.cause or inc.corrective_action)
        acknowledged = inc.acknowledged_at is not None
        open_count += 1
        if not acknowledged:
            unack_count += 1
        if not documented:
            undoc_count += 1
        if inc.storage_unit_id is not None:
            incidents_by_unit.setdefault(inc.storage_unit_id, []).append(
                DashboardIncident(
                    id=inc.id,
                    type=inc.type,
                    state=inc.state,
                    opened_at=_as_utc(inc.opened_at),
                    confirmed_at=_as_utc(inc.confirmed_at),
                    extreme_value_c=inc.extreme_value_c,
                    defrost_overlap=inc.defrost_overlap,
                    acknowledged=acknowledged,
                    documented=documented,
                )
            )

    summary = DashboardSummary(
        total=len(units_db),
        open_incidents=open_count,
        unacknowledged_incidents=unack_count,
        undocumented_incidents=undoc_count,
    )
    out_units: list[DashboardUnit] = []
    last_sample_at: datetime | None = _as_utc(connection.last_event_at)

    for unit in units_db:
        by_role = {a.role: a for a in unit.assignments}
        room_assignment = by_role.get(EntityRole.room_temperature.value)

        room_value: DashboardRoleValue | None = None
        last_update: datetime | None = None
        normalized_c: float | None = None
        quality: str | None = None
        room_exists = False

        if room_assignment is not None:
            entity = manager.get_entity(room_assignment.entity_id)
            room_value = _role_value(EntityRole.room_temperature.value, entity, False)
            if entity is not None:
                room_exists = True
                normalized_c = room_value.numeric_c
                quality = room_value.quality
                last_update = _as_utc(entity.last_updated or entity.last_changed)
                if last_update and (last_sample_at is None or last_update > last_sample_at):
                    last_sample_at = last_update

        # Staleness: connected + valid but no update within the offline delay.
        is_stale = bool(
            connected
            and quality == Quality.valid.value
            and last_update is not None
            and (now - last_update).total_seconds() > max(unit.offline_delay_seconds, 60)
        )

        status = compute_status(
            connected=connected,
            has_room_assignment=room_assignment is not None,
            room_exists=room_exists,
            quality=quality,
            normalized_c=normalized_c,
            lower_limit_c=unit.lower_limit_c,
            upper_limit_c=unit.upper_limit_c,
            warning_margin_c=unit.warning_margin_c,
            is_stale=is_stale,
        )
        setattr(summary, status, getattr(summary, status) + 1)

        # Optional role chips (only roles that are actually assigned).
        roles: list[DashboardRoleValue] = []
        setpoint_c: float | None = None
        for role, assignment in by_role.items():
            if role == EntityRole.room_temperature.value:
                continue
            rv = _role_value(
                role, manager.get_entity(assignment.entity_id), assignment.invert_state
            )
            roles.append(rv)
            if role == EntityRole.setpoint.value:
                setpoint_c = rv.numeric_c

        out_units.append(
            DashboardUnit(
                id=unit.id,
                name=unit.name,
                short_report_name=unit.short_report_name,
                unit_type=unit.unit_type,
                profile_name=unit.applied_profile_name,
                lower_limit_c=unit.lower_limit_c,
                upper_limit_c=unit.upper_limit_c,
                warning_margin_c=unit.warning_margin_c,
                setpoint_c=setpoint_c,
                status=status,
                room=room_value,
                last_update=last_update,
                roles=roles,
                spark=await _spark(db, unit.id),
                active_incidents=incidents_by_unit.get(unit.id, []),
            )
        )

    return DashboardResponse(
        connection=connection,
        summary=summary,
        units=out_units,
        last_sample_at=last_sample_at,
        timezone=(datetime.now().astimezone().tzname() or "UTC"),
        generated_at=now,
    )
