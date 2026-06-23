"""Deterministic tests for report chart aggregation + interval semantics (Phase 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import db as db_module
from app.models import EntityAssignment, SensorSample, StorageUnit
from app.reporting.metrics import (
    _aggregate_buckets,
    _violation_ranges,
    sample_metrics,
)
from app.reporting.render import _fmt_dt, _fmt_duration, _fmt_pct, _fmt_temp


def test_german_locale_formatting():
    assert _fmt_temp(3.9, "de") == "3,9 °C"
    assert _fmt_temp(3.9, "en") == "3.9 °C"
    assert _fmt_pct(7.7, "de") == "7,7 %"
    assert _fmt_pct(7.7, "en") == "7.7 %"
    assert _fmt_duration(16 * 60, "de") == "16 min"
    assert _fmt_duration(2 * 3600 + 5 * 60, "de") == "2 h 5 min"
    assert _fmt_dt("2026-06-23T01:05:00+00:00", "de") == "23.06.2026, 01:05"
    assert _fmt_dt("2026-06-23T01:05:00+00:00", "en") == "2026-06-23 01:05"


def test_buckets_positioned_at_real_timestamps_not_stretched():
    # A 30-day period with data only on the LAST day. Buckets must sit near the
    # end, and the leading 29 days must be a gap (not stretched/extended).
    start = T0
    end = T0 + timedelta(days=30)
    last_day = end - timedelta(days=1)
    samples = [_s_at(last_day + timedelta(minutes=10 * i), 5.0) for i in range(12)]
    buckets, gaps = _aggregate_buckets(samples, start, end, bucket_seconds=3600, max_points=800)
    filled = [b for b in buckets if b[1] is not None]
    assert filled, "expected some filled buckets"
    # every filled bucket is in the last day, not spread across the month
    assert all(b[0] >= last_day.timestamp() - 3600 for b in filled)
    # a long leading gap exists, starting at the period start
    assert gaps and gaps[0][0] == start.timestamp()


def _s_at(dt, value, q="valid"):
    return (dt, value, q)

T0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
VALID = "valid"
UNAVAIL = "unavailable"


def _s(minutes, value, q=VALID):
    return (T0 + timedelta(minutes=minutes), value, q)


# --------------------------------------------------------------------------- #
# Pure interval semantics
# --------------------------------------------------------------------------- #


def test_violation_only_from_measured_valid_samples():
    # In-range, then a 3-sample spike above upper=8, then back in range.
    samples = [_s(0, 5), _s(5, 6), _s(10, 9), _s(15, 9.5), _s(20, 9), _s(25, 6)]
    ranges = _violation_ranges(samples, lower=0, upper=8, gap_threshold=1800)
    assert len(ranges) == 1
    start, end = ranges[0]
    assert start == samples[2][0].timestamp()  # first violating sample
    assert end == samples[5][0].timestamp()    # closed at the recovering sample


def test_unavailable_is_never_a_violation():
    samples = [_s(0, 5), _s(5, None, UNAVAIL), _s(10, None, UNAVAIL), _s(15, 5)]
    assert _violation_ranges(samples, lower=0, upper=8, gap_threshold=1800) == []


def test_violation_not_extended_across_gap_or_past_last_sample():
    # Violating, then a long gap (no data) — the red interval must NOT extend
    # across the gap or to the period end; it ends at the last measured sample.
    samples = [_s(0, 9), _s(5, 9.5)]  # then nothing for the rest of the month
    ranges = _violation_ranges(samples, lower=0, upper=8, gap_threshold=1800)
    assert len(ranges) == 1
    start, end = ranges[0]
    assert end == samples[1][0].timestamp()  # last measured point, not later


def test_in_range_average_cannot_hide_out_of_range_extremum():
    # A bucket whose average is in range but whose max exceeds the limit must
    # still surface the excursion (envelope max) AND a violation interval.
    base = [_s(m, 6.0) for m in range(0, 60, 5)]  # avg ~6 (in range, upper=8)
    base[6] = _s(30, 11.0)  # one spike
    end = T0 + timedelta(hours=1)
    buckets, _gaps = _aggregate_buckets(base, T0, end, bucket_seconds=3600, max_points=800)
    assert len(buckets) == 1
    _epoch, avg, lo, hi = buckets[0]
    assert avg is not None and avg <= 8  # average stays in range
    assert hi == 11.0  # but the max preserves the spike
    assert _violation_ranges(base, lower=0, upper=8, gap_threshold=1800)  # and it's a violation


def test_aggregation_reduces_dense_data_and_marks_gaps():
    # 7 days of 5-min hysteresis data -> hourly buckets are bounded and a missing
    # window becomes a single None break (never interpolated).
    samples = []
    for m in range(0, 7 * 24 * 60, 5):
        v = 5 + (1 if (m // 5) % 2 else -1) * 1.5  # raw zig-zag
        if 2 * 24 * 60 <= m < 3 * 24 * 60:  # a one-day gap
            continue
        samples.append(_s(m, v))
    end = T0 + timedelta(days=7)
    buckets, gaps = _aggregate_buckets(samples, T0, end, bucket_seconds=3600, max_points=800)
    assert len(buckets) <= 800  # bounded
    assert any(b[1] is None for b in buckets)  # the gap is a break
    assert len(gaps) == 1  # the one-day blackout is a single gap range
    # average is calm (~5) while the envelope keeps the ±1.5 swing
    filled = [b for b in buckets if b[1] is not None]
    assert all(abs(b[1] - 5) < 0.5 for b in filled)
    assert any(b[3] - b[2] > 2.0 for b in filled)  # min–max envelope preserved


# --------------------------------------------------------------------------- #
# Metrics invariance under aggregation (DB-backed)
# --------------------------------------------------------------------------- #


async def _unit_with_samples(client, lower, upper):
    r = await client.post(
        "/api/storage-units",
        json={"name": "u", "lower_limit_c": lower, "upper_limit_c": upper,
              "assignments": [{"role": "room_temperature", "entity_id": "sensor.u"}]},
    )
    uid = r.json()["id"]
    factory = db_module.get_session_factory()
    async with factory() as s:
        from sqlalchemy import select

        aid = await s.scalar(select(EntityAssignment.id).where(EntityAssignment.storage_unit_id == uid))
        for m in range(0, 6 * 60, 5):
            v = (lower + upper) / 2 + (1.2 if (m // 5) % 2 else -1.2)
            if m == 120:
                v = upper + 2.0  # spike
            s.add(SensorSample(
                storage_unit_id=uid, entity_assignment_id=aid, entity_id="sensor.u",
                role="room_temperature", event_timestamp=T0 + timedelta(minutes=m),
                received_timestamp=T0, raw_value=str(v), numeric_value=v,
                normalized_value_c=v, quality="valid", source="live_websocket",
            ))
        await s.commit()
    return uid


@pytest.mark.asyncio
async def test_metrics_invariant_to_bucket_size(app_client):
    uid = await _unit_with_samples(app_client, 0.0, 8.0)
    factory = db_module.get_session_factory()
    async with factory() as s:
        end = T0 + timedelta(hours=6)
        coarse = await sample_metrics(
            s, storage_unit_id=uid, start_utc=T0, end_utc=end,
            lower=0.0, upper=8.0, heartbeat_seconds=300, bucket_seconds=3600,
        )
        fine = await sample_metrics(
            s, storage_unit_id=uid, start_utc=T0, end_utc=end,
            lower=0.0, upper=8.0, heartbeat_seconds=300, bucket_seconds=300,
        )
    # Metrics derived from raw must NOT depend on chart bucket size.
    assert coarse.min_c == fine.min_c
    assert coarse.max_c == fine.max_c
    assert coarse.time_above_seconds == fine.time_above_seconds
    assert coarse.violation_ranges == fine.violation_ranges
    # Only the chart resolution differs.
    assert len(coarse.chart_points) < len(fine.chart_points)
    assert coarse.max_c >= 8.0  # the spike survived aggregation in the metrics
