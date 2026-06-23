"""Application settings API (Phase 3A): heartbeat interval & retention."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..schemas import AppSettingsOut, AppSettingsUpdate
from ..settings_store import (
    HEARTBEAT_INTERVAL_SECONDS,
    RETENTION_RAW_DAYS,
    RETENTION_STATE_DAYS,
    get_collector_settings,
    set_setting,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=AppSettingsOut)
async def get_settings_endpoint(db: AsyncSession = Depends(get_db)) -> AppSettingsOut:
    s = await get_collector_settings(db)
    return AppSettingsOut(
        heartbeat_interval_seconds=s.heartbeat_interval_seconds,
        retention_raw_days=s.retention_raw_days,
        retention_state_days=s.retention_state_days,
    )


@router.patch("", response_model=AppSettingsOut)
async def update_settings_endpoint(
    payload: AppSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AppSettingsOut:
    if payload.heartbeat_interval_seconds is not None:
        await set_setting(
            db, HEARTBEAT_INTERVAL_SECONDS, str(payload.heartbeat_interval_seconds)
        )
    if payload.retention_raw_days is not None:
        await set_setting(db, RETENTION_RAW_DAYS, str(payload.retention_raw_days))
    if payload.retention_state_days is not None:
        await set_setting(db, RETENTION_STATE_DAYS, str(payload.retention_state_days))
    await db.commit()

    # Let the collector pick up a new heartbeat interval immediately.
    collector = getattr(request.app.state, "collector", None)
    if collector is not None:
        await collector.refresh_index()

    s = await get_collector_settings(db)
    return AppSettingsOut(
        heartbeat_interval_seconds=s.heartbeat_interval_seconds,
        retention_raw_days=s.retention_raw_days,
        retention_state_days=s.retention_state_days,
    )
