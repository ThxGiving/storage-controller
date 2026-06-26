"""Deterministic tests for report timestamp localisation.

Root cause of the bug fixed here: _fmt_dt() formatted UTC ISO strings
without converting them to the report's configured timezone. Generated_at
was stored as UTC (e.g. 00:26+00:00) and displayed as 00:26, while the
period-range label — pre-formatted in builder.py using timezone-aware
calendar boundaries — showed the correct local time (02:26 CEST), creating
the visible inconsistency reported in the PDF.

The fix: _fmt_dt_local() accepts an IANA timezone string, converts
timezone-aware datetimes to that zone before formatting, and is wired up
as the `dtlocal` Jinja filter used for all display timestamps in the
report template.
"""

from app.reporting.render import _fmt_dt, _fmt_dt_local


# ---------------------------------------------------------------------------
# Core timezone conversion
# ---------------------------------------------------------------------------

def test_utc_to_cest():
    """00:26 UTC during CEST (summer) must display as 02:26 CEST (+2)."""
    assert _fmt_dt_local("2026-06-26T00:26:00+00:00", "de", "Europe/Berlin") == "26.06.2026, 02:26"


def test_utc_to_cet():
    """00:26 UTC during CET (winter) must display as 01:26 CET (+1)."""
    assert _fmt_dt_local("2026-01-15T00:26:00+00:00", "de", "Europe/Berlin") == "15.01.2026, 01:26"


def test_english_format_cest():
    """English locale uses YYYY-MM-DD HH:MM."""
    assert _fmt_dt_local("2026-06-26T00:26:00+00:00", "en", "Europe/Berlin") == "2026-06-26 02:26"


def test_utc_zone():
    """Europe/London outside BST (UTC+0) — no offset applied."""
    assert _fmt_dt_local("2026-01-15T14:30:00+00:00", "en", "UTC") == "2026-01-15 14:30"


# ---------------------------------------------------------------------------
# Midnight transitions
# ---------------------------------------------------------------------------

def test_midnight_cest_crosses_to_next_day():
    """23:00 UTC → 01:00 local; date changes from the 25th to the 26th."""
    assert _fmt_dt_local("2026-06-25T23:00:00+00:00", "de", "Europe/Berlin") == "26.06.2026, 01:00"


def test_midnight_cet_crosses_to_next_day():
    """23:00 UTC in CET → 00:00 local; date and hour both change."""
    assert _fmt_dt_local("2026-01-14T23:00:00+00:00", "de", "Europe/Berlin") == "15.01.2026, 00:00"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_naive_datetime_no_conversion():
    """Naive datetime (no tzinfo) must not be shifted — return as-is."""
    assert _fmt_dt_local("2026-06-26T14:30:00", "de", "Europe/Berlin") == "26.06.2026, 14:30"


def test_empty_string_returns_dash():
    assert _fmt_dt_local("", "de", "Europe/Berlin") == "—"
    assert _fmt_dt("", "de") == "—"


def test_invalid_iso_returns_original():
    assert _fmt_dt_local("not-a-date", "de", "Europe/Berlin") == "not-a-date"


# ---------------------------------------------------------------------------
# Verify the old UTC-display bug no longer applies to dtlocal
# ---------------------------------------------------------------------------

def test_dtlocal_differs_from_dt_in_non_utc_zone():
    """Confirm the fix: dtlocal returns local time; dt still returns UTC time."""
    iso = "2026-06-26T00:26:00+00:00"
    utc_display = _fmt_dt(iso, "de")
    local_display = _fmt_dt_local(iso, "de", "Europe/Berlin")
    assert utc_display == "26.06.2026, 00:26"   # old / raw UTC
    assert local_display == "26.06.2026, 02:26"  # correct CEST
    assert utc_display != local_display


# ---------------------------------------------------------------------------
# DST boundary — clocks spring forward on last Sunday of March
# ---------------------------------------------------------------------------

def test_cest_dst_boundary_before():
    """One minute before DST switch (02:00 CET → 03:00 CEST on 2026-03-29):
    00:59 UTC = 01:59 CET (still standard time)."""
    assert _fmt_dt_local("2026-03-29T00:59:00+00:00", "de", "Europe/Berlin") == "29.03.2026, 01:59"


def test_cest_dst_boundary_after():
    """One minute after DST switch: 01:00 UTC = 03:00 CEST (summer time)."""
    assert _fmt_dt_local("2026-03-29T01:00:00+00:00", "de", "Europe/Berlin") == "29.03.2026, 03:00"
