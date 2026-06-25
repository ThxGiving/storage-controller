"""Timezone-aware scheduling math for monthly report schedules (Phase 6).

All reporting periods are computed from **calendar boundaries in the schedule's
IANA timezone** (never by subtracting a fixed number of days), so DST is handled
correctly. A monthly schedule fires on ``run_day`` at ``run_time`` local and
reports the **previous complete calendar month**.

Example: a schedule firing 2026-07-01 06:00 Europe/Berlin reports
2026-06-01 00:00 .. 2026-07-01 00:00 (i.e. through 2026-06-30 23:59:59 local).
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .reporting.metrics import month_range_utc

__all__ = [
    "month_range_utc",
    "parse_hhmm",
    "previous_month",
    "fire_local",
    "next_run_utc",
    "latest_fire_utc",
    "reporting_period_for_fire",
]


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001 — unknown zone falls back to UTC
        return ZoneInfo("UTC")


def parse_hhmm(run_time: str) -> tuple[int, int]:
    try:
        hh, mm = run_time.split(":", 1)
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return 6, 0  # safe default 06:00


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def fire_local(year: int, month: int, run_day: int, h: int, m: int, zone: ZoneInfo) -> datetime:
    """The local fire datetime for a month, clamping run_day to the month length
    (so run_day=31 fires on the last day of shorter months)."""
    day = max(1, min(run_day, calendar.monthrange(year, month)[1]))
    return datetime(year, month, day, h, m, tzinfo=zone)


def next_run_utc(run_day: int, run_time: str, tz: str, after_utc: datetime) -> datetime:
    """First scheduled fire strictly after ``after_utc``, returned in UTC."""
    zone = _zone(tz)
    h, m = parse_hhmm(run_time)
    after_local = after_utc.astimezone(zone)
    year, month = after_local.year, after_local.month
    cand = fire_local(year, month, run_day, h, m, zone)
    if cand <= after_local:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        cand = fire_local(year, month, run_day, h, m, zone)
    return cand.astimezone(UTC)


def latest_fire_utc(run_day: int, run_time: str, tz: str, at_utc: datetime) -> datetime:
    """Most recent scheduled fire at or before ``at_utc``, returned in UTC."""
    zone = _zone(tz)
    h, m = parse_hhmm(run_time)
    at_local = at_utc.astimezone(zone)
    year, month = at_local.year, at_local.month
    cand = fire_local(year, month, run_day, h, m, zone)
    if cand > at_local:
        year, month = previous_month(year, month)
        cand = fire_local(year, month, run_day, h, m, zone)
    return cand.astimezone(UTC)


def reporting_period_for_fire(fire_utc: datetime, tz: str) -> tuple[int, int]:
    """The (year, month) reported by a fire — the previous calendar month of the
    fire's *local* month."""
    local = fire_utc.astimezone(_zone(tz))
    return previous_month(local.year, local.month)
