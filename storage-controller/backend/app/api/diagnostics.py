"""Targeted defrost / entity / event diagnostics (Phase 4.6.1).

Read-only tracing of the event → sample → defrost-engine chain for configured
mappings. Deliberately scoped: no arbitrary SQL or raw database access, and no
tokens/credentials are ever returned or logged. Trace mode is restricted to
authenticated Home Assistant users (Ingress) and auto-expires after 15 minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..diagnostics import DiagnosticsRecorder, EventTrace
from ..errors import AppError
from ..ha.manager import HAConnectionManager
from ..models import (
    OPEN_DEFROST_STATUSES,
    DefrostCycle,
    DefrostStatus,
    EntityAssignment,
    EntityRole,
    StorageUnit,
)
from ..normalization import (
    BoolMapping,
    normalize_bool,
    normalize_numeric,
    parse_bool_mapping,
)
from ..schemas import (
    DefrostDiagnosticsResponse,
    DefrostMappingDiagnostic,
    DiagnosticsEnableIn,
    DiagnosticsLogsResponse,
    DiagnosticsModeOut,
    EntityAssignmentDiagnostic,
    EntityDiagnostic,
    EventTraceOut,
    LogEntryOut,
    RecentEventsResponse,
    ValueMappingOut,
)
from .deps import get_manager

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


def _recorder(request: Request) -> DiagnosticsRecorder:
    rec = getattr(request.app.state, "diagnostics", None)
    if rec is None:
        rec = DiagnosticsRecorder()
        request.app.state.diagnostics = rec
    return rec


def _require_user(request: Request) -> str:
    """Trace mode is admin/authenticated only. Ingress is HA-auth-gated; require a
    forwarded user identity so trace control isn't anonymous."""
    user = request.headers.get("X-Remote-User-Name") or request.headers.get(
        "X-Remote-User-Id"
    )
    if not user:
        raise AppError("admin_required", status_code=403)
    return user


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def _mapping_out(m: BoolMapping) -> ValueMappingOut:
    return ValueMappingOut(
        active=sorted(m.active),
        inactive=sorted(m.inactive),
        invert=m.invert,
        configured=m.configured,
    )


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _trace_out(t: EventTrace) -> EventTraceOut:
    return EventTraceOut(
        timestamp=t.timestamp,
        entity_id=t.entity_id,
        storage_unit_id=t.storage_unit_id,
        role=t.role,
        old_raw=t.old_raw,
        new_raw=t.new_raw,
        normalized_old=t.normalized_old,
        normalized_new=t.normalized_new,
        mapping_found=t.mapping_found,
        persisted=t.persisted,
        engine_relevant=t.engine_relevant,
        result=t.result,
    )


@router.get("/defrost", response_model=DefrostDiagnosticsResponse)
async def defrost_diagnostics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    manager: HAConnectionManager = Depends(get_manager),
) -> DefrostDiagnosticsResponse:
    rec = _recorder(request)
    now = datetime.now(UTC)

    rows = (
        await db.execute(
            select(EntityAssignment, StorageUnit)
            .join(StorageUnit, EntityAssignment.storage_unit_id == StorageUnit.id)
            .where(EntityAssignment.role == EntityRole.defrost.value)
        )
    ).all()

    mappings: list[DefrostMappingDiagnostic] = []
    for assignment, unit in rows:
        mapping = parse_bool_mapping(assignment.value_mapping_json)
        entity = manager.get_entity(assignment.entity_id)
        raw_state = getattr(entity, "state", None) if entity else None
        available = bool(getattr(entity, "available", False)) if entity else False
        res = normalize_bool(raw_state, invert=assignment.invert_state, mapping=mapping)

        # Open + most-recent cycle for this unit.
        open_cycle = await db.scalar(
            select(DefrostCycle)
            .where(
                DefrostCycle.storage_unit_id == unit.id,
                DefrostCycle.status.in_([s.value for s in OPEN_DEFROST_STATUSES]),
            )
            .order_by(DefrostCycle.started_at.desc())
            .limit(1)
        )
        last_cycle = await db.scalar(
            select(DefrostCycle)
            .where(DefrostCycle.storage_unit_id == unit.id)
            .order_by(DefrostCycle.started_at.desc())
            .limit(1)
        )
        last_completed = await db.scalar(
            select(DefrostCycle.id)
            .where(
                DefrostCycle.storage_unit_id == unit.id,
                DefrostCycle.status == DefrostStatus.completed.value,
            )
            .order_by(DefrostCycle.started_at.desc())
            .limit(1)
        )

        last_event = rec.last_for(assignment.entity_id)
        last_persisted = next(
            (e for e in rec.recent(assignment.entity_id, 100) if e.persisted), None
        )
        last_ignored = next(
            (e for e in rec.recent(assignment.entity_id, 100) if e.result != "stored"), None
        )

        engine_state = open_cycle.status if open_cycle is not None else "no_cycle"

        problem = _defrost_problem(
            enabled=unit.defrost_evaluation_enabled,
            entity=entity,
            available=available,
            res_bool=res.normalized_bool,
            res_reason=res.reason,
            raw_state=raw_state,
        )

        mappings.append(
            DefrostMappingDiagnostic(
                storage_unit_id=unit.id,
                storage_unit_name=unit.name,
                defrost_entity_id=assignment.entity_id,
                entity_domain=_domain(assignment.entity_id),
                evaluation_enabled=unit.defrost_evaluation_enabled,
                entity_exists=entity is not None,
                available=available,
                raw_state=raw_state,
                normalized_bool=res.normalized_bool,
                normalization_reason=res.reason,
                value_mapping=_mapping_out(mapping),
                last_state_change=_as_utc(
                    getattr(entity, "last_changed", None) if entity else None
                ),
                last_event_received=last_event.timestamp if last_event else None,
                last_event_persisted=last_persisted.timestamp if last_persisted else None,
                last_engine_evaluation=manager.last_incident_eval_at,
                engine_state=engine_state,
                active_cycle_id=open_cycle.id if open_cycle else None,
                last_cycle_started=_as_utc(last_cycle.started_at) if last_cycle else None,
                last_cycle_ended=_as_utc(last_cycle.ended_at) if last_cycle else None,
                last_completed_cycle_id=last_completed,
                last_cycle_reconstructed=bool(last_cycle.reconstructed) if last_cycle else False,
                last_ignored_reason=last_ignored.result if last_ignored else None,
                connected=manager.connected,
                reconnect_attempts=manager.status().reconnect_attempts,
                last_connected_at=manager.status().last_connected_at,
                problem=problem,
            )
        )

    return DefrostDiagnosticsResponse(
        generated_at=now,
        connected=manager.connected,
        last_event_at=manager.last_event_at,
        last_engine_evaluation=manager.last_incident_eval_at,
        mappings=mappings,
    )


