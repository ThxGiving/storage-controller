"""Report metrics computed from the App's own recorded data (Phase 5).

All period boundaries are computed in the report timezone, then stored/queried in
UTC. Durations (time above/below limit, unavailable/invalid, gaps) are attributed
by a single ordered pass over the room-temperature samples; large gaps are counted
as missing data, never interpolated across.
"""

from __future__ import annotations

import math
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
from ..state_series import MAX_TRUST_SECONDS, gap_ranges, in_gap, reconstruct
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
    # Aggregated buckets: [epoch_center, avg, min, max] (all None for an empty bucket).
    chart_points: list[list[float | None]] = field(default_factory=list)
    gap_ranges: list[tuple[float, float]] = field(default_factory=list)  # (start, end) epoch
    # Measured threshold-violation intervals (from raw samples only; never gaps).
    violation_ranges: list[tuple[float, float]] = field(default_factory=list)


async def sample_metrics(
    session: AsyncSession,
    *,
    storage_unit_id: int,
    start_utc: datetime,
    end_utc: datetime,
    lower: float | None,
    upper: float | None,
    heartbeat_seconds: int,
    bucket_seconds: int = 3600,
    max_points: int = 800,
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

    # State-change aware attribution. A value holds (is "covered") until the next
    # sample, capped at the trust interval; silence beyond that, or an explicit
    # unavailable/unknown/invalid state, is attributed as such — never as a steady
    # gap. This stops a normal state-change sensor from looking mostly-missing.
    max_trust = float(MAX_TRUST_SECONDS)
    period_seconds = (end_utc - start_utc).total_seconds()
    above = below = unavailable = invalid = gap = valid_covered = 0.0
    gaps_count = 0
    first_ts = next((ts for ts, _v, _q in samples if ts is not None), None)
    if first_ts is not None and first_ts > start_utc:
        gap += (first_ts - start_utc).total_seconds()  # leading missing region
        gaps_count += 1
    n = len(samples)
    for i, (ts, v, q) in enumerate(samples):
        if ts is None:
            continue
        nts = samples[i + 1][0] if i + 1 < n else end_utc
        if nts is None or nts <= ts:
            continue
        dur = (nts - ts).total_seconds()
        held = min(dur, max_trust)
        overflow = dur - held  # silence beyond trust → uncertain gap
        if q == Quality.valid.value and v is not None:
            valid_covered += held
            if upper is not None and v > upper:
                above += held
            elif lower is not None and v < lower:
                below += held
        elif q in (Quality.unavailable.value, Quality.unknown.value):
            unavailable += held
        elif q in (Quality.invalid.value, Quality.implausible.value):
            invalid += held
        if overflow > 0:
            gap += overflow
            gaps_count += 1

    valid_count = len(valid_values)
    expected = int(period_seconds / heartbeat_seconds) if heartbeat_seconds > 0 else None
    coverage = None
    if period_seconds > 0:
        coverage = round(min(100.0, 100.0 * valid_covered / period_seconds), 1)

    m.time_above_seconds = int(above)
    m.time_below_seconds = int(below)
    m.data_quality = DataQuality(
        valid_count=valid_count,
        total_count=len(samples),
        expected_count=expected,
        coverage_percent=coverage,
        # True when there are valid measurements but coverage rounds below 0.1%,
        # so the report never shows "0.0 %" next to real min/avg/max values.
        coverage_below_min=bool(valid_count > 0 and coverage is not None and coverage < 0.05),
        unavailable_seconds=int(unavailable),
        invalid_seconds=int(invalid),
        gap_seconds=int(gap),
        gaps_count=gaps_count,
        missing_entity=False,
        incomplete=bool(coverage is not None and coverage < 90.0),
    )
    # Chart gaps come from reconstructed state validity (genuine missing/unavailable
    # only); steady state-change periods stay continuous, not shaded.
    intervals = reconstruct(samples, start_utc, end_utc, valid_quality=Quality.valid.value)
    chart_gaps = gap_ranges(intervals)
    m.chart_points = _aggregate_buckets(
        samples, start_utc, end_utc, bucket_seconds, max_points, chart_gaps
    )
    m.gap_ranges = _merge_ranges(chart_gaps)
    m.violation_ranges = _violation_ranges(samples, lower, upper, max_trust)
    return m


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping/adjacent (start, end) intervals into a minimal set."""
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for s, e in ordered[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def _aggregate_buckets(
    samples, start_utc, end_utc, bucket_seconds: int, max_points: int, chart_gaps
) -> list[list[float | None]]:
    """Deterministic time-bucket aggregation with state-change continuity.

    Each bucket → ``[epoch, avg, min, max]``. A bucket with no samples carries the
    last known value (the state persisted) and stays continuous — UNLESS its centre
    falls inside a genuine gap (``chart_gaps`` from reconstructed state validity),
    where it becomes a single ``None`` break so the line/envelope stop and never
    interpolate across missing data. The min/max preserve short excursions.
    """
    span = (end_utc - start_utc).total_seconds()
    if span <= 0:
        return []
    base = start_utc.timestamp()
    width = max(bucket_seconds, span / max_points) if max_points > 0 else bucket_seconds
    nbuckets = max(1, math.ceil(span / width))
    acc: dict[int, list[float]] = {}
    for ts, v, q in samples:
        if ts is None or v is None or q != Quality.valid.value:
            continue
        idx = min(int((ts.timestamp() - base) / width), nbuckets - 1)
        acc.setdefault(idx, []).append(v)

    points: list[list[float | None]] = []
    last_val: float | None = None
    broke = False
    for i in range(nbuckets):
        epoch = base + (i + 0.5) * width
        vals = acc.get(i)
        if vals:
            last_val = round(statistics.fmean(vals), 2)
            points.append([epoch, last_val, round(min(vals), 2), round(max(vals), 2)])
            broke = False
        elif in_gap(chart_gaps, epoch) or last_val is None:
            # Genuine gap (or nothing known yet) → one break marker per gap run.
            if not broke:
                points.append([epoch, None, None, None])
                broke = True
            last_val = None
        else:
            # Steady state: carry the last known value so the line stays continuous.
            points.append([epoch, last_val, last_val, last_val])
            broke = False
    return points


def _violation_ranges(
    samples, lower: float | None, upper: float | None, gap_threshold: float
) -> list[tuple[float, float]]:
    """Contiguous intervals where MEASURED valid samples exceeded a safety limit.

    Derived only from real samples — never extended across a gap or past the last
    measured point, so missing/unknown data is never shown as a violation.
    """
    if lower is None and upper is None:
        return []
    out: list[tuple[float, float]] = []
    run_start: float | None = None
    run_last: float | None = None
    prev_ts: float | None = None
    for ts, v, q in samples:
        if ts is None:
            continue
        cur = ts.timestamp()
        # A real gap ends any open run at the last measured point (no extension).
        if prev_ts is not None and (cur - prev_ts) > gap_threshold and run_start is not None:
            out.append((run_start, run_last))
            run_start = None
        violating = (
            q == Quality.valid.value
            and v is not None
            and ((upper is not None and v > upper) or (lower is not None and v < lower))
        )
        if violating:
            if run_start is None:
                run_start = cur
            run_last = cur
        elif run_start is not None:
            out.append((run_start, cur))  # closed at the recovering sample
            run_start = None
        prev_ts = cur
    if run_start is not None and run_last is not None:
        out.append((run_start, run_last))
    return out


_CONSOLIDATION_WINDOW = 1800.0  # 30 min — adjacent same-type incidents within this gap are merged


def _consolidate_incidents(incidents: list[IncidentSummary]) -> list[IncidentSummary]:
    """Merge same-type incidents separated by less than _CONSOLIDATION_WINDOW seconds.

    Prevents individual hysteresis crossings or brief recovery-and-re-violation events
    from inflating incident counts.  The report data model is never modified; only the
    presentation list is consolidated.
    """
    if len(incidents) <= 1:
        return list(incidents)

    _priority = {
        "closed_auto": 0, "closed_manual": 0,
        "recovering": 1, "pending_violation": 2, "active_violation": 3,
    }

    def _worst_state(a: str, b: str) -> str:
        return a if _priority.get(a, 0) >= _priority.get(b, 0) else b

    def _worse_extreme(a: float | None, b: float | None, t: str) -> float | None:
        if a is None:
            return b
        if b is None:
            return a
        return max(a, b) if "above" in t else min(a, b)

    merged: list[IncidentSummary] = [incidents[0]]
    for inc in incidents[1:]:
        prev = merged[-1]
        if inc.type != prev.type:
            merged.append(inc)
            continue
        try:
            if prev.closed_at:
                gap = (
                    datetime.fromisoformat(inc.opened_at)
                    - datetime.fromisoformat(prev.closed_at)
                ).total_seconds()
            else:
                gap = 0.0  # previous still open → absorb
        except (ValueError, TypeError):
            merged.append(inc)
            continue
        if gap < 0 or gap <= _CONSOLIDATION_WINDOW:
            merged[-1] = IncidentSummary(
                id=prev.id,
                type=prev.type,
                state=_worst_state(prev.state, inc.state),
                opened_at=prev.opened_at,
                closed_at=inc.closed_at,
                duration_seconds=prev.duration_seconds + inc.duration_seconds,
                extreme_value_c=_worse_extreme(
                    prev.extreme_value_c, inc.extreme_value_c, prev.type
                ),
                limit_value_c=prev.limit_value_c or inc.limit_value_c,
                defrost_overlap=prev.defrost_overlap or inc.defrost_overlap,
                acknowledged=prev.acknowledged and inc.acknowledged,
                documented=prev.documented or inc.documented,
                cause=prev.cause or inc.cause,
                corrective_action=prev.corrective_action or inc.corrective_action,
                note=prev.note or inc.note,
            )
        else:
            merged.append(inc)
    return merged


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
    return _consolidate_incidents(out)


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
