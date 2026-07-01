"""Storage-unit history API (Phase 3A).

Returns a time-series of normalized Celsius temperature samples for a role, with
visible gaps for unavailable/missing periods and time-bucket downsampling for
long ranges. Downsampling is for display only and does not alter stored data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..errors import ERROR_STORAGE_UNIT_NOT_FOUND, AppError
from ..models import (
    DefrostCycle,
    EntityAssignment,
    EntityRole,
    Quality,
    SensorSample,
    StorageUnit,
)
from ..schemas import DefrostCycleOut, HistoryPoint, HistoryResponse
from ..state_series import gap_ranges, in_gap, reconstruct, valid_seconds
from ..timeutil import ensure_utc

router = APIRouter(prefix="/api/storage-units", tags=["history"])

_RANGE_DELTAS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _resolve_range(
    range_key: str, frm: datetime | None, to: datetime | None
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    if range_key == "custom" and frm and to:
        return frm, to
    delta = _RANGE_DELTAS.get(range_key, _RANGE_DELTAS["24h"])
    return now - delta, now


@router.get("/{unit_id}/samples", response_model=HistoryResponse)
async def unit_samples(
    unit_id: int,
    role: EntityRole = Query(default=EntityRole.room_temperature),
    range: str = Query(default="24h"),
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    max_points: int = Query(default=800, ge=10, le=5000),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    unit = await db.get(StorageUnit, unit_id)
    if unit is None:
        raise AppError(ERROR_STORAGE_UNIT_NOT_FOUND, status_code=404)

    start, end = _resolve_range(range, from_ts, to_ts)

    assignment = await db.scalar(
        select(EntityAssignment).where(
            EntityAssignment.storage_unit_id == unit_id,
            EntityAssignment.role == role.value,
        )
    )

    rows = (
        await db.execute(
            select(
                SensorSample.event_timestamp,
                SensorSample.normalized_value_c,
                SensorSample.quality,
            )
            .where(
                SensorSample.storage_unit_id == unit_id,
                SensorSample.role == role.value,
                SensorSample.event_timestamp >= start,
                SensorSample.event_timestamp <= end,
            )
            .order_by(SensorSample.event_timestamp.asc())
        )
    ).all()

    valid = [
        (ts, val)
        for ts, val, q in rows
        if q == Quality.valid.value and val is not None
    ]
    samples = [(ensure_utc(ts), val, q) for ts, val, q in rows]
    intervals = reconstruct(samples, ensure_utc(start), ensure_utc(end))
    points, downsampled, bucket_seconds = _build_points(rows, start, end, max_points, intervals)

    min_c = min((v for _, v in valid), default=None)
    max_c = max((v for _, v in valid), default=None)
    avg_c = (sum(v for _, v in valid) / len(valid)) if valid else None

    # Coverage: share of the period in which a valid state was known. A steady
    # state-change sensor holds its last value between rows, so steady periods
    # count as covered — only explicit unavailable/unknown or silence beyond the
    # trust interval is missing.
    span = (ensure_utc(end) - ensure_utc(start)).total_seconds()
    coverage = (valid_seconds(intervals) / span) if span > 0 else None

    return HistoryResponse(
        storage_unit_id=unit_id,
        role=role,
        entity_id=assignment.entity_id if assignment else None,
        unit="°C",
        from_ts=start,
        to_ts=end,
        lower_limit_c=unit.lower_limit_c,
        upper_limit_c=unit.upper_limit_c,
        sample_count=len(rows),
        downsampled=downsampled,
        bucket_seconds=bucket_seconds,
        points=points,
        min_c=min_c,
        max_c=max_c,
        avg_c=avg_c,
        coverage_ratio=coverage,
    )


@router.get("/{unit_id}/defrost-cycles", response_model=list[DefrostCycleOut])
async def unit_defrost_cycles(
    unit_id: int,
    range: str = Query(default="24h"),
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> list[DefrostCycle]:
    """Defrost cycles overlapping the range (for chart bands + operational history)."""
    if await db.get(StorageUnit, unit_id) is None:
        raise AppError(ERROR_STORAGE_UNIT_NOT_FOUND, status_code=404)
    start, end = _resolve_range(range, from_ts, to_ts)
    rows = (
        await db.scalars(
            select(DefrostCycle)
            .where(
                DefrostCycle.storage_unit_id == unit_id,
                # overlaps [start, end]: started before end and (still open or ended after start)
                DefrostCycle.started_at <= end,
            )
            .order_by(DefrostCycle.started_at.asc())
        )
    ).all()
    return [c for c in rows if c.ended_at is None or ensure_utc(c.ended_at) >= start]


def _build_points(
    rows: list[tuple[datetime, float | None, str]],
    start: datetime,
    end: datetime,
    max_points: int,
    intervals,
) -> tuple[list[HistoryPoint], bool, int | None]:
    """Return display points using reconstructed state validity.

    A valid value persists between state-change rows, so the line stays continuous
    through steady periods; it breaks (``v=None``) only across genuine gaps
    (explicit unavailable/unknown or silence beyond the trust interval). Empty
    aggregation buckets inside a valid interval carry the last known value instead
    of being mis-rendered as missing.
    """
    gaps = gap_ranges(intervals)

    if len(rows) <= max_points:
        points: list[HistoryPoint] = []
        prev_epoch: float | None = None
        for ts, val, q in rows:
            if q != Quality.valid.value or val is None:
                continue
            e = ensure_utc(ts).timestamp()
            # Break the line only if a genuine gap lies between the two samples.
            if prev_epoch is not None and _straddles_gap(gaps, prev_epoch, e):
                points.append(HistoryPoint(t=ensure_utc(ts), v=None, q=None))
            points.append(HistoryPoint(t=ensure_utc(ts), v=val, q=Quality.valid.value))
            prev_epoch = e
        return points, False, None

    start = ensure_utc(start)
    total_seconds = max((end - start).total_seconds(), 1.0)
    bucket_seconds = max(int(total_seconds / max_points), 1)
    buckets: dict[int, list[float]] = {}
    for ts, val, q in rows:
        if q != Quality.valid.value or val is None:
            continue
        idx = int((ensure_utc(ts) - start).total_seconds() // bucket_seconds)
        buckets.setdefault(idx, []).append(val)

    points = []
    n_buckets = int(total_seconds // bucket_seconds) + 1
    last_val: float | None = None
    for idx in range(n_buckets):
        center = start + timedelta(seconds=bucket_seconds * idx + bucket_seconds / 2)
        values = buckets.get(idx)
        if values:
            mean = sum(values) / len(values)
            points.append(
                HistoryPoint(t=center, v=mean, vmin=min(values), vmax=max(values),
                             q=Quality.valid.value)
            )
            last_val = mean
        elif in_gap(gaps, center.timestamp()) or last_val is None:
            # Genuine gap (or nothing known yet) → break the line.
            points.append(HistoryPoint(t=center, v=None, q=None))
            last_val = None
        else:
            # Steady state: the last known value still holds (continuous, no break).
            points.append(
                HistoryPoint(t=center, v=last_val, vmin=last_val, vmax=last_val,
                             q=Quality.valid.value)
            )
    return points, True, bucket_seconds


def _straddles_gap(gaps: list[tuple[float, float]], a: float, b: float) -> bool:
    """True if a genuine gap interval lies between epochs ``a`` and ``b``."""
    return any(g0 < b and g1 > a for g0, g1 in gaps)
