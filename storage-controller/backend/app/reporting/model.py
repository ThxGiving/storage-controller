"""Immutable report model (Phase 5).

This pydantic structure is the single source of truth for a generated report. PDF,
CSV and JSON are all derived from it — never directly from database rows or the
dashboard. Once a report is generated the serialized model is frozen and checksummed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BrandingSnapshot(BaseModel):
    organization_name: str | None = None
    site_name: str | None = None
    address: str | None = None
    contact: str | None = None
    logo_filename: str | None = None
    report_title: str | None = None
    subtitle: str | None = None
    accent: str | None = None
    footer_text: str | None = None
    disclaimer: str | None = None
    signature_labels: list[str] = Field(default_factory=list)


class ThresholdSnapshot(BaseModel):
    """Configured safety limits — never learned, never operational defrost values."""

    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    warning_margin_c: float = 0.0


class IncidentSummary(BaseModel):
    id: int
    type: str
    state: str
    opened_at: str
    closed_at: str | None = None
    duration_seconds: int
    extreme_value_c: float | None = None
    limit_value_c: float | None = None
    defrost_overlap: bool = False
    acknowledged: bool = False
    documented: bool = False
    cause: str | None = None  # user free text, never auto-translated
    corrective_action: str | None = None  # user free text, never auto-translated
    note: str | None = None  # user free text, never auto-translated


class DefrostSummary(BaseModel):
    cycle_count: int = 0
    completed_count: int = 0
    abnormal_count: int = 0
    reconstructed_count: int = 0
    typical_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    typical_recovery_seconds: int | None = None
    max_recovery_seconds: int | None = None
    has_approved_model: bool = False


class DataQuality(BaseModel):
    valid_count: int = 0
    total_count: int = 0
    expected_count: int | None = None
    coverage_percent: float | None = None
    unavailable_seconds: int = 0
    invalid_seconds: int = 0
    gap_seconds: int = 0
    gaps_count: int = 0
    missing_entity: bool = False
    incomplete: bool = False


class ChartBand(BaseModel):
    kind: str  # deviation | gap | defrost
    start: float  # epoch seconds
    end: float


class ChartSeries(BaseModel):
    unit_id: int
    name: str
    color: str = "#2563eb"
    points: list[list[float | None]] = Field(default_factory=list)  # [epoch_s, value|None]
    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    bands: list[ChartBand] = Field(default_factory=list)


class OverviewChart(BaseModel):
    group_key: str  # chilled | frozen | <chart_group>
    label: str
    unit: str = "°C"
    series: list[ChartSeries] = Field(default_factory=list)
    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    bands: list[ChartBand] = Field(default_factory=list)


class UnitReport(BaseModel):
    id: int
    name: str
    short_name: str | None = None
    unit_type: str
    type_label: str = ""  # subtitle shown under the name
    profile_name: str | None = None
    chart_group: str
    status: str = "ok"  # ok | reviewed | attention
    accent: str = "#16a34a"  # header/accent color derived from status
    thresholds: ThresholdSnapshot

    min_c: float | None = None
    max_c: float | None = None
    avg_c: float | None = None

    time_above_seconds: int = 0
    time_below_seconds: int = 0
    outside_seconds: int = 0

    incident_count: int = 0
    total_incident_seconds: int = 0
    longest_incident_seconds: int = 0
    incident_extreme_c: float | None = None

    data_quality: DataQuality = Field(default_factory=DataQuality)
    defrost: DefrostSummary | None = None
    incidents: list[IncidentSummary] = Field(default_factory=list)
    chart: ChartSeries | None = None  # per-unit mini chart


class FlatIncident(BaseModel):
    n: int
    unit_name: str
    opened_at: str
    duration_seconds: int
    extreme_value_c: float | None = None
    cause: str | None = None
    corrective_action: str | None = None
    state: str
    documented: bool = False


class ReportSummary(BaseModel):
    total_units: int = 0
    monitored_count: int = 0
    units_with_incidents: int = 0
    total_incidents: int = 0
    confirmed_deviations: int = 0
    open_incidents: int = 0
    overall_status: str = "ok"  # ok | attention | incomplete
    verdict: str = "ok"  # ok | documented | open | incomplete
    coverage_percent: float | None = None


class ReportModel(BaseModel):
    version: str
    uuid: str
    generated_at: str
    locale: str
    timezone: str
    timezone_label: str

    period_year: int
    period_month: int
    period_label: str
    period_start_utc: str
    period_end_utc: str
    detail_level: str

    period_range_label: str = ""  # e.g. "01.05.2026 00:00 – 31.05.2026 23:59"
    branding: BrandingSnapshot
    summary: ReportSummary
    units: list[UnitReport] = Field(default_factory=list)
    overview_charts: list[OverviewChart] = Field(default_factory=list)
    incidents_flat: list[FlatIncident] = Field(default_factory=list)
    data_quality_ok: bool = True
    data_quality_note: str = ""
