"""Reconstruct sensor state validity as typed intervals from state-change history.

Home Assistant's Recorder is **state-change based**: a steady sensor emits no new
row until its (rounded) value changes. A large interval between rows therefore does
NOT mean the sensor was unavailable — the last valid state persists until:

* a new state is reported,
* an explicit ``unavailable`` / ``unknown`` state,
* (inferred) a connection outage, or
* a bounded **maximum trust interval** elapses with no evidence either way.

This module turns ordered samples into ``valid`` / ``gap`` intervals so that charts
and coverage treat steady state as continuous — never as missing — while still
breaking on genuine unavailability. It deliberately does NOT carry a value forever:
beyond ``max_trust`` seconds of silence the interval becomes a gap (uncertain).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Beyond this much silence with no availability evidence, a held value is no longer
# trusted and the interval is treated as a gap. Generous enough not to penalise a
# normal state-change sensor that holds a steady value, bounded so data never
# extends indefinitely. (Configurable hook for the future.)
MAX_TRUST_SECONDS = 7200  # 2 hours

UNAVAILABLE_STATES = {"unavailable", "unknown"}


@dataclass
class Interval:
    start: float  # epoch seconds
    end: float
    kind: str  # "valid" | "gap"
    value: float | None = None  # last known value (valid intervals only)


def _epoch(ts: datetime) -> float:
    return ts.timestamp()


def reconstruct(
    samples: list[tuple[datetime, float | None, str]],
    period_start: datetime,
    period_end: datetime,
    *,
    max_trust: float = MAX_TRUST_SECONDS,
    valid_quality: str = "valid",
) -> list[Interval]:
    """Return typed intervals covering ``[period_start, period_end)``.

    ``samples`` must be ordered by timestamp: ``(ts, normalized_value, quality)``.
    A valid sample's value holds until the next sample (capped at ``max_trust``);
    an ``unavailable``/``unknown`` sample, or silence beyond ``max_trust``, is a gap.
    """
    ps, pe = _epoch(period_start), _epoch(period_end)
    if pe <= ps:
        return []
    pts = [(_epoch(ts), v, q) for ts, v, q in samples if ps <= _epoch(ts) < pe]
    out: list[Interval] = []
    if not pts:
        return [Interval(ps, pe, "gap")]

    # Leading region before the first sample is genuinely missing.
    if pts[0][0] > ps:
        out.append(Interval(ps, pts[0][0], "gap"))

    n = len(pts)
    for i, (ts, v, q) in enumerate(pts):
        seg_end = pts[i + 1][0] if i + 1 < n else pe
        seg_end = min(seg_end, pe)
        if seg_end <= ts:
            continue
        if q == valid_quality and v is not None:
            trust_end = ts + max_trust
            if seg_end <= trust_end:
                out.append(Interval(ts, seg_end, "valid", v))
            else:
                out.append(Interval(ts, trust_end, "valid", v))
                out.append(Interval(trust_end, seg_end, "gap"))
        else:
            # Explicit unavailable/unknown (or non-valid) → genuine gap.
            out.append(Interval(ts, seg_end, "gap"))

    return _merge(out)


def _merge(intervals: list[Interval]) -> list[Interval]:
    """Merge adjacent intervals of the same kind (gaps; valid only if same value)."""
    merged: list[Interval] = []
    for iv in intervals:
        if merged:
            last = merged[-1]
            same = last.kind == iv.kind and (iv.kind == "gap" or last.value == iv.value)
            if same and abs(last.end - iv.start) < 1e-6:
                last.end = iv.end
                continue
        merged.append(iv)
    return merged


def gap_ranges(intervals: list[Interval]) -> list[tuple[float, float]]:
    """Genuine gap (missing/unavailable) ranges as (start, end) epochs."""
    return [(iv.start, iv.end) for iv in intervals if iv.kind == "gap"]


def valid_seconds(intervals: list[Interval]) -> float:
    return sum(iv.end - iv.start for iv in intervals if iv.kind == "valid")


def in_gap(gaps: list[tuple[float, float]], epoch: float) -> bool:
    return any(g0 <= epoch < g1 for g0, g1 in gaps)
