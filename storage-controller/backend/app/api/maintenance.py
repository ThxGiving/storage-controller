"""Maintenance & storage status API (Phase 4.5)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..maintenance import MaintenanceRunner
from ..models import MaintenanceRun
from ..schemas import MaintenanceStatus, StorageCategory

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


def _runner(request: Request) -> MaintenanceRunner:
    return request.app.state.maintenance


async def _status(request: Request, db: AsyncSession) -> MaintenanceStatus:
    runner = _runner(request)
    usage = runner.current_usage() or await runner.refresh_storage()
    last = await db.scalar(select(MaintenanceRun).order_by(MaintenanceRun.id.desc()).limit(1))
    next_run = (last.started_at + timedelta(days=1)) if last and last.started_at else None
    return MaintenanceStatus(
        last_run=last.finished_at if last else None,
        next_run=next_run,
        last_result=last.detail if last else None,
        database_bytes=usage.database_bytes,
        wal_bytes=usage.wal_bytes,
        reports_bytes=usage.reports_bytes,
        uploads_bytes=usage.uploads_bytes,
        logs_bytes=usage.logs_bytes,
        app_total_bytes=usage.app_total_bytes,
        free_bytes=usage.free_bytes,
        free_percent=usage.free_percent,
        budget_bytes=usage.budget_bytes,
        budget_used_percent=usage.budget_used_percent,
        level=usage.level,
        categories=[
            StorageCategory(name="database", bytes=usage.database_bytes),
            StorageCategory(name="wal", bytes=usage.wal_bytes),
            StorageCategory(name="reports", bytes=usage.reports_bytes),
            StorageCategory(name="uploads", bytes=usage.uploads_bytes),
            StorageCategory(name="logs", bytes=usage.logs_bytes),
        ],
    )


@router.get("/status", response_model=MaintenanceStatus)
async def maintenance_status(
    request: Request, db: AsyncSession = Depends(get_db)
) -> MaintenanceStatus:
    return await _status(request, db)


@router.post("/run", response_model=MaintenanceStatus)
async def maintenance_run(
    request: Request, db: AsyncSession = Depends(get_db)
) -> MaintenanceStatus:
    runner = _runner(request)
    await runner.run_once()
    # Reflect any emergency change to the collector immediately.
    collector = getattr(request.app.state, "collector", None)
    if collector is not None:
        collector.suspend_heartbeat = runner.emergency
    return await _status(request, db)