def _defrost_problem(
    *, enabled: bool, entity, available: bool, res_bool, res_reason: str, raw_state
) -> str | None:
    if entity is None:
        return "entity_not_found"
    if not enabled:
        return "evaluation_disabled"
    if not available or res_reason in ("unavailable", "unknown", "missing"):
        return "entity_unavailable"
    if res_bool is None and res_reason == "unrecognized_state":
        return f"normalization_failed: raw state {raw_state!r} is not on/off — add a value mapping"
    return None


@router.get("/entities/{entity_id}", response_model=EntityDiagnostic)
async def entity_diagnostic(
    entity_id: str,
    manager: HAConnectionManager = Depends(get_manager),
    db: AsyncSession = Depends(get_db),
) -> EntityDiagnostic:
    entity = manager.get_entity(entity_id)
    assignments = (
        await db.scalars(
            select(EntityAssignment)
            .where(EntityAssignment.entity_id == entity_id)
            .options(selectinload(EntityAssignment.storage_unit))
        )
    ).all()

    raw_state = getattr(entity, "state", None) if entity else None
    unit_meas = getattr(entity, "unit_of_measurement", None) if entity else None
    num = normalize_numeric(raw_state, unit_meas)
    bool_res = normalize_bool(raw_state)

    assigned: list[EntityAssignmentDiagnostic] = []
    for a in assignments:
        assigned.append(
            EntityAssignmentDiagnostic(
                storage_unit_id=a.storage_unit_id,
                storage_unit_name=a.storage_unit.name if a.storage_unit else "",
                role=a.role,
                value_mapping=_mapping_out(parse_bool_mapping(a.value_mapping_json)),
            )
        )

    return EntityDiagnostic(
        entity_id=entity_id,
        domain=_domain(entity_id),
        exists=entity is not None,
        available=bool(getattr(entity, "available", False)) if entity else False,
        raw_state=raw_state,
        last_changed=_as_utc(getattr(entity, "last_changed", None) if entity else None),
        last_updated=_as_utc(getattr(entity, "last_updated", None) if entity else None),
        numeric_c=num.normalized_value_c,
        numeric_quality=num.quality.value,
        normalized_bool=bool_res.normalized_bool,
        bool_reason=bool_res.reason,
        assignments=assigned,
    )


@router.get("/events/recent", response_model=RecentEventsResponse)
async def recent_events(
    request: Request,
    entity_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> RecentEventsResponse:
    rec = _recorder(request)
    events = [_trace_out(e) for e in rec.recent(entity_id, limit)]
    return RecentEventsResponse(entity_id=entity_id, events=events)


def _mode_out(s) -> DiagnosticsModeOut:
    return DiagnosticsModeOut(
        enabled=s.enabled,
        expires_at=s.expires_at,
        remaining_seconds=s.remaining_seconds,
        enabled_by=s.enabled_by,
        buffered_logs=s.buffered_logs,
    )


@router.get("/logging/status", response_model=DiagnosticsModeOut)
async def logging_status(request: Request) -> DiagnosticsModeOut:
    return _mode_out(_recorder(request).mode_status())


@router.post("/logging/enable", response_model=DiagnosticsModeOut)
async def logging_enable(
    payload: DiagnosticsEnableIn, request: Request
) -> DiagnosticsModeOut:
    user = _require_user(request)
    rec = _recorder(request)
    rec.enable_mode(minutes=payload.minutes, user=user)
    rec.log("info", "diagnostics", "diagnostics mode enabled", fields={"minutes": payload.minutes})
    return _mode_out(rec.mode_status())


@router.post("/logging/disable", response_model=DiagnosticsModeOut)
async def logging_disable(request: Request) -> DiagnosticsModeOut:
    _require_user(request)
    return _mode_out(_recorder(request).disable_mode())


@router.get("/logs", response_model=DiagnosticsLogsResponse)
async def get_logs(
    request: Request,
    component: str | None = Query(default=None),
    storage_unit_id: int | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=200),
) -> DiagnosticsLogsResponse:
    _require_user(request)
    rec = _recorder(request)
    entries = rec.query_logs(
        component=component,
        storage_unit_id=storage_unit_id,
        entity_id=entity_id,
        severity=severity,
        since=since,
        limit=limit,
    )
    return DiagnosticsLogsResponse(
        mode=_mode_out(rec.mode_status()),
        count=len(entries),
        entries=[
            LogEntryOut(
                timestamp=e.timestamp,
                severity=e.severity,
                component=e.component,
                message=e.message,
                storage_unit_id=e.storage_unit_id,
                entity_id=e.entity_id,
                fields=e.fields,
            )
            for e in entries
        ],
    )
