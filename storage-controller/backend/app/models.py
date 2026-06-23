"""ORM models.

Phase 1 + 2 introduce application settings, storage units, role-based entity
assignments and an audit trail. Further tables (sensor_samples, incidents,
reports, schedules, …) are added in later phases as separate migrations; the
model is structured so they can be added without reshaping existing tables.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class EntityRole(str, enum.Enum):
    room_temperature = "room_temperature"
    evaporator_temperature = "evaporator_temperature"
    setpoint = "setpoint"
    hysteresis = "hysteresis"
    compressor = "compressor"
    fan = "fan"
    defrost = "defrost"
    light = "light"
    controller = "controller"
    door = "door"
    alarm = "alarm"


MANDATORY_ROLES = {EntityRole.room_temperature}

# Roles whose value is recorded as a numeric temperature/measurement sample.
NUMERIC_ROLES = {
    EntityRole.room_temperature,
    EntityRole.evaporator_temperature,
    EntityRole.setpoint,
    EntityRole.hysteresis,
}


class Quality(str, enum.Enum):
    valid = "valid"
    unknown = "unknown"
    unavailable = "unavailable"
    invalid = "invalid"
    implausible = "implausible"
    stale = "stale"
    missing = "missing"


class SampleSource(str, enum.Enum):
    live_websocket = "live_websocket"
    reconcile = "reconcile"
    heartbeat = "heartbeat"
    home_assistant_history_import = "home_assistant_history_import"


class IncidentType(str, enum.Enum):
    temperature_high = "temperature_high"
    temperature_low = "temperature_low"
    sensor_unavailable = "sensor_unavailable"
    sensor_stale = "sensor_stale"
    sensor_invalid = "sensor_invalid"
    home_assistant_disconnected = "home_assistant_disconnected"
    abnormal_defrost = "abnormal_defrost"
    recovery_timeout = "recovery_timeout"


class DefrostStatus(str, enum.Enum):
    active = "active"
    recovering = "recovering"
    completed = "completed"
    abnormal = "abnormal"
    incomplete = "incomplete"


class DefrostClassification(str, enum.Enum):
    expected_defrost = "expected_defrost"
    expected_defrost_excursion = "expected_defrost_excursion"
    abnormal_defrost = "abnormal_defrost"
    recovery_timeout = "recovery_timeout"


# Defrost cycle statuses that are still ongoing.
OPEN_DEFROST_STATUSES = {DefrostStatus.active, DefrostStatus.recovering}


class IncidentState(str, enum.Enum):
    pending_violation = "pending_violation"
    active_violation = "active_violation"
    recovering = "recovering"
    closed = "closed"


# Incident states that are still ongoing (not closed).
OPEN_INCIDENT_STATES = {
    IncidentState.pending_violation,
    IncidentState.active_violation,
    IncidentState.recovering,
}


class StorageUnitType(str, enum.Enum):
    """Physical installation / operational purpose of a storage unit.

    The type may influence suggestions (icon, default profile, chart grouping)
    but must never silently enforce temperature limits.
    """

    day_cold_room = "day_cold_room"
    freezer_room = "freezer_room"
    vegetable_cold_room = "vegetable_cold_room"
    beverage_cold_room = "beverage_cold_room"
    refrigerator = "refrigerator"
    freezer = "freezer"
    refrigerated_counter = "refrigerated_counter"
    custom = "custom"


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StorageUnit(Base):
    __tablename__ = "storage_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_report_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit_type: Mapped[str] = mapped_column(
        String(40), default=StorageUnitType.custom.value, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    lower_limit_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_limit_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    warning_margin_c: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    violation_delay_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    recovery_delay_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    offline_delay_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    defrost_grace_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    defrost_grace_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    plausible_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    plausible_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    chart_group: Mapped[str | None] = mapped_column(String(60), nullable=True)
    report_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Snapshot of the monitoring profile that was applied (contextual only — the
    # effective values above are what actually governs monitoring and reports).
    applied_profile_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    applied_profile_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Defrost-aware evaluation (Phase 4). Suggested by profiles, editable per unit.
    defrost_evaluation_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    maximum_expected_defrost_duration_seconds: Mapped[int] = mapped_column(
        Integer, default=1800, nullable=False
    )
    pre_defrost_correlation_seconds: Mapped[int] = mapped_column(
        Integer, default=300, nullable=False
    )
    post_defrost_recovery_seconds: Mapped[int] = mapped_column(
        Integer, default=1800, nullable=False
    )
    maximum_expected_room_temperature_c: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    maximum_expected_evaporator_temperature_c: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    recovery_target_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_recovery_duration_seconds: Mapped[int] = mapped_column(
        Integer, default=3600, nullable=False
    )
    expected_defrost_excursions_visible_in_incident_list: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    abnormal_defrost_creates_incident: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    manual_review_required_after_abnormal_defrost: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    assignments: Mapped[list[EntityAssignment]] = relationship(
        back_populates="storage_unit",
        cascade="all, delete-orphan",
        order_by="EntityAssignment.role",
    )


class EntityAssignment(Base):
    __tablename__ = "entity_assignments"
    __table_args__ = (
        UniqueConstraint("storage_unit_id", "role", name="uq_assignment_unit_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    invert_state: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    value_mapping_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    storage_unit: Mapped[StorageUnit] = relationship(back_populates="assignments")


class MonitoringProfile(Base):
    """Editable preset of suggested monitoring rules.

    Built-in profiles are read-only templates; users may duplicate and edit a
    copy. Applying a profile copies its current values into a storage unit, so a
    later profile edit never silently changes existing units.
    """

    __tablename__ = "monitoring_profiles"
    __table_args__ = (UniqueConstraint("key", name="uq_profile_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    built_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lower_limit_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_limit_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    warning_margin_c: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    violation_delay_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    recovery_delay_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    offline_delay_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)

    plausible_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    plausible_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    defrost_grace_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    defrost_grace_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    chart_group: Mapped[str | None] = mapped_column(String(60), nullable=True)
    report_enabled_by_default: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SensorSample(Base):
    """A numeric measurement sample (temperature, setpoint, …).

    Raw, original-unit and normalized-Celsius values are all retained. Unknown /
    unavailable / invalid readings are stored with a quality flag and NULL
    numeric values — never coerced to zero.
    """

    __tablename__ = "sensor_samples"
    __table_args__ = (
        UniqueConstraint(
            "entity_assignment_id", "event_timestamp", name="uq_sensor_sample_assignment_ts"
        ),
        Index("ix_sensor_samples_unit_ts", "storage_unit_id", "event_timestamp"),
        Index("ix_sensor_samples_assignment_ts", "entity_assignment_id", "event_timestamp"),
        Index("ix_sensor_samples_role_ts", "role", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False
    )
    entity_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("entity_assignments.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)

    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    raw_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_value_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)

    quality: Mapped[str] = mapped_column(String(20), nullable=False, default=Quality.valid.value)
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default=SampleSource.live_websocket.value
    )
    source_context_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class StateSample(Base):
    """An operational on/off (or textual) state sample for non-numeric roles
    (compressor, fan, defrost, light, controller, door, alarm) and availability
    transitions."""

    __tablename__ = "state_samples"
    __table_args__ = (
        UniqueConstraint(
            "entity_assignment_id", "event_timestamp", name="uq_state_sample_assignment_ts"
        ),
        Index("ix_state_samples_unit_role_ts", "storage_unit_id", "role", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False
    )
    entity_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("entity_assignments.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)

    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    raw_state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    quality: Mapped[str] = mapped_column(String(20), nullable=False, default=Quality.valid.value)
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default=SampleSource.live_websocket.value
    )
    source_context_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Incident(Base):
    """A detected deviation/condition with a lifecycle.

    The original threshold-crossing time (``opened_at``) is preserved across
    state transitions. ``confirmed_at`` marks when it became an active violation
    after the configured delay. Extremes are tracked continuously.
    """

    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_unit_state", "storage_unit_id", "state"),
        Index("ix_incidents_opened_at", "opened_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovering_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    limit_value_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    extreme_value_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    extreme_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    defrost_overlap: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Documentation (HACCP)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    events: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentEvent.timestamp",
    )


class IncidentEvent(Base):
    """Lifecycle/audit entry for an incident (state transitions, documentation)."""

    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident", "incident_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # transition|extreme|doc
    from_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    value_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    user: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="events")


class DefrostCycle(Base):
    """A persisted defrost cycle (operational event, not a critical incident).

    Captures start/end, snapshots and peaks of room/evaporator temperature, the
    recovery phase, and a status/classification. Normal cycles stay operational;
    only abnormal cycles or failed recovery become incidents.
    """

    __tablename__ = "defrost_cycles"
    __table_args__ = (
        Index("ix_defrost_cycles_unit_status", "storage_unit_id", "status"),
        Index("ix_defrost_cycles_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    initial_room_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_room_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_evaporator_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_evaporator_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    triggering_rule: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SensorAggregate(Base):
    """Down-sampled temperature aggregates (15-minute and hourly tiers).

    Computed from raw sensor_samples before eligible raw rows may be deleted, so
    long-term trends and data-quality coverage survive retention cleanup.
    """

    __tablename__ = "sensor_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "entity_assignment_id", "tier", "bucket_start", name="uq_aggregate_bucket"
        ),
        Index("ix_aggregates_unit_tier_bucket", "storage_unit_id", "tier", "bucket_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False
    )
    entity_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("entity_assignments.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    tier: Mapped[str] = mapped_column(String(10), nullable=False)  # "15min" | "hourly"
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaintenanceRun(Base):
    """Result of a bounded daily maintenance run."""

    __tablename__ = "maintenance_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aggregated_15min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aggregated_hourly: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aggregates_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wal_checkpointed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    integrity_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    app_total_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    component: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    user: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
