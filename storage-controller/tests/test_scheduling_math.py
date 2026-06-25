"""Deterministic scheduling math: previous-calendar-month, boundaries, leap year,
CET/CEST transitions, next-run (Phase 6). All in the schedule's IANA timezone."""

from __future__ import annotations

from datetime import UTC, datetime

from app.scheduling import (
    latest_fire_utc,
    month_range_utc,
    next_run_utc,
    previous_month,
    reporting_period_for_fire,
)

TZ = "Europe/Berlin"


def test_previous_month_wraps_year():
    assert previous_month(2026, 1) == (2025, 12)
    assert previous_month(2026, 7) == (2026, 6)


def test_monthly_run_reports_previous_calendar_month():
    # Fires 2026-07-01 06:00 Europe/Berlin (=04:00 UTC, CEST).
    fire = latest_fire_utc(1, "06:00", TZ, datetime(2026, 7, 1, 4, 0, tzinfo=UTC))
    assert fire == datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    assert reporting_period_for_fire(fire, TZ) == (2026, 6)


def test_june_boundaries_are_calendar_aware():
    start, end = month_range_utc(2026, 6, TZ)
    # 01.06 00:00 CEST = 31.05 22:00 UTC; end is 01.07 00:00 CEST exclusive.
    assert start == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)


def test_february_leap_year_boundaries():
    start, end = month_range_utc(2024, 2, TZ)  # 2024 is a leap year (29 days)
    assert start == datetime(2024, 1, 31, 23, 0, tzinfo=UTC)  # CET (UTC+1) in winter
    assert end == datetime(2024, 2, 29, 23, 0, tzinfo=UTC)  # 29 Feb exists


def test_february_non_leap_year_boundaries():
    _start, end = month_range_utc(2025, 2, TZ)
    assert end == datetime(2025, 2, 28, 23, 0, tzinfo=UTC)  # 28 Feb, no 29th


def test_next_run_advances_one_month():
    nxt = next_run_utc(1, "06:00", TZ, datetime(2026, 7, 1, 12, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 8, 1, 4, 0, tzinfo=UTC)


def test_dst_winter_vs_summer_fire_in_utc():
    # 06:00 local is 05:00 UTC in winter (CET, UTC+1), 04:00 UTC in summer (CEST).
    winter = next_run_utc(1, "06:00", TZ, datetime(2025, 12, 15, tzinfo=UTC))
    summer = next_run_utc(1, "06:00", TZ, datetime(2026, 6, 15, tzinfo=UTC))
    assert winter.hour == 5
    assert summer.hour == 4


def test_run_day_clamped_to_month_length():
    # run_day=31 fires on the last day of a 30-day month.
    fire = latest_fire_utc(31, "06:00", TZ, datetime(2026, 7, 1, tzinfo=UTC))
    local = fire.astimezone(__import__("zoneinfo").ZoneInfo(TZ))
    assert local.day == 30 and local.month == 6  # 30 June, not an invalid 31 June


def test_cet_cest_spring_transition_period():
    # March 2026 contains the spring-forward; boundaries still align to calendar.
    start, end = month_range_utc(2026, 3, TZ)
    assert start == datetime(2026, 2, 28, 23, 0, tzinfo=UTC)  # CET start
    assert end == datetime(2026, 3, 31, 22, 0, tzinfo=UTC)  # CEST end (clocks moved)
