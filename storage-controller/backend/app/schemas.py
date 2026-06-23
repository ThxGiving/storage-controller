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


class AppSettingsOut(BaseModel):
    heartbeat_interval_seconds: int
    retention_raw_days: int
    retention_state_days: int


class AppSettingsUpdate(BaseModel):
    heartbeat_interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    retention_raw_days: int | None = Field(default=None, ge=1)
    retention_state_days: int | None = Field(default=None, ge=1)


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


class DashboardSummary(BaseModel):
    total: int = 0
    normal: int = 0
    near_limit: int = 0
    outside_range: int = 0
    unavailable: int = 0
    stale: int = 0
    disconnected: int = 0
    configuration_error: int = 0


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
