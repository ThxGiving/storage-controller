"""State-change semantics: a valid value persists between Recorder rows until a
new state, an explicit unavailable/unknown, or the bounded trust interval — so
steady sensors are not mis-classified as missing and charts don't draw dashed
bridges. Covers reconstruct(), the live-chart point builder, and aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.history import _build_points
from app.reporting.metrics import _aggregate_buckets
from app.state_series import (
    MAX_TRUST_SECONDS,
    gap_ranges,
    reconstruct,
    valid_seconds,
)

T0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
TRUST_MIN = MAX_TRUST_SECONDS / 60  # 120 min


def _s(minutes, v, q="valid"):
    return (T0 + timedelta(minutes=minutes), v, q)


def _end(minutes):
    return T0 + timedelta(minutes=minutes)


# --------------------------------------------------------------------------- #
# reconstruct(): state validity intervals
# --------------------------------------------------------------------------- #


def test_unchanged_value_no_new_rows_is_not_a_gap():
    # Two rows an hour apart (sensor held steady, emitted no rows between).
    samples = [_s(0, 5.0), _s(60, 5.0)]
    intervals = reconstruct(samples, T0, _end(90))
    assert gap_ranges(intervals) == []  # steady state is NOT missing
    assert valid_seconds(intervals) == 90 * 60  # whole period is covered


def test_value_change_after_minutes_stays_continuous():
    samples = [_s(0, 5.0), _s(40, 6.5), _s(80, 4.0)]
    intervals = reconstruct(samples, T0, _end(100))
    assert gap_ranges(intervals) == []


def test_identical_values_distinct_timestamps_no_gap():
    samples = [_s(0, 5.0), _s(20, 5.0), _s(40, 5.0)]
    assert gap_ranges(reconstruct(samples, T0, _end(60))) == []


def test_explicit_unavailable_is_a_gap():
    samples = [_s(0, 5.0), _s(30, None, "unavailable"), _s(60, 5.0)]
    gaps = gap_ranges(reconstruct(samples, T0, _end(90)))
    assert len(gaps) == 1
    g0, g1 = gaps[0]
    assert g0 == _s(30, 0)[0].timestamp()  # gap starts at the unavailable row
    assert g1 == _s(60, 0)[0].timestamp()  # ends when a valid value returns


def test_recovery_from_unavailable_resumes_valid():
    samples = [_s(0, 5.0), _s(30, None, "unknown"), _s(60, 4.0), _s(90, 4.5)]
    intervals = reconstruct(samples, T0, _end(120))
    # exactly one gap (the unavailable window); valid before and after
    assert len(gap_ranges(intervals)) == 1
    assert any(iv.kind == "valid" and iv.start >= _s(60, 0)[0].timestamp() for iv in intervals)


def test_silence_beyond_trust_becomes_a_gap():
    # Two valid rows 5h apart with no availability evidence between.
    samples = [_s(0, 5.0), _s(300, 5.0)]
    gaps = gap_ranges(reconstruct(samples, T0, _end(360)))
    assert len(gaps) == 1
    g0, g1 = gaps[0]
    assert g0 == _s(TRUST_MIN, 0)[0].timestamp()  # value trusted only up to max_trust
    assert g1 == _s(300, 0)[0].timestamp()


def test_leading_region_before_first_sample_is_a_gap():
    samples = [_s(60, 5.0), _s(90, 5.0)]
    gaps = gap_ranges(reconstruct(samples, T0, _end(120)))
    assert gaps and gaps[0] == (T0.timestamp(), _s(60, 0)[0].timestamp())


def test_imported_then_native_samples_are_continuous():
    # Source is irrelevant to validity: imported rows then native rows, all valid
    # and within trust spacing -> one continuous valid stretch, no gap.
    samples = [_s(0, 5.0), _s(50, 5.2), _s(95, 5.1), _s(140, 5.3)]
    assert gap_ranges(reconstruct(samples, T0, _end(160))) == []


# --------------------------------------------------------------------------- #
# Live chart point builder: no dashed bridges for steady state
# --------------------------------------------------------------------------- #


def test_build_points_steady_state_has_no_internal_break():
    rows = [_s(0, 5.0), _s(60, 5.0), _s(110, 5.0)]  # sparse but steady
    intervals = reconstruct(rows, T0, _end(140))
    points, downsampled, _bs = _build_points(rows, T0, _end(140), 800, intervals)
    assert not downsampled
    assert all(p.v is not None for p in points)  # continuous — no dashed bridge


def test_build_points_breaks_on_explicit_unavailable():
    rows = [_s(0, 5.0), _s(30, None, "unavailable"), _s(60, 5.0)]
    intervals = reconstruct(rows, T0, _end(90))
    points, _d, _bs = _build_points(rows, T0, _end(90), 800, intervals)
    assert any(p.v is None for p in points)  # the gap breaks the line


def test_aggregated_steady_state_is_continuous_genuine_gap_breaks():
    # 30 days of valid 30-min samples, steady value, with one 6-hour unavailable
    # window -> aggregated buckets stay continuous except a single break.
    rows = []
    for m in range(0, 30 * 24 * 60, 30):
        if 5 * 24 * 60 <= m < 5 * 24 * 60 + 6 * 60:  # 6h unavailable on day 5
            rows.append(_s(m, None, "unavailable"))
        else:
            rows.append(_s(m, 5.0 + (0.2 if (m // 30) % 2 else -0.2)))
    end = _end(30 * 24 * 60)
    gaps = gap_ranges(reconstruct(rows, T0, end))
    buckets = _aggregate_buckets(rows, T0, end, 3600, 800, gaps)
    breaks = [b for b in buckets if b[1] is None]
    assert len(gaps) == 1  # only the genuine unavailable window
    assert 1 <= len(breaks) <= 3  # a single break run, not alternating dashes
    assert len([b for b in buckets if b[1] is not None]) > 600  # mostly continuous
