"""Home Assistant history import for a storage unit's primary sensor (Phase 5.1).

Imports recorder raw history (fine resolution) where available and falls back to
long-term hourly statistics (min/max/mean) for older periods. Imported records are
marked with their source/resolution. Imports are deduplicated by the existing
UNIQUE constraints and **never** trigger live incident workflows — historical
threshold crossings are reportable as imported deviations only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ha import websocket as ws_proto
from .ha.client import HomeAssistantRestClient
from .models import (
    EntityAssignment,
    HistoryImport,
    HistoryImportStatus,
    HistoryRange,
    Quality,
    SampleSource,
    SensorAggregate,
    SensorSample,
)
from .normalization import normalize_numeric

log = logging.getLogger("history_import")

# Treat "all" as a bounded long lookback so an import is never unbounded.
_ALL_LOOKBACK_DAYS = 730
RECOMMENDED_RANGE = HistoryRange.last_30_days.value


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def range_window(range_key: str, now: datetime, tz_name: str) -> tuple[datetime, datetime]:
    end = now
    if range_key == HistoryRange.current_month.value:
        try:
            zone = ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001
            zone = ZoneInfo("UTC")
        local = now.astimezone(zone)
        start = datetime(local.year, local.month, 1, tzinfo=zone).astimezone(UTC)
    elif range_key == HistoryRange.last_90_days.value:
        start = end - timedelta(days=90)
    elif range_key == HistoryRange.all.value:
        start = end - timedelta(days=_ALL_LOOKBACK_DAYS)
    else:  # last_30_days (default)
        start = end - timedelta(days=30)
    return start, end


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):  # statistics: ms epoch
            return datetime.fromtimestamp(value / 1000.0, UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, OSError):
        return None


async def check_availability(
    rest: HomeAssistantRestClient,
    *,
    entity_id: str,
    ws_url: str,
    token: str | None,
    now: datetime | None = None,
) -> dict:
    """Probe what history is available. States: raw_available | stats_only |
    no_history (plus a recommended range)."""
    now = now or datetime.now(UTC)
    out = {
        "state": "no_history",
        "raw_available": False,
        "oldest_raw": None,
        "has_statistics": False,
        "recommended_range": RECOMMENDED_RANGE,
    }
    try:
        recent = await rest.get_history(entity_id, _iso(now - timedelta(days=2)), _iso(now))
    except Exception as exc:  # noqa: BLE001
        log.info("history: availability probe failed for %s: %s", entity_id, type(exc).__name__)
        recent = []
    if recent:
        out["raw_available"] = True
        out["state"] = "raw_available"

    if token:
        try:
            stats = await ws_proto.fetch_statistics(
                ws_url, token, entity_id,
                _iso(now - timedelta(days=400)), _iso(now - timedelta(days=10)),
            )
            if stats:
                out["has_statistics"] = True
                if not recent:
                    out["state"] = "stats_only"
        except Exception as exc:  # noqa: BLE001
            log.info("history: statistics probe failed: %s", type(exc).__name__)
    return out


async def run_import(
    session: AsyncSession,
    *,
    job: HistoryImport,
    assignment: EntityAssignment,
    storage_unit_id: int,
    rest: HomeAssistantRestClient,
    ws_url: str,
    token: str | None,
    entity_unit: str | None,
    tz_name: str,
    now: datetime | None = None,
) -> HistoryImport:
    """Run the import in place. Commits status transitions via the caller's
    session. Never raises for HA/import errors — records a sanitized failure."""
    now = now or datetime.now(UTC)
    job.status = HistoryImportStatus.importing.value
    job.started_at = now
    await session.flush()

    start, end = range_window(job.requested_range, now, tz_name)
    try:
        raw_from, raw_to, raw_count = await _import_raw(
            session, assignment, storage_unit_id, rest, job.entity_id, entity_unit, start, end
        )
        job.raw_from, job.raw_to, job.raw_count = raw_from, raw_to, raw_count

        # Older than the earliest raw point → hourly long-term statistics.
        stats_end = raw_from or end
        stats_count = 0
        if token and stats_end > start:
            sf, st, stats_count = await _import_statistics(
                session, assignment, storage_unit_id, ws_url, token, job.entity_id, start, stats_end
            )
            job.stats_from, job.stats_to, job.stats_count = sf, st, stats_count

        if raw_count and stats_count:
            job.status = HistoryImportStatus.completed.value
        elif raw_count:
            job.status = HistoryImportStatus.completed.value
        elif stats_count:
            job.status = HistoryImportStatus.partial.value  # only hourly statistics
        else:
            job.status = HistoryImportStatus.no_history.value
    except Exception as exc:  # noqa: BLE001
        job.status = HistoryImportStatus.failed.value
        job.error_message = "History import failed."  # sanitized
        log.warning("history: import failed for %s: %s", job.entity_id, type(exc).__name__)

    job.finished_at = datetime.now(UTC)
    await session.flush()
    return job


async def _existing_ts(session: AsyncSession, aid: int, start: datetime, end: datetime) -> set:
    rows = await session.scalars(
        select(SensorSample.event_timestamp).where(
            SensorSample.entity_assignment_id == aid,
            SensorSample.event_timestamp >= start,
            SensorSample.event_timestamp < end,
        )
    )
    return {r.replace(tzinfo=UTC) if r.tzinfo is None else r for r in rows}


async def _import_raw(
    session, assignment, storage_unit_id, rest, entity_id, entity_unit, start, end
):
    points = await rest.get_history(entity_id, _iso(start), _iso(end))
    if not points:
        return None, None, 0
    existing = await _existing_ts(session, assignment.id, start, end)
    lo = hi = None
    added = 0
    for pt in points:
        ts = _parse_ts(pt.get("last_changed") or pt.get("last_updated"))
        if ts is None or ts in existing:
            continue
        res = normalize_numeric(pt.get("state"), entity_unit)
        session.add(
            SensorSample(
                storage_unit_id=storage_unit_id,
                entity_assignment_id=assignment.id,
                entity_id=entity_id,
                role=assignment.role,
                event_timestamp=ts,
                received_timestamp=datetime.now(UTC),
                raw_value=res.raw_value,
                numeric_value=res.numeric_value,
                normalized_value_c=res.normalized_value_c,
                original_unit=res.original_unit,
                quality=res.quality.value,
                source=SampleSource.home_assistant_history_import.value,
                source_context_id=None,
            )
        )
        existing.add(ts)
        added += 1
        lo = ts if lo is None or ts < lo else lo
        hi = ts if hi is None or ts > hi else hi
    await session.flush()
    return lo, hi, added


async def _existing_buckets(session: AsyncSession, aid: int, start: datetime, end: datetime) -> set:
    rows = await session.scalars(
        select(SensorAggregate.bucket_start).where(
            SensorAggregate.entity_assignment_id == aid,
            SensorAggregate.tier == "hourly",
            SensorAggregate.bucket_start >= start,
            SensorAggregate.bucket_start < end,
        )
    )
    return {r.replace(tzinfo=UTC) if r.tzinfo is None else r for r in rows}


async def _import_statistics(
    session, assignment, storage_unit_id, ws_url, token, entity_id, start, end
):
    rows = await ws_proto.fetch_statistics(ws_url, token, entity_id, _iso(start), _iso(end))
    if not rows:
        return None, None, 0
    existing = await _existing_buckets(session, assignment.id, start, end)
    lo = hi = None
    added = 0
    for r in rows:
        bucket = _parse_ts(r.get("start"))
        if bucket is None or bucket in existing:
            continue
        mn, mx, mean = r.get("min"), r.get("max"), r.get("mean")
        session.add(
            SensorAggregate(
                storage_unit_id=storage_unit_id,
                entity_assignment_id=assignment.id,
                role=assignment.role,
                tier="hourly",
                bucket_start=bucket,
                sample_count=0,
                valid_count=0,
                min_c=mn,
                max_c=mx,
                avg_c=mean,
                source="ha_statistics",
            )
        )
        existing.add(bucket)
        added += 1
        lo = bucket if lo is None or bucket < lo else lo
        hi = bucket if hi is None or bucket > hi else hi
    await session.flush()
    return lo, hi, added


def imported_quality(res_quality: str) -> str:
    # Imported raw samples keep their normalized quality; this hook lets callers
    # distinguish imported data if needed in the future.
    return res_quality or Quality.valid.value
