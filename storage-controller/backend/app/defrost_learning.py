"""Defrost learning — robust statistics over observed cycles (Phase 4.6).

Pure, deterministic functions (no I/O) that turn a set of *complete, valid*
defrost cycles into a suggested operational profile. This module learns only
**operational characteristics** (durations, peak temperatures, recovery time,
frequency). It never touches, derives or returns storage-temperature safety
limits, and a single outlier is never used as a learned bound (robust median /
percentile / MAD statistics with a conservative safety margin).

A suggestion produced here is advisory until a human explicitly approves it; the
incident engine must not suppress or reclassify anything from an unapproved
model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

# Cycle-count thresholds for confidence. Below the preliminary threshold there is
# not enough evidence to suggest a model at all.
MIN_PRELIMINARY_CYCLES = 10
MIN_HIGH_CONFIDENCE_CYCLES = 20

# A "recovery" shorter than this is a same-tick completion — the room never
# actually left the safe band, so it tells us nothing about how long recovery
# takes. Counting these near-zero durations would collapse the learned recovery
# envelope toward 0 and then strangle the recovery timeout (real recoveries
# would instantly time out, be marked abnormal, and so never feed learning — a
# self-reinforcing loop). Such cycles are excluded from recovery-time learning.
MIN_RECOVERY_OBSERVATION_SECONDS = 60

# Conservative default safety margin added on top of learned peaks (°C).
DEFAULT_SAFETY_MARGIN_C = 2.0
# Fractional head-room added on top of learned durations (p95 * (1 + fraction)).
DURATION_MARGIN_FRACTION = 0.25

# Drift: how far the recent median may move from the approved typical before we
# warn and suggest retraining (in robust MAD multiples, with absolute floors).
DRIFT_MAD_MULTIPLE = 3.0
DRIFT_MIN_ROOM_C = 1.5
DRIFT_MIN_DURATION_S = 600


@dataclass(frozen=True)
class ObservedCycle:
    """A single complete, valid defrost cycle reduced to learnable scalars."""

    started_at: datetime
    defrost_seconds: float
    recovery_seconds: float | None
    room_peak_c: float | None
    evaporator_peak_c: float | None


@dataclass
class LearnedSuggestion:
    valid_cycle_count: int
    confidence: str
    confidence_score: float
    window_start: datetime | None
    window_end: datetime | None
    typical_defrost_seconds: int | None = None
    max_defrost_seconds: int | None = None
    typical_recovery_seconds: int | None = None
    max_recovery_seconds: int | None = None
    typical_room_peak_c: float | None = None
    max_room_peak_c: float | None = None
    typical_evaporator_peak_c: float | None = None
    max_evaporator_peak_c: float | None = None
    typical_interval_seconds: int | None = None
    room_peak_variation_c: float | None = None
    duration_variation_seconds: int | None = None
    safety_margin_c: float = DEFAULT_SAFETY_MARGIN_C
    outlier_count: int = 0
    outliers: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Robust statistics
# --------------------------------------------------------------------------- #


def median(values: list[float]) -> float | None:
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    if n % 2:
        return xs[mid]
    return (xs[mid - 1] + xs[mid]) / 2.0


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile, ``p`` in [0, 100]."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    rank = (p / 100.0) * (len(xs) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return xs[lo]
    frac = rank - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def mad(values: list[float]) -> float | None:
    """Median absolute deviation (robust spread)."""
    xs = [v for v in values if v is not None]
    med = median(xs)
    if med is None:
        return None
    return median([abs(v - med) for v in xs])


def confidence_for(n: int) -> tuple[str, float]:
    """Return a confidence label and a 0..1 score for ``n`` valid cycles."""
    if n < MIN_PRELIMINARY_CYCLES:
        return "insufficient", round(min(1.0, n / MIN_PRELIMINARY_CYCLES) * 0.4, 3)
    if n < MIN_HIGH_CONFIDENCE_CYCLES:
        # 0.5 .. 0.8 across the preliminary band.
        span = MIN_HIGH_CONFIDENCE_CYCLES - MIN_PRELIMINARY_CYCLES
        return "preliminary", round(0.5 + 0.3 * (n - MIN_PRELIMINARY_CYCLES) / span, 3)
    return "high", round(min(1.0, 0.8 + 0.2 * (n - MIN_HIGH_CONFIDENCE_CYCLES) / 20), 3)


# --------------------------------------------------------------------------- #
# Suggestion building
# --------------------------------------------------------------------------- #


def _intervals(cycles: list[ObservedCycle]) -> list[float]:
    starts = sorted(c.started_at for c in cycles)
    return [
        (b - a).total_seconds()
        for a, b in zip(starts, starts[1:], strict=False)
        if (b - a).total_seconds() > 0
    ]


def _upper_fence(values: list[float]) -> float | None:
    """Tukey upper fence ``Q3 + 1.5*IQR``; for a degenerate spread, ``Q3``."""
    xs = [v for v in values if v is not None]
    if len(xs) < 4:
        return None
    q1 = percentile(xs, 25)
    q3 = percentile(xs, 75)
    if q1 is None or q3 is None:
        return None
    iqr = q3 - q1
    return q3 + 1.5 * iqr if iqr > 0 else q3


def _high_outliers(label: str, values: list[float], unit: str) -> list[str]:
    """Values above the upper Tukey fence (reported, never used as a bound)."""
    xs = [v for v in values if v is not None]
    fence = _upper_fence(xs)
    if fence is None:
        return []
    return [f"{label}={v:.1f}{unit}" for v in xs if v > fence]


def _inliers(values: list[float]) -> list[float]:
    """Drop high outliers so a single extreme never becomes the learned bound."""
    xs = [v for v in values if v is not None]
    fence = _upper_fence(xs)
    if fence is None:
        return xs
    return [v for v in xs if v <= fence]


def build_suggestion(
    cycles: list[ObservedCycle],
    *,
    min_cycles: int = MIN_PRELIMINARY_CYCLES,
    safety_margin_c: float = DEFAULT_SAFETY_MARGIN_C,
) -> LearnedSuggestion:
    """Build a robust suggestion from complete valid cycles.

    Below ``min_cycles`` (or ``MIN_PRELIMINARY_CYCLES``, whichever is larger) the
    returned suggestion carries the cycle count and confidence only — no learned
    bounds — so the engine cannot act on premature data.
    """
    n = len(cycles)
    label, score = confidence_for(n)
    window_start = min((c.started_at for c in cycles), default=None)
    window_end = max((c.started_at for c in cycles), default=None)

    threshold = max(min_cycles, MIN_PRELIMINARY_CYCLES)
    if n < threshold:
        return LearnedSuggestion(
            valid_cycle_count=n,
            confidence=label,
            confidence_score=score,
            window_start=window_start,
            window_end=window_end,
        )

    durations = [c.defrost_seconds for c in cycles]
    recoveries = [c.recovery_seconds for c in cycles if c.recovery_seconds is not None]
    room_peaks = [c.room_peak_c for c in cycles if c.room_peak_c is not None]
    evap_peaks = [c.evaporator_peak_c for c in cycles if c.evaporator_peak_c is not None]
    intervals = _intervals(cycles)

    def p95_duration(vals: list[float]) -> int | None:
        # Robust max: exclude high outliers, then p95 with fractional head-room.
        p = percentile(_inliers(vals), 95)
        if p is None:
            return None
        return int(round(p * (1.0 + DURATION_MARGIN_FRACTION)))

    typ_dur = median(durations)
    typ_rec = median(recoveries)
    typ_room = median(room_peaks)
    max_room = percentile(_inliers(room_peaks), 95)
    typ_evap = median(evap_peaks)
    max_evap = percentile(_inliers(evap_peaks), 95)
    typ_int = median(intervals)
    room_mad = mad(room_peaks)
    dur_mad = mad(durations)

    outliers = (
        _high_outliers("dauer", durations, "s")
        + _high_outliers("raum", room_peaks, "°C")
        + _high_outliers("recovery", recoveries, "s")
    )

    return LearnedSuggestion(
        valid_cycle_count=n,
        confidence=label,
        confidence_score=score,
        window_start=window_start,
        window_end=window_end,
        typical_defrost_seconds=int(round(typ_dur)) if typ_dur is not None else None,
        max_defrost_seconds=p95_duration(durations),
        typical_recovery_seconds=int(round(typ_rec)) if typ_rec is not None else None,
        max_recovery_seconds=p95_duration(recoveries),
        typical_room_peak_c=round(typ_room, 2) if typ_room is not None else None,
        max_room_peak_c=round(max_room + safety_margin_c, 2) if max_room is not None else None,
        typical_evaporator_peak_c=round(typ_evap, 2) if typ_evap is not None else None,
        max_evaporator_peak_c=(
            round(max_evap + safety_margin_c, 2) if max_evap is not None else None
        ),
        typical_interval_seconds=int(round(typ_int)) if typ_int is not None else None,
        room_peak_variation_c=round(room_mad, 2) if room_mad is not None else None,
        duration_variation_seconds=int(round(dur_mad)) if dur_mad is not None else None,
        safety_margin_c=safety_margin_c,
        outlier_count=len(outliers),
        outliers=outliers,
    )


# --------------------------------------------------------------------------- #
# Drift detection (against an already-approved model)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DriftResult:
    drifted: bool
    detail: str | None = None


def detect_drift(
    *,
    approved_typical_room_c: float | None,
    approved_room_variation_c: float | None,
    approved_typical_defrost_s: int | None,
    approved_duration_variation_s: int | None,
    recent: LearnedSuggestion,
) -> DriftResult:
    """Compare a fresh suggestion against the approved typicals.

    Drift is advisory: it warns and suggests retraining. It must never cause the
    engine to silently change behaviour.
    """
    reasons: list[str] = []

    if (
        approved_typical_room_c is not None
        and recent.typical_room_peak_c is not None
    ):
        tol = max(DRIFT_MIN_ROOM_C, DRIFT_MAD_MULTIPLE * (approved_room_variation_c or 0.0))
        if abs(recent.typical_room_peak_c - approved_typical_room_c) > tol:
            reasons.append(
                f"Raumspitze {approved_typical_room_c:.1f}→{recent.typical_room_peak_c:.1f} °C"
            )

    if (
        approved_typical_defrost_s is not None
        and recent.typical_defrost_seconds is not None
    ):
        tol_s = max(
            DRIFT_MIN_DURATION_S,
            DRIFT_MAD_MULTIPLE * (approved_duration_variation_s or 0),
        )
        if abs(recent.typical_defrost_seconds - approved_typical_defrost_s) > tol_s:
            reasons.append(
                f"Dauer {approved_typical_defrost_s // 60}→"
                f"{recent.typical_defrost_seconds // 60} min"
            )

    if reasons:
        return DriftResult(True, "; ".join(reasons))
    return DriftResult(False)
