"""Report metrics computed from the App's own recorded data (Phase 5).

All period boundaries are computed in the report timezone, then stored/queried in
UTC. Durations (time above/below limit, unavailable/invalid, gaps) are attributed
by a single ordered pass over the room-temperature samples; large gaps are counted
as missing data, never interpolated across.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    DefrostClassification,
    DefrostCycle,
    DefrostStatus,
    EntityRole,
    Incident,
    Quality,
    SensorSample,
    StorageUnit,
)
from .model import DataQuality, DefrostSummary, IncidentSummary


def month_range_utc(year: int, month: int, tz: str) -> tuple[datetime, datetime]:
    """Return [start, end) in UTC for the given month in the report timezone."""
    try:
        zone = ZoneInfo(tz)
    except Exception:  # noqa: BLE001 — unknown zone falls back to UTC
        zone = ZoneInfo("UTC")
    start_local = datetime(year, month, 1, tzinfo=zone)
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    end_local = datetime(ny, nm, 1, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


@dataclass
class SampleMetrics:
    min_c: float | None = None
    max_c: float | None = None
    avg_c: float | None = None
    time_above_seconds: int = 0
    time_below_seconds: int = 0
    data_quality: DataQuality = field(default_factory=DataQuality)
    chart_points: list[list[float | None]] = field(default_factory=list)
    gap_ranges: list[tuple[float, float]] = field(default_factory=list)  # (start, end) epoch


async def sample_metrics(
    session: AsyncSession,
    *,
    storage_unit_id: int,
    start_utc: datetime,
    end_utc: datetime,
    lower: float | None,
    upper: float | None,
    heartbeat_seconds: int,
    chart_buckets: int = 160,
) -> SampleMetrics:
    rows = (
        await session.execute(
            select(
                SensorSample.event_timestamp,
                SensorSample.normalized_value_c,
                SensorSample.quality,
            )
            .where(
                SensorSample.storage_unit_id == storage_unit_id,
                SensorSample.role == EntityRole.room_temperature.value,
                SensorSample.event_timestamp >= start_utc,
                SensorSample.event_timestamp < end_utc,
            )
            .order_by(SensorSample.event_timestamp.asc())
        )
    ).all()

    m = SampleMetrics()
    if not rows:
        m.data_quality = DataQuality(missing_entity=True, incomplete=True, coverage_percent=0.0)
        return m

    samples = [(_utc(ts), v, q) for ts, v, q in rows]
    valid_values = [v for _, v, q in samples if q == Quality.valid.value and v is not None]
    if valid_values:
        m.min_c = round(min(valid_values), 2)
        m.max_c = round(max(valid_values), 2)
        m.avg_c = round(statistics.fmean(valid_values), 2)

    attribute_cap = max(2 * heartbeat_seconds, 600)
    gap_threshold = max(3 * heartbeat_seconds, 1800)

    unavailable = invalid = gap = above = below = 0.0
    gaps_count = 0
    gap_ranges: list[tuple[float, float]] = []
    # Attribute the interval after each sample to that sample's state.
    for (ts, v, q), (nts, _nv, _nq) in zip(samples, samples[1:], strict=False):
        if ts is None or nts is None:
            continue
        dt = (nts - ts).total_seconds()
        if dt <= 0:
            continue
        if dt > gap_threshold:
            gap += dt
            gaps_count += 1
            gap_ranges.append((ts.timestamp(), nts.timestamp()))
            continue
        dt = min(dt, attribute_cap)
        if q == Quality.valid.value and v is not None:
            if upper is not None and v > upper:
                above += dt
            elif lower is not None and v < lower:
                below += dt
        elif q in (Quality.unavailable.value, Quality.unknown.value):
            unavailable += dt
        elif q in (Quality.invalid.value, Quality.implausible.value):
            invalid += dt

    period_seconds = (end_utc - start_utc).total_seconds()
    expected = int(period_seconds / heartbeat_seconds) if heartbeat_seconds > 0 else None
    valid_count = len(valid_values)
    coverage = None
    if expected and expected > 0:
        coverage = round(min(100.0, 100.0 * valid_count / expected), 1)

    m.time_above_seconds = int(above)
    m.time_below_seconds = int(below)
    m.data_quality = DataQuality(
        valid_count=valid_count,
        total_count=len(samples),
        expected_count=expected,
        coverage_percent=coverage,
        unavailable_seconds=int(unavailable),
        invalid_seconds=int(invalid),
        gap_seconds=int(gap),
        gaps_count=gaps_count,
        missing_entity=False,
        incomplete=bool(coverage is not None and coverage < 90.0),
    )
    m.chart_points = _downsample(samples, start_utc, end_utc, chart_buckets)
    m.gap_ranges = gap_ranges
    return m


def _downsample(samples, start_utc, end_utc, buckets: int) -> list[list[float | None]]:
    """Bucket valid samples into ~``buckets`` points; empty buckets become gaps
    (None) so missing periods render as breaks, never interpolated."""
    span = (end_utc - start_utc).total_seconds()
    if span <= 0 or buckets <= 0:
        return []
    width = span / buckets
    acc: dict[int, list[float]] = {}
    for ts, v, q in samples:
        if ts is None or v is None or q != Quality.valid.value:
            continue
        idx = int((ts - start_utc).total_seconds() / width)
        idx = min(idx, buckets - 1)
        acc.setdefault(idx, []).append(v)
    points: list[list[float | None]] = []
    for i in range(buckets):
        epoch = start_utc.timestamp() + (i + 0.5) * width
        vals = acc.get(i)
        points.append([epoch, round(statistics.fmean(vals), 2) if vals else None])
    return points


async def incident_summaries(
    session: AsyncSession, *, storage_unit_id: int, start_utc: datetime, end_utc: datetime
) -> list[IncidentSummary]:
    rows = (
        await session.scalars(
            select(Incident)
            .where(
                Incident.storage_unit_id == storage_unit_id,
                Incident.opened_at < end_utc,
            )
            .order_by(Incident.opened_at.asc())
        )
    ).all()
    out: list[IncidentSummary] = []
    for inc in rows:
        opened = _utc(inc.opened_at)
        closed = _utc(inc.closed_at)
        # Overlaps the period?
        if (closed or end_utc) < start_utc:
            continue
        eff_end = closed or end_utc
        dur = max(0, int((eff_end - opened).total_seconds())) if opened else 0
        out.append(
            IncidentSummary(
                id=inc.id,
                type=inc.type,
                state=inc.state,
                opened_at=opened.isoformat() if opened else "",
                closed_at=closed.isoformat() if closed else None,
                duration_seconds=dur,
                extreme_value_c=inc.extreme_value_c,
                limit_value_c=inc.limit_value_c,
                defrost_overlap=inc.defrost_overlap,
                acknowledged=inc.acknowledged_at is not None,
                documented=bool(inc.corrective_action or inc.cause),
                cause=inc.cause,
                corrective_action=inc.corrective_action,
                note=inc.note,
            )
        )
    return out


async def defrost_summary(
    session: AsyncSession,
    *,
    storage_unit_id: int,
    start_utc: datetime,
    end_utc: datetime,
    has_approved_model: bool,
) -> DefrostSummary | None:
    rows = (
        await session.scalars(
            select(DefrostCycle).where(
                DefrostCycle.storage_unit_id == storage_unit_id,
                DefrostCycle.started_at >= start_utc,
                DefrostCycle.started_at < end_utc,
            )
        )
    ).all()
    if not rows:
        return None
    durations: list[float] = []
    recoveries: list[float] = []
    completed = abnormal = reconstructed = 0
    for c in rows:
        s, e = _utc(c.started_at), _utc(c.ended_at)
        if s and e and e > s:
            durations.append((e - s).total_seconds())
        rs, rd = _utc(c.recovery_started_at), _utc(c.recovered_at)
        if rs and rd and rd > rs:
            recoveries.append((rd - rs).total_seconds())
        if c.status == DefrostStatus.completed.value:
            completed += 1
        if c.status == DefrostStatus.abnormal.value or c.classification in (
            DefrostClassification.abnormal_defrost.value,
            DefrostClassification.recovery_timeout.value,
        ):
            abnormal += 1
        if c.reconstructed:
            reconstructed += 1

    def med(xs: list[float]) -> int | None:
        return int(statistics.median(xs)) if xs else None

    return DefrostSummary(
        cycle_count=len(rows),
        completed_count=completed,
        abnormal_count=abnormal,
        reconstructed_count=reconstructed,
        typical_duration_seconds=med(durations),
        max_duration_seconds=int(max(durations)) if durations else None,
        typical_recovery_seconds=med(recoveries),
        max_recovery_seconds=int(max(recoveries)) if recoveries else None,
        has_approved_model=has_approved_model,
    )


async def defrost_ranges(
    session: AsyncSession, *, storage_unit_id: int, start_utc: datetime, end_utc: datetime
) -> list[tuple[float, float]]:
    rows = (
        await session.scalars(
            select(DefrostCycle).where(
                DefrostCycle.storage_unit_id == storage_unit_id,
                DefrostCycle.started_at >= start_utc,
                DefrostCycle.started_at < end_utc,
            )
        )
    ).all()
    out: list[tuple[float, float]] = []
    for c in rows:
        s = _utc(c.started_at)
        e = _utc(c.ended_at) or _utc(c.recovered_at)
        if s and e and e > s:
            out.append((s.timestamp(), e.timestamp()))
    return out


def chart_group_for(unit: StorageUnit) -> str:
    """Data/config-driven grouping: explicit chart_group, else scale-based."""
    if unit.chart_group:
        return unit.chart_group
    upper = unit.upper_limit_c
    if upper is not None and upper <= -5:
        return "frozen"
    return "chilled"
