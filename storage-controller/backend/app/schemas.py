"""Pydantic request/response models for the internal App API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import EntityRole, StorageUnitType

# --------------------------------------------------------------------------- #
# Home Assistant entities
# --------------------------------------------------------------------------- #


class HAEntity(BaseModel):
    entity_id: str
    domain: str
    friendly_name: str | None = None
    state: str | None = None
    unit_of_measurement: str | None = None
    device_class: str | None = None
    device_name: str | None = None
    available: bool = True
    last_changed: datetime | None = None
    last_updated: datetime | None = None


class ConnectionStatus(BaseModel):
    status: str  # connected | reconnecting | disconnected | authentication_error
    last_event_at: datetime | None = None
    last_connected_at: datetime | None = None
    reconnect_attempts: int = 0
    entity_count: int = 0
    detail: str | None = None


class AppStatus(BaseModel):
    name: str = "Storage Controller"
    version: str
    home_assistant: ConnectionStatus
    storage_unit_count: int
    database_ok: bool


# --------------------------------------------------------------------------- #
# Entity assignments
# --------------------------------------------------------------------------- #


class EntityAssignmentIn(BaseModel):
    role: EntityRole
    entity_id: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    invert_state: bool = False

    @field_validator("entity_id")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class EntityAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: EntityRole
    entity_id: str
    enabled: bool
    invert_state: bool


# --------------------------------------------------------------------------- #
# Storage units
# --------------------------------------------------------------------------- #


class StorageUnitBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    short_report_name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    location: str | None = None
    unit_type: StorageUnitType = StorageUnitType.custom
    enabled: bool = True
    sort_order: int = 0

    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    warning_margin_c: float = 0.0

    violation_delay_seconds: int = Field(default=900, ge=0)
    recovery_delay_seconds: int = Field(default=300, ge=0)
    offline_delay_seconds: int = Field(default=600, ge=0)
    defrost_grace_enabled: bool = False
    defrost_grace_seconds: int = Field(default=0, ge=0)

    plausible_min_c: float | None = None
    plausible_max_c: float | None = None
    chart_group: str | None = None
    report_enabled: bool = True

    applied_profile_key: str | None = None
    applied_profile_name: str | None = None

    # Defrost-aware evaluation (Phase 4)
    defrost_evaluation_enabled: bool = False
    maximum_expected_defrost_duration_seconds: int = Field(default=1800, ge=0)
    pre_defrost_correlation_seconds: int = Field(default=300, ge=0)
    post_defrost_recovery_seconds: int = Field(default=1800, ge=0)
    maximum_expected_room_temperature_c: float | None = None
    maximum_expected_evaporator_temperature_c: float | None = None
    recovery_target_temperature_c: float | None = None
    maximum_recovery_duration_seconds: int = Field(default=3600, ge=0)
    expected_defrost_excursions_visible_in_incident_list: bool = False
    abnormal_defrost_creates_incident: bool = True
    manual_review_required_after_abnormal_defrost: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class StorageUnitCreate(StorageUnitBase):
    assignments: list[EntityAssignmentIn] = Field(default_factory=list)


class StorageUnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    short_report_name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    location: str | None = None
    unit_type: StorageUnitType | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    warning_margin_c: float | None = None
    violation_delay_seconds: int | None = Field(default=None, ge=0)
    recovery_delay_seconds: int | None = Field(default=None, ge=0)
    offline_delay_seconds: int | None = Field(default=None, ge=0)
    defrost_grace_enabled: bool | None = None
    defrost_grace_seconds: int | None = Field(default=None, ge=0)
    plausible_min_c: float | None = None
    plausible_max_c: float | None = None
    chart_group: str | None = None
    report_enabled: bool | None = None
    applied_profile_key: str | None = None
    applied_profile_name: str | None = None
    defrost_evaluation_enabled: bool | None = None
    maximum_expected_defrost_duration_seconds: int | None = Field(default=None, ge=0)
    pre_defrost_correlation_seconds: int | None = Field(default=None, ge=0)
    post_defrost_recovery_seconds: int | None = Field(default=None, ge=0)
    maximum_expected_room_temperature_c: float | None = None
    maximum_expected_evaporator_temperature_c: float | None = None
    recovery_target_temperature_c: float | None = None
    maximum_recovery_duration_seconds: int | None = Field(default=None, ge=0)
    expected_defrost_excursions_visible_in_incident_list: bool | None = None
    abnormal_defrost_creates_incident: bool | None = None
    manual_review_required_after_abnormal_defrost: bool | None = None
    assignments: list[EntityAssignmentIn] | None = None


class StorageUnitOut(StorageUnitBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    assignments: list[EntityAssignmentOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Monitoring profiles
# --------------------------------------------------------------------------- #


class MonitoringProfileBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    warning_margin_c: float = 0.0
    violation_delay_seconds: int = Field(default=900, ge=0)
    recovery_delay_seconds: int = Field(default=300, ge=0)
    offline_delay_seconds: int = Field(default=600, ge=0)
    plausible_min_c: float | None = None
    plausible_max_c: float | None = None
    defrost_grace_enabled: bool = False
    defrost_grace_seconds: int = Field(default=0, ge=0)
    chart_group: str | None = None
    report_enabled_by_default: bool = True


class MonitoringProfileCreate(MonitoringProfileBase):
    """Create a custom profile, optionally duplicating an existing one."""

    duplicate_of_id: int | None = None


class MonitoringProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    archived: bool | None = None
    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    warning_margin_c: float | None = None
    violation_delay_seconds: int | None = Field(default=None, ge=0)
    recovery_delay_seconds: int | None = Field(default=None, ge=0)
    offline_delay_seconds: int | None = Field(default=None, ge=0)
    plausible_min_c: float | None = None
    plausible_max_c: float | None = None
    defrost_grace_enabled: bool | None = None
    defrost_grace_seconds: int | None = Field(default=None, ge=0)
    chart_group: str | None = None
    report_enabled_by_default: bool | None = None


class MonitoringProfileOut(MonitoringProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str | None = None
    built_in: bool
    archived: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Incidents (Phase 4)
# --------------------------------------------------------------------------- #


class IncidentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    kind: str
    from_state: str | None = None
    to_state: str | None = None
    value_c: float | None = None
    user: str | None = None
    detail: str | None = None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    storage_unit_id: int | None
    type: str
    state: str
    opened_at: datetime
    confirmed_at: datetime | None = None
    recovering_at: datetime | None = None
    closed_at: datetime | None = None
    limit_value_c: float | None = None
    extreme_value_c: float | None = None
    extreme_at: datetime | None = None
    defrost_overlap: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    cause: str | None = None
    corrective_action: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentOut):
    storage_unit_name: str | None = None
    events: list[IncidentEventOut] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    acknowledge: bool | None = None
    cause: str | None = None
    corrective_action: str | None = None
    note: str | None = None


class AppSettingsOut(BaseModel):
    timezone: str
    timezone_abbreviation: str
    timezone_offset: str
    timezone_label: str
    heartbeat_interval_seconds: int
    min_temp_delta_c: float
    retention_raw_days: int
    retention_agg15_days: int
    retention_agg_hourly_days: int
    storage_budget_bytes: int
    warning_pct: int
    critical_pct: int
    emergency_pct: int


class AppSettingsUpdate(BaseModel):
    timezone: str | None = None
    heartbeat_interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    min_temp_delta_c: float | None = Field(default=None, ge=0, le=50)
    retention_raw_days: int | None = Field(default=None, ge=1)
    retention_agg15_days: int | None = Field(default=None, ge=1)
    retention_agg_hourly_days: int | None = Field(default=None, ge=1)
    storage_budget_bytes: int | None = Field(default=None, ge=104857600)  # >= 100 MB
    warning_pct: int | None = Field(default=None, ge=1, le=100)
    critical_pct: int | None = Field(default=None, ge=1, le=100)
    emergency_pct: int | None = Field(default=None, ge=1, le=100)


class StorageCategory(BaseModel):
    name: str
    bytes: int


class MaintenanceStatus(BaseModel):
    last_run: datetime | None = None
    next_run: datetime | None = None
    last_result: str | None = None
    database_bytes: int
    wal_bytes: int
    reports_bytes: int
    uploads_bytes: int
    logs_bytes: int
    app_total_bytes: int
    free_bytes: int
    free_percent: float
    budget_bytes: int
    budget_used_percent: float
    level: str  # ok | warning | critical | emergency
    categories: list[StorageCategory] = Field(default_factory=list)


class HistoryPoint(BaseModel):
    t: datetime
    # Null value = gap (unavailable / missing / no valid data in the bucket).
    v: float | None = None
    vmin: float | None = None
    vmax: float | None = None
    q: str | None = None


class HistoryResponse(BaseModel):
    storage_unit_id: int
    role: EntityRole
    entity_id: str | None = None
    unit: str = "°C"
    from_ts: datetime
    to_ts: datetime
    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    sample_count: int
    downsampled: bool
    bucket_seconds: int | None = None
    points: list[HistoryPoint] = Field(default_factory=list)
    # Range stats over valid samples only (None when no valid data).
    min_c: float | None = None
    max_c: float | None = None
    avg_c: float | None = None
    coverage_ratio: float | None = None


# --------------------------------------------------------------------------- #
# Operational dashboard (Phase 3B)
# --------------------------------------------------------------------------- #


class DashboardRoleValue(BaseModel):
    role: EntityRole
    entity_id: str
    exists: bool
    available: bool
    quality: str
    numeric_c: float | None = None  # normalized Celsius (numeric roles)
    raw: str | None = None
    unit: str | None = None
    bool_value: bool | None = None  # operational on/off (state roles)


class DashboardSpark(BaseModel):
    t: datetime
    v: float | None = None


class DashboardIncident(BaseModel):
    id: int
    type: str
    state: str
    opened_at: datetime
    confirmed_at: datetime | None = None
    extreme_value_c: float | None = None
    defrost_overlap: bool = False
    acknowledged: bool = False
    documented: bool = False


class DashboardDefrost(BaseModel):
    """Current open defrost cycle (active or recovering) for a unit."""

    id: int
    status: str  # active | recovering
    started_at: datetime
    recovery_started_at: datetime | None = None
    peak_room_temperature_c: float | None = None
    peak_evaporator_temperature_c: float | None = None
    max_expected_duration_seconds: int
    max_recovery_seconds: int
    recovery_target_c: float | None = None


class DefrostCycleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    storage_unit_id: int
    started_at: datetime
    ended_at: datetime | None = None
    recovery_started_at: datetime | None = None
    recovered_at: datetime | None = None
    initial_room_temperature_c: float | None = None
    peak_room_temperature_c: float | None = None
    initial_evaporator_temperature_c: float | None = None
    peak_evaporator_temperature_c: float | None = None
    status: str
    classification: str | None = None
    triggering_rule: str | None = None


class DashboardUnit(BaseModel):
    id: int
    name: str
    short_report_name: str | None = None
    unit_type: StorageUnitType
    profile_name: str | None = None
    lower_limit_c: float | None = None
    upper_limit_c: float | None = None
    warning_margin_c: float = 0.0
    setpoint_c: float | None = None

    # normal | near_limit | outside_range | unavailable | stale | disconnected |
    # configuration_error
    status: str
    room: DashboardRoleValue | None = None
    last_update: datetime | None = None
    roles: list[DashboardRoleValue] = Field(default_factory=list)
    spark: list[DashboardSpark] = Field(default_factory=list)
    active_incidents: list[DashboardIncident] = Field(default_factory=list)
    defrost: DashboardDefrost | None = None


class DashboardSummary(BaseModel):
    total: int = 0
    normal: int = 0
    near_limit: int = 0
    outside_range: int = 0
    unavailable: int = 0
    stale: int = 0
    disconnected: int = 0
    configuration_error: int = 0
    open_incidents: int = 0
    unacknowledged_incidents: int = 0
    undocumented_incidents: int = 0


class DashboardResponse(BaseModel):
    connection: ConnectionStatus
    summary: DashboardSummary
    units: list[DashboardUnit] = Field(default_factory=list)
    last_sample_at: datetime | None = None
    timezone: str = "UTC"
    generated_at: datetime


class AssignmentCurrentValue(BaseModel):
    """Live value for an assigned entity, enriched from the HA entity cache."""

    role: EntityRole
    entity_id: str
    exists: bool
    available: bool
    state: str | None = None
    unit_of_measurement: str | None = None
    friendly_name: str | None = None
    warning: str | None = None


# --------------------------------------------------------------------------- #
# Defrost learning (Phase 4.6)
# --------------------------------------------------------------------------- #


class LearnedModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    status: str
    confidence: str
    confidence_score: float
    valid_cycle_count: int
    window_start: datetime | None = None
    window_end: datetime | None = None
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
    safety_margin_c: float = 2.0
    drift_warning: bool = False
    drift_detail: str | None = None
    generated_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None


class DefrostLearningStatus(BaseModel):
    """Diagnostic view of a unit's defrost learning state."""

    storage_unit_id: int
    enabled: bool
    has_defrost_entity: bool
    # disabled | no_entity | observing | suggestion_ready | approved
    state: str
    valid_cycle_count: int = 0
    min_cycles: int = 10
    confidence: str = "insufficient"
    confidence_score: float = 0.0
    outlier_count: int = 0
    outliers: list[str] = Field(default_factory=list)
    drift_warning: bool = False
    drift_detail: str | None = None
    suggestion: LearnedModelOut | None = None
    approved: LearnedModelOut | None = None
    recent_cycles: list[DefrostCycleOut] = Field(default_factory=list)


class DefrostLearningApprove(BaseModel):
    """Optional human edits applied when approving a suggestion."""

    max_room_peak_c: float | None = None
    max_evaporator_peak_c: float | None = None
    max_defrost_seconds: int | None = Field(default=None, ge=0)
    max_recovery_seconds: int | None = Field(default=None, ge=0)
    safety_margin_c: float | None = Field(default=None, ge=0)
