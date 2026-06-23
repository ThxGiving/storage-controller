"""Persistent application settings (key/value in app_settings).

Phase 3 introduces the heartbeat interval and retention settings. Retention
values are stored and surfaced but destructive cleanup is intentionally NOT run
automatically (see DOCS); only an explicit, tested operation may delete data.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSetting

# Setting keys
HEARTBEAT_INTERVAL_SECONDS = "collector.heartbeat_interval_seconds"
RETENTION_RAW_DAYS = "retention.raw_samples_days"
RETENTION_STATE_DAYS = "retention.state_samples_days"

DEFAULTS: dict[str, str] = {
    HEARTBEAT_INTERVAL_SECONDS: "300",  # 5 minutes
    RETENTION_RAW_DAYS: "730",  # 24 months
    RETENTION_STATE_DAYS: "730",
}


@dataclass
class CollectorSettings:
    heartbeat_interval_seconds: int
    retention_raw_days: int
    retention_state_days: int


async def get_setting(session: AsyncSession, key: str) -> str:
    value = await session.scalar(select(AppSetting.value).where(AppSetting.key == key))
    if value is None:
        return DEFAULTS.get(key, "")
    return value


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    existing = await session.get(AppSetting, key)
    if existing is None:
        session.add(AppSetting(key=key, value=value))
    else:
        existing.value = value


async def _get_int(session: AsyncSession, key: str) -> int:
    value = await get_setting(session, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(DEFAULTS[key])


async def get_collector_settings(session: AsyncSession) -> CollectorSettings:
    return CollectorSettings(
        heartbeat_interval_seconds=await _get_int(session, HEARTBEAT_INTERVAL_SECONDS),
        retention_raw_days=await _get_int(session, RETENTION_RAW_DAYS),
        retention_state_days=await _get_int(session, RETENTION_STATE_DAYS),
    )
