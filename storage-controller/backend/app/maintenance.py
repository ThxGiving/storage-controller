"""Bounded data maintenance (Phase 4.5).

Daily job: aggregate raw samples into 15-minute and hourly tiers, then delete
expired raw/aggregate rows in bounded batches — but only after the covering
aggregates exist. Reports, incidents, manual checks and audit records are never
deleted here. Also computes app-owned storage usage and a budget level, runs a
WAL checkpoint and a lightweight integrity check.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import get_settings
from .models import MaintenanceRun, SensorAggregate, SensorSample
from .settings_store import get_maintenance_settings

log = logging.getLogger("maintenance")

BUCKET_SECONDS = {"15min": 900, "hourly": 3600}


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def floor_bucket(ts: datetime, seconds: int) -> datetime:
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


async def aggregate(session: AsyncSession, tier: str, now: datetime, max_rows: int = 50000) -> int:
    secs = BUCKET_SECONDS[tier]
    last_complete = floor_bucket(now, secs)  # current (incomplete) bucket start

    # Start just after the newest already-aggregated bucket for this tier.
    newest = _as_utc(
        await session.scalar(
            select(func.max(SensorAggregate.bucket_start)).where(SensorAggregate.tier == tier)
        )
    )
    if newest is None:
        earliest = _as_utc(await session.scalar(select(func.min(SensorSample.event_timestamp))))
        if earliest is None:
            return 0
        start = floor_bucket(earliest, secs)
    else:
        start = newest + timedelta(seconds=secs)

    if start >= last_complete:
        return 0

    rows = (
        await session.execute(
            select(
                SensorSample.entity_assignment_id,
                SensorSample.storage_unit_id,
                SensorSample.role,
                SensorSample.event_timestamp,
                SensorSample.normalized_value_c,
                SensorSample.quality,
            )
            .where(
                SensorSample.event_timestamp >= start,
                SensorSample.event_timestamp < last_complete,
            )
            .order_by(SensorSample.event_timestamp.asc())
            .limit(max_rows)
        )
    ).all()

    buckets: dict[tuple[int, datetime], dict] = {}
    for aid, unit_id, role, ts, value, quality in rows:
        b = floor_bucket(_as_utc(ts), secs)
        acc = buckets.setdefault(
            (aid, b),
            {
                "unit": unit_id, "role": role, "count": 0, "valid": 0,
                "min": None, "max": None, "sum": 0.0,
            },
        )
        acc["count"] += 1
        if quality == "valid" and value is not None:
            acc["valid"] += 1
            acc["sum"] += value
            acc["min"] = value if acc["min"] is None else min(acc["min"], value)
            acc["max"] = value if acc["max"] is None else max(acc["max"], value)

    # Skip buckets already present (idempotent).
    existing = {
        (aid, _as_utc(bs))
        for aid, bs in (
            await session.execute(
                select(SensorAggregate.entity_assignment_id, SensorAggregate.bucket_start).where(
                    SensorAggregate.tier == tier,
                    SensorAggregate.bucket_start >= start,
                    SensorAggregate.bucket_start < last_complete,
                )
            )
        ).all()
    }

    inserted = 0
    for (aid, b), acc in buckets.items():
        if (aid, b) in existing:
            continue
        session.add(
            SensorAggregate(
                storage_unit_id=acc["unit"],
                entity_assignment_id=aid,
                role=acc["role"],
                tier=tier,
                bucket_start=b,
                sample_count=acc["count"],
                valid_count=acc["valid"],
                min_c=acc["min"],
                max_c=acc["max"],
                avg_c=(acc["sum"] / acc["valid"]) if acc["valid"] else None,
            )
        )
        inserted += 1
    return inserted


# --------------------------------------------------------------------------- #
# Retention cleanup (batched, aggregate-guarded)
# --------------------------------------------------------------------------- #


async def cleanup_raw(
    session: AsyncSession, retention_days: int, now: datetime, batch: int = 5000
) -> int:
    """Delete raw samples older than retention — only where 15-minute aggregates
    already cover that period (so nothing is lost). Bounded batches."""
    cutoff = now - timedelta(days=retention_days)

    # Guard: every raw row we are about to delete (older than cutoff) must already
    # be covered by a 15-minute aggregate. Aggregation is contiguous from the
    # oldest sample, so it is sufficient that the newest 15-min aggregate bucket
    # reaches the bucket of the newest raw row being deleted.
    max_old = _as_utc(
        await session.scalar(
            select(func.max(SensorSample.event_timestamp)).where(
                SensorSample.event_timestamp < cutoff
            )
        )
    )
    if max_old is None:
        return 0
    need_bucket = floor_bucket(max_old, BUCKET_SECONDS["15min"])
    newest15 = _as_utc(
        await session.scalar(
            select(func.max(SensorAggregate.bucket_start)).where(SensorAggregate.tier == "15min")
        )
    )
    if newest15 is None or newest15 < need_bucket:
        log.info("maintenance: skipping raw cleanup — aggregates do not yet cover the cutoff")
        return 0

    deleted = 0
    while True:
        ids = (
            await session.scalars(
                select(SensorSample.id)
                .where(SensorSample.event_timestamp < cutoff)
                .limit(batch)
            )
        ).all()
        if not ids:
            break
        await session.execute(delete(SensorSample).where(SensorSample.id.in_(ids)))
        await session.commit()
        deleted += len(ids)
        if len(ids) < batch:
            break
    return deleted


async def cleanup_aggregates(
    session: AsyncSession, tier: str, retention_days: int, now: datetime, batch: int = 5000
) -> int:
    cutoff = now - timedelta(days=retention_days)
    deleted = 0
    while True:
        ids = (
            await session.scalars(
                select(SensorAggregate.id)
                .where(SensorAggregate.tier == tier, SensorAggregate.bucket_start < cutoff)
                .limit(batch)
            )
        ).all()
        if not ids:
            break
        await session.execute(delete(SensorAggregate).where(SensorAggregate.id.in_(ids)))
        await session.commit()
        deleted += len(ids)
        if len(ids) < batch:
            break
    return deleted


# --------------------------------------------------------------------------- #
# Storage monitoring
# --------------------------------------------------------------------------- #


@dataclass
class StorageUsage:
    database_bytes: int
    wal_bytes: int
    reports_bytes: int
    uploads_bytes: int
    logs_bytes: int
    app_total_bytes: int
    free_bytes: int
    free_percent: float
    budget_bytes: int
    budget_used_percent: float
    level: str  # ok | warning | critical | emergency


def _size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _dir_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def storage_usage(
    data_dir: Path, budget: int, warn_pct: int, crit_pct: int, emerg_pct: int
) -> StorageUsage:
    db = data_dir / "storage-controller.db"
    database_bytes = _size(db)
    wal_bytes = _size(data_dir / "storage-controller.db-wal") + _size(
        data_dir / "storage-controller.db-shm"
    )
    reports_bytes = _dir_size(data_dir / "reports")
    uploads_bytes = _dir_size(data_dir / "uploads")
    logs_bytes = _dir_size(data_dir / "logs")
    app_total = database_bytes + wal_bytes + reports_bytes + uploads_bytes + logs_bytes

    try:
        usage = shutil.disk_usage(str(data_dir))
        free_bytes = usage.free
        free_percent = (usage.free / usage.total * 100) if usage.total else 0.0
    except OSError:
        free_bytes = 0
        free_percent = 0.0

    used_pct = (app_total / budget * 100) if budget else 0.0
    if used_pct >= emerg_pct:
        level = "emergency"
    elif used_pct >= crit_pct:
        level = "critical"
    elif used_pct >= warn_pct:
        level = "warning"
    else:
        level = "ok"

    return StorageUsage(
        database_bytes=database_bytes,
        wal_bytes=wal_bytes,
        reports_bytes=reports_bytes,
        uploads_bytes=uploads_bytes,
        logs_bytes=logs_bytes,
        app_total_bytes=app_total,
        free_bytes=free_bytes,
        free_percent=round(free_percent, 1),
        budget_bytes=budget,
        budget_used_percent=round(used_pct, 1),
        level=level,
    )


async def wal_checkpoint(session: AsyncSession) -> bool:
    try:
        await session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        return True
    except Exception:  # noqa: BLE001
        return False


async def integrity_ok(session: AsyncSession) -> bool:
    try:
        result = await session.scalar(text("PRAGMA quick_check"))
        return result == "ok"
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


class MaintenanceRunner:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.last_usage: StorageUsage | None = None
        # Set when storage is at emergency level (collector suspends heartbeats).
        self.emergency = False

    async def run_once(self, now: datetime | None = None) -> MaintenanceRun:
        now = now or datetime.now(UTC)
        run = MaintenanceRun(started_at=now)
        async with self._session_factory() as session:
            maint = await get_maintenance_settings(session)

            run.aggregated_15min = await aggregate(session, "15min", now)
            run.aggregated_hourly = await aggregate(session, "hourly", now)
            await session.commit()

            run.raw_deleted = await cleanup_raw(session, maint.retention_raw_days, now)
            run.aggregates_deleted = await cleanup_aggregates(
                session, "15min", maint.retention_agg15_days, now
            )
            run.aggregates_deleted += await cleanup_aggregates(
                session, "hourly", maint.retention_agg_hourly_days, now
            )

            run.wal_checkpointed = await wal_checkpoint(session)
            run.integrity_ok = await integrity_ok(session)

            usage = storage_usage(
                get_settings().data_dir,
                maint.storage_budget_bytes,
                maint.warning_pct,
                maint.critical_pct,
                maint.emergency_pct,
            )
            self.last_usage = usage
            self.emergency = usage.level == "emergency"
            run.app_total_bytes = usage.app_total_bytes
            run.finished_at = datetime.now(UTC)
            run.detail = f"level={usage.level}"

            session.add(run)
            await session.commit()
            await session.refresh(run)
        log.info(
            "maintenance: agg15=%d aggH=%d rawDel=%d aggDel=%d level=%s",
            run.aggregated_15min,
            run.aggregated_hourly,
            run.raw_deleted,
            run.aggregates_deleted,
            run.detail,
        )
        return run

    async def refresh_storage(self) -> StorageUsage:
        """Compute storage usage only (cheap; for startup + the status endpoint)."""
        async with self._session_factory() as session:
            maint = await get_maintenance_settings(session)
        usage = storage_usage(
            get_settings().data_dir,
            maint.storage_budget_bytes,
            maint.warning_pct,
            maint.critical_pct,
            maint.emergency_pct,
        )
        self.last_usage = usage
        self.emergency = usage.level == "emergency"
        return usage

    def current_usage(self) -> StorageUsage | None:
        return self.last_usage
