"""Application settings API (Phase 3+4.5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..schemas import AppSettingsOut, AppSettingsUpdate
from ..settings_store import (
    DISPLAY_TIMEZONE,
    HEARTBEAT_INTERVAL_SECONDS,
    MIN_TEMP_DELTA_C,
    RETENTION_AGG15_DAYS,
    RETENTION_AGG_HOURLY_DAYS,
    RETENTION_RAW_DAYS,
    STORAGE_BUDGET_BYTES,
    STORAGE_CRITICAL_PCT,
    STORAGE_EMERGENCY_PCT,
    STORAGE_WARNING_PCT,
    get_collector_settings,
    get_maintenance_settings,
    get_timezone_name,
    set_setting,
)
from ..timezone import resolve_timezone

router = APIRouter(prefix="/api/settings", tags=["settings"])


async def _build(db: AsyncSession) -> AppSettingsOut:
    coll = await get_collector_settings(db)
    maint = await get_maintenance_settings(db)
    tz = resolve_timezone(await get_timezone_name(db))
    return AppSettingsOut(
        timezone=tz.iana,
        timezone_abbreviation=tz.abbreviation,
        timezone_offset=tz.offset,
        timezone_label=tz.label,
        heartbeat_interval_seconds=coll.heartbeat_interval_seconds,
        min_temp_delta_c=coll.min_temp_delta_c,
        retention_raw_days=maint.retention_raw_days,
        retention_agg15_days=maint.retention_agg15_days,
        retention_agg_hourly_days=maint.retention_agg_hourly_days,
        storage_budget_bytes=maint.storage_budget_bytes,
        warning_pct=maint.warning_pct,
        critical_pct=maint.critical_pct,
        emergency_pct=maint.emergency_pct,
    )


@router.get("", response_model=AppSettingsOut)
async def get_settings_endpoint(db: AsyncSession = Depends(get_db)) -> AppSettingsOut:
    return await _build(db)


_FIELD_KEYS = {
    "timezone": DISPLAY_TIMEZONE,
    "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
    "min_temp_delta_c": MIN_TEMP_DELTA_C,
    "retention_raw_days": RETENTION_RAW_DAYS,
    "retention_agg15_days": RETENTION_AGG15_DAYS,
    "retention_agg_hourly_days": RETENTION_AGG_HOURLY_DAYS,
    "storage_budget_bytes": STORAGE_BUDGET_BYTES,
    "warning_pct": STORAGE_WARNING_PCT,
    "critical_pct": STORAGE_CRITICAL_PCT,
    "emergency_pct": STORAGE_EMERGENCY_PCT,
}


@router.patch("", response_model=AppSettingsOut)
async def update_settings_endpoint(
    payload: AppSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AppSettingsOut:
    for field, key in _FIELD_KEYS.items():
        value = getattr(payload, field)
        if value is not None:
            await set_setting(db, key, str(value))
    await db.commit()

    # Let the collector pick up new heartbeat / min-delta immediately.
    collector = getattr(request.app.state, "collector", None)
    if collector is not None:
        await collector.refresh_index()

    return await _build(db)
