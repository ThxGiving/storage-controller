"""History-import API, embedded in the storage-unit flow (Phase 5.1).

No separate navigation section: availability + import are scoped under a storage
unit. Import runs asynchronously (never blocks unit creation); the client polls
the job status. Imports never create live incidents.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import get_db, get_session_factory
from ..errors import ERROR_STORAGE_UNIT_NOT_FOUND, AppError
from ..history_import import (
    RECOMMENDED_RANGE,
    check_availability,
    run_import,
    summarize_chunks,
)
from ..models import (
    EntityAssignment,
    EntityRole,
    HistoryImport,
    HistoryImportStatus,
    HistoryRange,
    StorageUnit,
)
from ..schemas import (
    HistoryAvailabilityOut,
    HistoryDateRange,
    HistoryImportOut,
    HistoryImportStart,
)
from ..settings_store import get_timezone_name
from .deps import get_manager

log = logging.getLogger("api")

router = APIRouter(prefix="/api/storage-units", tags=["history-import"])

# Job ids currently running / requested-to-cancel in THIS process. After a
# restart these are empty, so a job left "importing" by a dead process is
# treated as stale and can be resumed.
_RUNNING: set[int] = set()
_CANCEL: set[int] = set()

# A resumable job is one that didn't finish cleanly and isn't actively running.
_RESUMABLE = {
    HistoryImportStatus.failed.value,
    HistoryImportStatus.partial.value,
    HistoryImportStatus.cancelled.value,
}


def _ingress_user(request: Request) -> str | None:
    return request.headers.get("X-Remote-User-Name") or request.headers.get("X-Remote-User-Id")


async def _unit(db: AsyncSession, unit_id: int) -> StorageUnit:
    u = await db.scalar(
        select(StorageUnit).where(StorageUnit.id == unit_id).options(
            selectinload(StorageUnit.assignments)
        )
    )
    if u is None:
        raise AppError(ERROR_STORAGE_UNIT_NOT_FOUND, status_code=404)
    return u


def _out(j: HistoryImport) -> HistoryImportOut:
    ranges = summarize_chunks(j.chunks_json)
    return HistoryImportOut(
        id=j.id,
        storage_unit_id=j.storage_unit_id,
        entity_id=j.entity_id,
        requested_range=j.requested_range,
        status=j.status,
        raw_from=j.raw_from,
        raw_to=j.raw_to,
        raw_count=j.raw_count,
        stats_from=j.stats_from,
        stats_to=j.stats_to,
        stats_count=j.stats_count,
        error_message=j.error_message,
        imported_ranges=[HistoryDateRange(**r) for r in ranges["imported"]],
        failed_ranges=[HistoryDateRange(**r) for r in ranges["failed"]],
        created_at=j.created_at,
        finished_at=j.finished_at,
    )


@router.get("/{unit_id}/history/availability", response_model=HistoryAvailabilityOut)
async def availability(
    unit_id: int,
    request: Request,
    entity_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    manager=Depends(get_manager),
) -> HistoryAvailabilityOut:
    await _unit(db, unit_id)
    settings = get_settings()
    rest = getattr(request.app.state, "rest", None)
    if rest is None:
        return HistoryAvailabilityOut(
            state="no_history", raw_available=False, has_statistics=False,
            recommended_range=RECOMMENDED_RANGE, connected=False,
        )
    info = await check_availability(
        rest, entity_id=entity_id, ws_url=settings.ha_ws_url, token=settings.ha_token
    )
    return HistoryAvailabilityOut(
        state=info["state"],
        raw_available=info["raw_available"],
        has_statistics=info["has_statistics"],
        recommended_range=info["recommended_range"],
        connected=manager.connected,
        earliest=info.get("earliest"),
        latest=info.get("latest"),
    )


@router.get("/{unit_id}/history/import", response_model=HistoryImportOut | None)
async def latest_import(
    unit_id: int, db: AsyncSession = Depends(get_db)
) -> HistoryImportOut | None:
    await _unit(db, unit_id)
    j = await db.scalar(
        select(HistoryImport)
        .where(HistoryImport.storage_unit_id == unit_id)
        .order_by(HistoryImport.created_at.desc())
        .limit(1)
    )
    return _out(j) if j else None


@router.post("/{unit_id}/history/import", response_model=HistoryImportOut, status_code=201)
async def start_import(
    unit_id: int,
    payload: HistoryImportStart,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HistoryImportOut:
    unit = await _unit(db, unit_id)
    # The primary temperature sensor must be assigned to this unit.
    assignment = next(
        (
            a for a in unit.assignments
            if a.role == EntityRole.room_temperature.value and a.entity_id == payload.entity_id
        ),
        None,
    )
    if assignment is None:
        raise AppError("entity_not_assigned", status_code=422)
    rng = payload.range if payload.range in {r.value for r in HistoryRange} else RECOMMENDED_RANGE

    latest = await db.scalar(
        select(HistoryImport)
        .where(HistoryImport.storage_unit_id == unit_id)
        .order_by(HistoryImport.created_at.desc())
        .limit(1)
    )

    resume = False
    job = None
    if latest is not None:
        actively_running = latest.id in _RUNNING
        if latest.status == HistoryImportStatus.importing.value and actively_running:
            # A live import is already running for this unit — return it as-is.
            return _out(latest)
        # Resume a not-cleanly-finished job (failed/partial/cancelled, or an
        # "importing" job orphaned by a restart) when the range matches.
        stale = latest.status == HistoryImportStatus.importing.value and not actively_running
        if (latest.status in _RESUMABLE or stale) and latest.requested_range == rng:
            job = latest
            resume = True
            _CANCEL.discard(job.id)

    if job is None:
        job = HistoryImport(
            storage_unit_id=unit_id,
            entity_id=payload.entity_id,
            requested_range=rng,
            status=HistoryImportStatus.importing.value,
            created_by=_ingress_user(request),
            created_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()

    settings = get_settings()
    rest = getattr(request.app.state, "rest", None)
    entity = request.app.state.ha_manager.get_entity(payload.entity_id)
    entity_unit = getattr(entity, "unit_of_measurement", None) if entity else None
    tz_name = await get_timezone_name(db)

    # Run asynchronously; the request returns immediately (non-blocking).
    asyncio.create_task(
        _run(job.id, assignment.id, unit_id, rest, settings.ha_ws_url, settings.ha_token,
             entity_unit, tz_name, resume),
        name=f"history-import-{job.id}",
    )
    return _out(job)


@router.post("/{unit_id}/history/import/cancel", response_model=HistoryImportOut | None)
async def cancel_import(
    unit_id: int, db: AsyncSession = Depends(get_db)
) -> HistoryImportOut | None:
    await _unit(db, unit_id)
    job = await db.scalar(
        select(HistoryImport)
        .where(
            HistoryImport.storage_unit_id == unit_id,
            HistoryImport.status == HistoryImportStatus.importing.value,
        )
        .order_by(HistoryImport.created_at.desc())
        .limit(1)
    )
    if job is None:
        return None
    _CANCEL.add(job.id)  # the running task stops at the next window boundary
    return _out(job)


async def _run(
    job_id, assignment_id, unit_id, rest, ws_url, token, entity_unit, tz_name, resume=False
) -> None:
    if rest is None:
        return
    _RUNNING.add(job_id)
    factory = get_session_factory()
    try:
        async with factory() as session:
            job = await session.get(HistoryImport, job_id)
            assignment = await session.get(EntityAssignment, assignment_id)
            if job is None or assignment is None:
                # Unit/sensor was deleted while queued — nothing to import.
                return
            try:
                await run_import(
                    session, job=job, assignment=assignment, storage_unit_id=unit_id,
                    rest=rest, ws_url=ws_url, token=token, entity_unit=entity_unit,
                    tz_name=tz_name, resume=resume, is_cancelled=lambda: job_id in _CANCEL,
                )
            except Exception as exc:  # noqa: BLE001
                job.status = HistoryImportStatus.failed.value
                job.error_message = "History import failed."
                log.warning("history: task error: %s", type(exc).__name__)
                await session.commit()
    finally:
        _RUNNING.discard(job_id)
        _CANCEL.discard(job_id)
