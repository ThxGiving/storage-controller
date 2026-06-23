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
from ..models import EntityAssignment, EntityRole, Quality, SensorSample, StorageUnit
from ..schemas import HistoryPoint, HistoryResponse

router = APIRouter(prefix="/api/storage-units", tags=["history"])

_RANGE_DELTAS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _as_utc(ts: datetime) -> datetime:
    """SQLite returns tz-naive datetimes; treat them as UTC."""
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


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
    points, downsampled, bucket_seconds = _build_points(rows, start, end, max_points)

    min_c = min((v for _, v in valid), default=None)
    max_c = max((v for _, v in valid), default=None)
    avg_c = (sum(v for _, v in valid) / len(valid)) if valid else None

    # Coverage: fraction of buckets that contain at least one valid value.
    covered = sum(1 for p in points if p.v is not None)
    coverage = (covered / len(points)) if points else None

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


def _build_points(
    rows: list[tuple[datetime, float | None, str]],
    start: datetime,
    end: datetime,
    max_points: int,
) -> tuple[list[HistoryPoint], bool, int | None]:
    """Return display points. Small series are returned raw (unavailable → gap);
    large series are downsampled into fixed time buckets (empty bucket → gap)."""
    if len(rows) <= max_points:
        return (
            [
                HistoryPoint(
                    t=_as_utc(ts),
                    v=val if (q == Quality.valid.value and val is not None) else None,
                    q=q,
                )
                for ts, val, q in rows
            ],
            False,
            None,
        )

    start = _as_utc(start)
    total_seconds = max((end - start).total_seconds(), 1.0)
    bucket_seconds = max(int(total_seconds / max_points), 1)
    buckets: dict[int, list[float]] = {}
    for ts, val, q in rows:
        if q != Quality.valid.value or val is None:
            continue
        idx = int((_as_utc(ts) - start).total_seconds() // bucket_seconds)
        buckets.setdefault(idx, []).append(val)

    points: list[HistoryPoint] = []
    n_buckets = int(total_seconds // bucket_seconds) + 1
    for idx in range(n_buckets):
        center = start + timedelta(seconds=bucket_seconds * idx + bucket_seconds / 2)
        values = buckets.get(idx)
        if values:
            points.append(
                HistoryPoint(
                    t=center,
                    v=sum(values) / len(values),
                    vmin=min(values),
                    vmax=max(values),
                    q=Quality.valid.value,
                )
            )
        else:
            points.append(HistoryPoint(t=center, v=None, q=None))
    return points, True, bucket_seconds
