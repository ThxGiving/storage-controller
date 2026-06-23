"""Home Assistant history import for a storage unit's primary sensor (Phase 5.1).

Imports recorder raw history (fine resolution) where available and falls back to
long-term hourly statistics (min/max/mean) for older periods. Imported records are
marked with their source/resolution. Imports are deduplicated by the existing
UNIQUE constraints and **never** trigger live incident workflows — historical
threshold crossings are reportable as imported deviations only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
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


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


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
        "has_statistics": False,
        "recommended_range": RECOMMENDED_RANGE,
        "earliest": None,
        "latest": None,
    }
    try:
        recent = await rest.get_history(
            entity_id, _iso(now - timedelta(days=2)), _iso(now), timeout=20.0
        )
    except Exception as exc:  # noqa: BLE001
        log.info("history: availability probe failed for %s: %s", entity_id, type(exc).__name__)
        recent = []
    if recent:
        out["raw_available"] = True
        out["state"] = "raw_available"
        out["latest"] = now
        last = _parse_ts(recent[-1].get("last_changed") or recent[-1].get("last_updated"))
        if last:
            out["latest"] = last

    if token:
        try:
            stats = await ws_proto.fetch_statistics(
                ws_url, token, entity_id,
                _iso(now - timedelta(days=_ALL_LOOKBACK_DAYS)), _iso(now),
            )
            if stats:
                out["has_statistics"] = True
                if not recent:
                    out["state"] = "stats_only"
                starts = [t for r in stats if (t := _parse_ts(r.get("start")))]
                if starts:
                    out["earliest"] = min(starts)
                    out["latest"] = out["latest"] or max(starts)
        except Exception as exc:  # noqa: BLE001
            log.info("history: statistics probe failed: %s", type(exc).__name__)
    return out


# Recent raw history is fetched in bounded windows so each request stays small,
# a single slow window can be retried in isolation, and progress survives a crash.
_CHUNK_DAYS = 5
_RETRY_TRIES = 3
_RETRY_BASE_DELAY = 2.0


def _chunk_plan(start: datetime, end: datetime) -> list[dict]:
    """Split [start, end) into <= _CHUNK_DAYS windows, oldest first."""
    chunks: list[dict] = []
    cursor = start
    step = timedelta(days=_CHUNK_DAYS)
    while cursor < end:
        ce = min(cursor + step, end)
        chunks.append({"s": _iso(cursor), "e": _iso(ce), "st": "pending"})
        cursor = ce
    return chunks


async def _fetch_with_retry(rest, entity_id, s, e):
    """Fetch one window with bounded exponential backoff. Raises if all tries fail."""
    delay = _RETRY_BASE_DELAY
    last: Exception | None = None
    for attempt in range(_RETRY_TRIES):
        try:
            return await rest.get_history(entity_id, _iso(s), _iso(e))
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < _RETRY_TRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2
    raise last if last else RuntimeError("history fetch failed")


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
    resume: bool = False,
    is_cancelled: Callable[[], bool] | None = None,
) -> HistoryImport:
    """Run (or resume) the import in place, committing progress after every chunk.

    Recent raw history is fetched in bounded, individually-retried windows; a
    failed window is recorded but never aborts the rest. Already-completed
    windows are never re-fetched, so this is idempotent and resumable across a
    restart. Never raises for HA/import errors — records sanitized progress.
    """
    now = now or datetime.now(UTC)
    start, end = range_window(job.requested_range, now, tz_name)
    is_cancelled = is_cancelled or (lambda: False)

    # Build the chunk plan once; on resume, keep the persisted per-chunk status.
    if resume and job.chunks_json:
        try:
            chunks = json.loads(job.chunks_json)
        except (ValueError, TypeError):
            chunks = _chunk_plan(start, end)
    else:
        chunks = _chunk_plan(start, end)
    job.status = HistoryImportStatus.importing.value
    job.started_at = job.started_at or now
    job.error_message = None
    job.chunks_json = json.dumps(chunks)
    await session.commit()

    # SQLite returns naive datetimes; make them UTC-aware so resume comparisons work.
    raw_lo = _aware(job.raw_from)
    raw_hi = _aware(job.raw_to)
    raw_count = job.raw_count or 0
    cancelled = False
    for ch in chunks:
        if ch.get("st") == "done":
            continue  # never restart a completed window
        if is_cancelled():
            cancelled = True
            break
        cs, ce = _parse_ts(ch["s"]), _parse_ts(ch["e"])
        try:
            points = await _fetch_with_retry(rest, job.entity_id, cs, ce)
        except Exception as exc:  # noqa: BLE001 — isolate a failed window
            ch["st"] = "failed"
            log.info("history: window %s..%s failed: %s", ch["s"], ch["e"], type(exc).__name__)
        else:
            lo, hi, added = await _insert_points(
                session, assignment, storage_unit_id, job.entity_id, entity_unit, points, cs, ce
            )
            raw_count += added
            raw_lo = lo if raw_lo is None or (lo and lo < raw_lo) else raw_lo
            raw_hi = hi if raw_hi is None or (hi and hi > raw_hi) else raw_hi
            ch["st"] = "done"
        job.raw_from, job.raw_to, job.raw_count = raw_lo, raw_hi, raw_count
        job.chunks_json = json.dumps(chunks)
        await session.commit()  # persist progress after every window

    # Older than the earliest raw point → hourly long-term statistics (best-effort).
    stats_end = raw_lo or end
    if not cancelled and token and stats_end > start:
        try:
            sf, st, sc = await _import_statistics(
                session, assignment, storage_unit_id, ws_url, token, job.entity_id, start, stats_end
            )
            job.stats_from, job.stats_to, job.stats_count = sf, st, sc
        except Exception as exc:  # noqa: BLE001
            log.info("history: statistics import failed: %s", type(exc).__name__)

    failed_any = any(c.get("st") == "failed" for c in chunks)
    stats_count = job.stats_count or 0
    if cancelled:
        job.status = HistoryImportStatus.cancelled.value
    elif failed_any:
        # Some windows failed: partial if we got *anything*, else a clean failure.
        if raw_count or stats_count:
            job.status = HistoryImportStatus.partial.value
        else:
            job.status = HistoryImportStatus.failed.value
            job.error_message = "History import failed for all windows."
    elif raw_count:
        job.status = HistoryImportStatus.completed.value  # all windows done with data
    elif stats_count:
        job.status = HistoryImportStatus.partial.value  # only hourly statistics
    else:
        job.status = HistoryImportStatus.no_history.value

    job.finished_at = datetime.now(UTC)
    await session.commit()
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


async def _insert_points(
    session, assignment, storage_unit_id, entity_id, entity_unit, points, start, end
):
    """Insert deduplicated raw points for one window. Existing timestamps (any
    source — including newer native samples) are skipped, so the import is
    idempotent and never overwrites native data."""
    existing = await _existing_ts(session, assignment.id, start, end)
    lo = hi = None
    added = 0
    for pt in points:
        ts = _parse_ts(pt.get("last_changed") or pt.get("last_updated"))
        # Keep only points inside this window: HA returns an "initial state" point
        # at/just before `start`, which is the previous window's last point — so
        # this both scopes the window and de-duplicates chunk boundaries.
        if ts is None or ts < start or ts >= end or ts in existing:
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


def summarize_chunks(chunks_json: str | None) -> dict[str, list[dict[str, str]]]:
    """Merge contiguous chunks of the same status into ``imported`` and ``failed``
    date ranges so the UI can show exactly which window failed."""
    out: dict[str, list[dict[str, str]]] = {"imported": [], "failed": []}
    if not chunks_json:
        return out
    try:
        chunks = json.loads(chunks_json)
    except (ValueError, TypeError):
        return out
    key = {"done": "imported", "failed": "failed"}
    cur_status = None
    cur = None
    for ch in chunks:
        bucket = key.get(ch.get("st"))
        if bucket and bucket == cur_status:
            cur["end"] = ch["e"]
        else:
            if cur is not None and cur_status:
                out[cur_status].append(cur)
            cur_status = bucket
            cur = {"start": ch["s"], "end": ch["e"]} if bucket else None
    if cur is not None and cur_status:
        out[cur_status].append(cur)
    return out


def imported_quality(res_quality: str) -> str:
    # Imported raw samples keep their normalized quality; this hook lets callers
    # distinguish imported data if needed in the future.
    return res_quality or Quality.valid.value
