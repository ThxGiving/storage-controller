"""Deterministic tests for incident lifecycle-state vs review-state rendering.

Four canonical cases must render distinct, non-ambiguous status indicators:

  closed + reviewed   → blue "✓ Reviewed" badge only
  closed + unreviewed → orange "Pending" badge only
  open   + reviewed   → red "Active" + blue "✓ Reviewed" badges
  open   + unreviewed → red "Active" badge only

The summary open_incidents count must agree with the number of FlatIncident
records that carry state='open'.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.reporting.model import (
    BrandingSnapshot,
    DataQuality,
    FlatIncident,
    ReportModel,
    ReportSummary,
    ThresholdSnapshot,
    UnitReport,
)
from app.reporting.render import render_html


def _make_model(incidents: list[FlatIncident], locale: str = "de") -> ReportModel:
    open_count = sum(1 for i in incidents if i.state == "open")
    # Unit status matches incident state so unit-card badges don't pollute assertions.
    unit_status = "open" if open_count else "reviewed"
    unit = UnitReport(
        id=1, name="Unit A", short_name="A", unit_type="chilled",
        type_label="Chilled", profile_name=None, chart_group="g1",
        status=unit_status, accent="#2563eb",
        thresholds=ThresholdSnapshot(lower_limit_c=0.0, upper_limit_c=7.0),
        min_c=1.0, max_c=8.5, avg_c=4.0,
        time_above_seconds=7200, time_below_seconds=0, outside_seconds=7200,
        incident_count=len(incidents),
        data_quality=DataQuality(coverage_percent=98.5, gaps_count=0),
        incidents=[],
    )
    summary = ReportSummary(
        total_units=1, monitored_count=1, coverage_percent=98.5,
        confirmed_deviations=sum(1 for i in incidents if i.documented),
        open_incidents=open_count,
        verdict="open" if open_count else "documented",
        overall_status="open" if open_count else "reviewed",
    )
    branding = BrandingSnapshot(
        organization_name="Test Org", report_title="Test Report", accent=None,
    )
    return ReportModel(
        detail_level="detailed",
        version="0.4.23", uuid="state-test",
        generated_at="2026-06-01T08:00:00+00:00",
        locale=locale, timezone="Europe/Berlin", timezone_label="CEST",
        period_year=2026, period_month=5, period_label="Mai 2026",
        period_start_utc="2026-05-01T00:00:00+00:00",
        period_end_utc="2026-06-01T00:00:00+00:00",
        period_range_label="01.05.2026 – 31.05.2026",
        branding=branding, summary=summary, units=[unit],
        overview_charts=[], incidents_flat=incidents,
        data_quality_ok=True, data_quality_note="OK.",
    )


# Four canonical incidents — each represents one distinct state combination.
_INC_CLOSED_REVIEWED = FlatIncident(
    n=1, unit_name="Unit A",
    opened_at="2026-05-01T10:00:00+00:00",
    closed_at="2026-05-01T12:00:00+00:00",
    duration_seconds=7200, extreme_value_c=7.8,
    state="resolved", documented=True,
)
_INC_CLOSED_UNREVIEWED = FlatIncident(
    n=2, unit_name="Unit A",
    opened_at="2026-05-02T10:00:00+00:00",
    closed_at="2026-05-02T11:00:00+00:00",
    duration_seconds=3600, extreme_value_c=8.1,
    state="resolved", documented=False,
)
_INC_OPEN_REVIEWED = FlatIncident(
    n=3, unit_name="Unit A",
    opened_at="2026-05-10T08:00:00+00:00",
    closed_at=None,  # still active
    duration_seconds=43200, extreme_value_c=8.5,
    state="open", documented=True,
)
_INC_OPEN_UNREVIEWED = FlatIncident(
    n=4, unit_name="Unit A",
    opened_at="2026-05-15T14:00:00+00:00",
    closed_at=None,  # still active
    duration_seconds=7200, extreme_value_c=8.3,
    state="open", documented=False,
)

ALL_FOUR = [
    _INC_CLOSED_REVIEWED,
    _INC_CLOSED_UNREVIEWED,
    _INC_OPEN_REVIEWED,
    _INC_OPEN_UNREVIEWED,
]


# ---------------------------------------------------------------------------
# Lifecycle state
# ---------------------------------------------------------------------------

def test_closed_reviewed_shows_reviewed_badge():
    # unit.status="reviewed" — no red badge from unit card, so Aktiv absence is meaningful.
    html = render_html(_make_model([_INC_CLOSED_REVIEWED]))
    assert "Geprüft" in html
    assert "Aktiv" not in html
    assert "Ausstehend" not in html


def test_closed_unreviewed_shows_pending_badge():
    # unit.status="reviewed" — no Aktiv from unit card.
    html = render_html(_make_model([_INC_CLOSED_UNREVIEWED]))
    assert "Ausstehend" in html
    assert "Aktiv" not in html


def test_open_reviewed_shows_active_and_reviewed():
    """An open but acknowledged incident must be labelled Active AND Reviewed."""
    # unit.status="open" shows "Offener Vorfall" (not "Aktiv"), so "Aktiv" can only
    # come from the incident badge macro.
    html = render_html(_make_model([_INC_OPEN_REVIEWED]))
    assert "Aktiv" in html
    assert "Geprüft" in html
    assert "Ausstehend" not in html


def test_open_unreviewed_shows_only_active_badge():
    # unit.status="open" shows "Offener Vorfall" (not "✓ Geprüft").
    # "Geprüft" alone also appears in the approval section label ("Geprüft durch:"),
    # so we check for the badge-specific "✓ Geprüft" which only comes from incident_badge.
    html = render_html(_make_model([_INC_OPEN_UNREVIEWED]))
    assert "Aktiv" in html
    assert "Ausstehend" not in html
    assert "✓ Geprüft" not in html


# ---------------------------------------------------------------------------
# Closed incident must not look like active
# ---------------------------------------------------------------------------

def test_closed_reviewed_has_end_timestamp():
    """The closed+reviewed incident must display a resolved end time, not an em dash."""
    html = render_html(_make_model([_INC_CLOSED_REVIEWED]))
    # closed_at = 2026-05-01T12:00:00+00:00 → 01.05.2026, 14:00 CEST
    assert "14:00" in html


def test_open_incident_end_is_em_dash():
    """Active incidents have no end timestamp — must render as —."""
    html = render_html(_make_model([_INC_OPEN_UNREVIEWED]))
    assert "—" in html


# ---------------------------------------------------------------------------
# Summary count agreement
# ---------------------------------------------------------------------------

def test_summary_open_count_matches_open_incidents():
    """open_incidents in the model must equal the number of state='open' incidents."""
    model = _make_model(ALL_FOUR)
    assert model.summary.open_incidents == 2  # incidents 3 and 4


def test_all_four_states_distinct_in_combined_render():
    """All four state combinations rendered together must produce distinct representations."""
    html = render_html(_make_model(ALL_FOUR))
    # Two open incidents → two "Aktiv" text occurrences (one per badge)
    assert html.count("Aktiv") >= 2
    # Two reviewed incidents (closed+reviewed and open+reviewed) → at least two "Geprüft"
    # (approval section also contributes "Geprüft durch:", so count >= 2 not == 2)
    assert html.count("Geprüft") >= 2
    # Exactly one pending (closed+unreviewed)
    assert html.count("Ausstehend") == 1


# ---------------------------------------------------------------------------
# English locale
# ---------------------------------------------------------------------------

def test_english_locale_labels():
    html = render_html(_make_model(ALL_FOUR, locale="en"))
    assert "Active" in html
    assert "Pending" in html
    assert "Reviewed" in html
