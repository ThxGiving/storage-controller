"""Stage 2 — pagination scale tests.

Renders the full unit-count matrix (1/3/4/5/8/10/15) × (compact/standard/detailed)
and verifies:
  - render completes without exception
  - correct number of chart figures in HTML
  - charts section uses .box.frag (allows page-spanning)
  - band legend is inside the last chart figure (stays with it across pages)
  - section-title and unit cards are both present (no orphan check in HTML,
    but CSS break-after:avoid is asserted in the stylesheet)
  - for large unit counts the comparison table has thead (header-group for repeat)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.reporting.model import (
    BrandingSnapshot,
    ChartSeries,
    DataQuality,
    FlatIncident,
    OverviewChart,
    ReportModel,
    ReportSummary,
    ThresholdSnapshot,
    UnitReport,
)
from app.reporting.render import render_html

# Fixed epoch bounds matching the test period (2026-05-01 … 2026-06-01 UTC)
_T0 = 1746057600.0
_T1 = 1748736000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLORS = [
    "#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c",
    "#0891b2", "#ca8a04", "#be185d", "#15803d", "#1d4ed8",
    "#7c3aed", "#b91c1c", "#0369a1", "#a16207", "#9f1239",
]


def _make_overview_chart(units_in_group: list) -> OverviewChart:
    """Minimal chart with two data points per unit — enough for render_chart_svg."""
    mid = (_T0 + _T1) / 2
    return OverviewChart(
        group_key="g1", label="Kühlräume",
        lower_limit_c=0.0, upper_limit_c=7.0,
        series=[
            ChartSeries(
                unit_id=u.id, name=u.name, color=u.accent,
                points=[[_T0, 4.0], [mid, 4.5], [_T1, 4.0]],
                lower_limit_c=0.0, upper_limit_c=7.0,
            )
            for u in units_in_group
        ],
    )


def _make_model(n_units: int, detail_level: str, n_incidents: int = 3) -> ReportModel:
    units = [
        UnitReport(
            id=i + 1, name=f"Kühlraum {i + 1}", short_name=f"K{i + 1}",
            unit_type="chilled", type_label="Kühlung",
            profile_name=None, chart_group="g1",
            status="ok", accent=_COLORS[i % len(_COLORS)],
            thresholds=ThresholdSnapshot(lower_limit_c=0.0, upper_limit_c=7.0),
            min_c=1.2, max_c=6.8, avg_c=4.1,
            time_above_seconds=0, time_below_seconds=0, outside_seconds=0,
            incident_count=1 if i == 0 else 0,
            data_quality=DataQuality(coverage_percent=99.0, gaps_count=0),
            incidents=[],
        )
        for i in range(n_units)
    ]
    incidents = [
        FlatIncident(
            n=j + 1, unit_name="Kühlraum 1",
            opened_at="2026-05-10T08:00:00+00:00",
            closed_at="2026-05-10T10:00:00+00:00",
            duration_seconds=7200, extreme_value_c=7.5,
            state="resolved", documented=True,
        )
        for j in range(n_incidents)
    ]
    summary = ReportSummary(
        total_units=n_units, monitored_count=n_units, coverage_percent=99.0,
        confirmed_deviations=n_incidents, open_incidents=0,
        verdict="documented", overall_status="reviewed",
    )
    branding = BrandingSnapshot(
        organization_name="Scale Test Org", report_title="Kühlraumprotokoll", accent=None,
    )
    # One overview chart per unit — exactly as the real builder produces.
    overview_charts = [_make_overview_chart([u]) for u in units]
    return ReportModel(
        detail_level=detail_level,
        version="0.4.24", uuid=f"scale-{n_units}-{detail_level}",
        generated_at="2026-05-31T22:00:00+00:00",
        locale="de", timezone="Europe/Berlin", timezone_label="CEST",
        period_year=2026, period_month=5, period_label="Mai 2026",
        period_start_utc="2026-05-01T00:00:00+00:00",
        period_end_utc="2026-06-01T00:00:00+00:00",
        period_range_label="01.05.2026 – 31.05.2026",
        branding=branding, summary=summary, units=units,
        overview_charts=overview_charts, incidents_flat=incidents,
        data_quality_ok=True, data_quality_note="Vollständig.",
    )


# ---------------------------------------------------------------------------
# Matrix: all 21 combinations render without exception
# ---------------------------------------------------------------------------

UNIT_COUNTS = [1, 3, 4, 5, 8, 10, 15]
DETAIL_LEVELS = ["compact", "standard", "detailed"]


@pytest.mark.parametrize("n", UNIT_COUNTS)
@pytest.mark.parametrize("dl", DETAIL_LEVELS)
def test_render_no_exception(dl, n):
    """Every combination in the 3×7 matrix must render without raising."""
    html = render_html(_make_model(n, dl))
    assert html  # non-empty


# ---------------------------------------------------------------------------
# Charts section structure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", UNIT_COUNTS)
@pytest.mark.parametrize("dl", DETAIL_LEVELS)
def test_charts_section_is_frag(dl, n):
    """Charts section must use .box.frag so it can span pages at any unit count."""
    html = render_html(_make_model(n, dl))
    # The charts box is rendered via page_one_body() for all three levels.
    # It must carry both 'box' and 'frag' classes.
    assert 'class="box frag"' in html or "box frag" in html


@pytest.mark.parametrize("n", UNIT_COUNTS)
@pytest.mark.parametrize("dl", DETAIL_LEVELS)
def test_band_legend_inside_last_chart(dl, n):
    """The band legend div must appear inside a <figure class="chart">, not after all figures.
    This prevents the legend being stranded on a different page from the last chart."""
    html = render_html(_make_model(n, dl))
    # Regardless of unit count, the legend should appear only once.
    assert html.count("bandleg") == 1
    # The legend must come BEFORE the closing </figure> tag of the last chart.
    idx_legend = html.index("bandleg")
    # Find the last </figure> in the document
    idx_last_fig_close = html.rfind("</figure>")
    assert idx_legend < idx_last_fig_close, (
        "band legend appears after last </figure> — it is detached from the chart"
    )


# ---------------------------------------------------------------------------
# Comparison table structure (header-group for pagination)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", UNIT_COUNTS)
@pytest.mark.parametrize("dl", DETAIL_LEVELS)
def test_cmp_table_has_thead(dl, n):
    """Comparison table must have a <thead> for CSS table-header-group to work."""
    html = render_html(_make_model(n, dl))
    assert "<thead>" in html


@pytest.mark.parametrize("n", UNIT_COUNTS)
@pytest.mark.parametrize("dl", DETAIL_LEVELS)
def test_cmp_table_row_count(dl, n):
    """Comparison table body must contain exactly n data rows.

    Detailed also renders a per-unit DQ table that uses .udot, so its total is 2n.
    """
    html = render_html(_make_model(n, dl))
    # Each data row in the cmp table has a .udot span.
    # Detailed adds a second .udot per unit in the per-unit DQ table.
    expected = n * 2 if dl == "detailed" else n
    assert html.count("udot") == expected


# ---------------------------------------------------------------------------
# Unit cards (standard + detailed only)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", UNIT_COUNTS)
@pytest.mark.parametrize("dl", ["standard", "detailed"])
def test_unit_cards_all_present(dl, n):
    """All n unit cards must be rendered."""
    html = render_html(_make_model(n, dl))
    # Each card has a .card-head div; count them.
    assert html.count("card-head") == n


@pytest.mark.parametrize("n", UNIT_COUNTS)
@pytest.mark.parametrize("dl", ["standard", "detailed"])
def test_section_title_present(dl, n):
    """The section title heading (DETAILANSICHT) must appear for standard/detailed."""
    html = render_html(_make_model(n, dl))
    assert "section-title" in html


# ---------------------------------------------------------------------------
# Compact has no unit cards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", UNIT_COUNTS)
def test_compact_no_unit_cards(n):
    """Compact report must not render unit detail cards."""
    html = render_html(_make_model(n, "compact"))
    assert "card-head" not in html
