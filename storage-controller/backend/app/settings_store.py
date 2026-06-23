"""Persistent application settings (key/value in app_settings).

Phase 3 introduced heartbeat + retention. Phase 4.5 adds the display timezone,
the minimum temperature delta, aggregate retention, and the storage budget /
thresholds. Retention values are honoured by the bounded maintenance job; nothing
is deleted outside that explicit, tested path.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSetting
from .timezone import DEFAULT_TIMEZONE

# -- keys -------------------------------------------------------------------- #
DISPLAY_TIMEZONE = "display.timezone"
HEARTBEAT_INTERVAL_SECONDS = "collector.heartbeat_interval_seconds"
MIN_TEMP_DELTA_C = "collector.min_temp_delta_c"
RETENTION_RAW_DAYS = "retention.raw_samples_days"
RETENTION_AGG15_DAYS = "retention.aggregate_15min_days"
RETENTION_AGG_HOURLY_DAYS = "retention.aggregate_hourly_days"
STORAGE_BUDGET_BYTES = "storage.budget_bytes"
STORAGE_WARNING_PCT = "storage.warning_pct"
STORAGE_CRITICAL_PCT = "storage.critical_pct"
STORAGE_EMERGENCY_PCT = "storage.emergency_pct"
MAINTENANCE_LAST_RUN = "maintenance.last_run"

DEFAULTS: dict[str, str] = {
    DISPLAY_TIMEZONE: DEFAULT_TIMEZONE,
    HEARTBEAT_INTERVAL_SECONDS: "300",  # 5 minutes
    MIN_TEMP_DELTA_C: "0.1",
    RETENTION_RAW_DAYS: "730",  # 24 months
    RETENTION_AGG15_DAYS: "1825",  # 5 years
    RETENTION_AGG_HOURLY_DAYS: "3650",  # 10 years
    STORAGE_BUDGET_BYTES: str(2 * 1024 * 1024 * 1024),  # 2 GB
    STORAGE_WARNING_PCT: "70",
    STORAGE_CRITICAL_PCT: "85",
    STORAGE_EMERGENCY_PCT: "95",
}


@dataclass
class CollectorSettings:
    heartbeat_interval_seconds: int
    min_temp_delta_c: float


@dataclass
class MaintenanceSettings:
    retention_raw_days: int
    retention_agg15_days: int
    retention_agg_hourly_days: int
    storage_budget_bytes: int
    warning_pct: int
    critical_pct: int
    emergency_pct: int


async def get_setting(session: AsyncSession, key: str) -> str:
    value = await session.scalar(select(AppSetting.value).where(AppSetting.key == key))
    return DEFAULTS.get(key, "") if value is None else value


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    existing = await session.get(AppSetting, key)
    if existing is None:
        session.add(AppSetting(key=key, value=value))
    else:
        existing.value = value


async def _int(session: AsyncSession, key: str) -> int:
    try:
        return int(await get_setting(session, key))
    except (TypeError, ValueError):
        return int(DEFAULTS[key])


async def _float(session: AsyncSession, key: str) -> float:
    try:
        return float(await get_setting(session, key))
    except (TypeError, ValueError):
        return float(DEFAULTS[key])


async def get_collector_settings(session: AsyncSession) -> CollectorSettings:
    return CollectorSettings(
        heartbeat_interval_seconds=await _int(session, HEARTBEAT_INTERVAL_SECONDS),
        min_temp_delta_c=await _float(session, MIN_TEMP_DELTA_C),
    )


async def get_maintenance_settings(session: AsyncSession) -> MaintenanceSettings:
    return MaintenanceSettings(
        retention_raw_days=await _int(session, RETENTION_RAW_DAYS),
        retention_agg15_days=await _int(session, RETENTION_AGG15_DAYS),
        retention_agg_hourly_days=await _int(session, RETENTION_AGG_HOURLY_DAYS),
        storage_budget_bytes=await _int(session, STORAGE_BUDGET_BYTES),
        warning_pct=await _int(session, STORAGE_WARNING_PCT),
        critical_pct=await _int(session, STORAGE_CRITICAL_PCT),
        emergency_pct=await _int(session, STORAGE_EMERGENCY_PCT),
    )


async def get_timezone_name(session: AsyncSession) -> str:
    return await get_setting(session, DISPLAY_TIMEZONE)
