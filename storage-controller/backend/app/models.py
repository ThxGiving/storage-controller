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
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator):
    """DateTime column that guarantees UTC-aware values across the DB boundary.

    This is the single, canonical place the whole backend handles stored times.
    SQLite (via SQLAlchemy's ``DateTime``) keeps datetimes tz-naive, so a UTC
    instant read back looks naive and serializes to JSON without an offset — the
    frontend then misreads stored UTC as local time (the 2h summer offset bug).

    The rule enforced here:
      * on write — a naive value is assumed to already be UTC; an aware value is
        converted to UTC; either way it is stored naive-UTC (identical on-disk
        format to existing rows, so no data migration is needed);
      * on read — the value is always returned tz-aware in UTC.

    Because this holds for every ORM datetime, endpoints must NOT re-stamp times
    sourced from the database. The only remaining ``_as_utc``-style helpers are
    for non-ORM sources (in-memory diagnostics/HA state) that never pass here.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )


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
    door_open = "door_open"
    controller_alarm = "controller_alarm"


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

# Cycle outcomes that count as a complete, trustworthy observation for learning.
LEARNABLE_DEFROST_CLASSIFICATIONS = {
    DefrostClassification.expected_defrost,
    DefrostClassification.expected_defrost_excursion,
}


class DefrostModelStatus(str, enum.Enum):
    suggested = "suggested"
    approved = "approved"
    superseded = "superseded"
    rejected = "rejected"


class DefrostConfidence(str, enum.Enum):
    insufficient = "insufficient"
    preliminary = "preliminary"
    high = "high"


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
        UtcDateTime, default=utcnow, onupdate=utcnow
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
    # Defrost learning (Phase 4.6). Minimum complete cycles before a learned
    # operational profile may be suggested for approval.
    defrost_learning_min_cycles: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
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

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
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

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
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

    event_timestamp: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    received_timestamp: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
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

    event_timestamp: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    received_timestamp: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
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

    opened_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    recovering_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    limit_value_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    extreme_value_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    extreme_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    defrost_overlap: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Documentation (HACCP)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
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
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
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

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    recovery_started_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    recovered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    initial_room_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_room_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_evaporator_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_evaporator_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    triggering_rule: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # True when the cycle start was reconstructed on (re)connect rather than
    # directly observed — its timestamps are approximate, not precise.
    reconstructed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
    )


class DefrostLearnedModel(Base):
    """A learned operational profile for a unit's defrost behaviour.

    Operational characteristics (typical/maximum durations, peak temperatures,
    recovery time, frequency) are LEARNED from observed complete cycles. Safety
    temperature limits are NEVER learned or changed here. A ``suggested`` model
    must be explicitly approved before the incident engine may use it to suppress
    or reclassify excursions; an ``approved`` model is the active envelope.
    """

    __tablename__ = "defrost_learned_models"
    __table_args__ = (
        Index("ix_defrost_models_unit_status", "storage_unit_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=DefrostModelStatus.suggested.value, nullable=False
    )
    confidence: Mapped[str] = mapped_column(
        String(20), default=DefrostConfidence.insufficient.value, nullable=False
    )
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    valid_cycle_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    window_start: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    window_end: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )

    # Robust statistics (median for typical, p95 for maximum).
    typical_defrost_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_defrost_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    typical_recovery_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_recovery_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    typical_room_peak_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_room_peak_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    typical_evaporator_peak_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_evaporator_peak_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    typical_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_peak_variation_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_variation_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    safety_margin_c: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)

    drift_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    drift_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
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
    bucket_start: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    # "computed" (from raw samples) or "ha_statistics" (imported long-term stats).
    source: Mapped[str] = mapped_column(String(20), default="computed", nullable=False)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class MaintenanceRun(Base):
    """Result of a bounded daily maintenance run."""

    __tablename__ = "maintenance_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    aggregated_15min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aggregated_hourly: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aggregates_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wal_checkpointed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    integrity_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    app_total_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class HistoryImportStatus(str, enum.Enum):
    importing = "importing"
    completed = "completed"
    partial = "partial"  # some chunks done, some failed (or only hourly statistics)
    failed = "failed"
    cancelled = "cancelled"
    no_history = "no_history"


class HistoryRange(str, enum.Enum):
    all = "all"
    current_month = "current_month"
    last_30_days = "last_30_days"
    last_90_days = "last_90_days"


class HistoryImport(Base):
    """Tracks an asynchronous Home Assistant history import for a storage unit's
    primary temperature sensor. Imported samples are marked with their source and
    resolution and never trigger live incident workflows."""

    __tablename__ = "history_imports"
    __table_args__ = (Index("ix_history_imports_unit", "storage_unit_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    storage_unit_id: Mapped[int] = mapped_column(
        ForeignKey("storage_units.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_range: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=HistoryImportStatus.importing.value, nullable=False
    )
    # Raw recorder coverage actually imported.
    raw_from: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    raw_to: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    raw_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Long-term hourly statistics coverage actually imported.
    stats_from: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    stats_to: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    stats_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-chunk progress for resumable imports: JSON list of {s, e, st} where
    # st is pending|done|failed. Lets an interrupted/failed import resume without
    # restarting completed windows, and the UI show which date range failed.
    chunks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ReportStatus(str, enum.Enum):
    queued = "queued"
    generating = "generating"
    completed = "completed"
    failed = "failed"


class ReportDetailLevel(str, enum.Enum):
    compact = "compact"
    standard = "standard"
    detailed = "detailed"


# Bump when the immutable report-model structure changes.
REPORT_MODEL_VERSION = "2"


class ReportBrandingSettings(Base):
    """Editable report branding. A snapshot is frozen into each report at
    generation, so later edits never change already-generated reports."""

    __tablename__ = "report_branding_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    organization_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    site_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    report_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subtitle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    accent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclaimer: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_labels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    default_timezone: Mapped[str] = mapped_column(
        String(64), default="Europe/Berlin", nullable=False
    )
    default_detail_level: Mapped[str] = mapped_column(
        String(20), default=ReportDetailLevel.standard.value, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
    )


class Report(Base):
    """An immutable generated report. After ``completed`` the snapshot JSON,
    branding snapshot and checksum are frozen and never recomputed."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("uuid", name="uq_report_uuid"),
        Index("ix_reports_period", "period_year", "period_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ReportStatus.queued.value, nullable=False
    )

    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start_utc: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    period_end_utc: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin", nullable=False)
    detail_level: Mapped[str] = mapped_column(
        String(20), default=ReportDetailLevel.standard.value, nullable=False
    )
    storage_unit_ids_json: Mapped[str] = mapped_column(Text, nullable=False)

    report_model_version: Mapped[str] = mapped_column(String(10), nullable=False)
    model_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    branding_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    pdf_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    csv_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    json_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    generated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, index=True
    )
    component: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    user: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------- #
# Phase 6 — report scheduling and email delivery
# --------------------------------------------------------------------------- #


class SmtpSecurityMode(str, enum.Enum):
    starttls = "starttls"  # plain connect, upgrade to TLS (typically 587)
    implicit_tls = "implicit_tls"  # TLS from the start (typically 465)
    plain = "plain"  # unencrypted — opt-in only, trusted local relays


class ScheduleRunState(str, enum.Enum):
    pending = "pending"
    generating = "generating"
    generated = "generated"
    sending = "sending"
    completed = "completed"
    partially_failed = "partially_failed"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class DeliveryState(str, enum.Enum):
    pending = "pending"
    sending = "sending"
    completed = "completed"
    partially_failed = "partially_failed"
    failed = "failed"
    cancelled = "cancelled"


class DeliveryFailureCategory(str, enum.Enum):
    connection = "connection"
    tls = "tls"
    authentication = "authentication"
    recipient_rejected = "recipient_rejected"
    message_too_large = "message_too_large"
    temporary = "temporary_smtp"
    permanent = "permanent_smtp"
    attachment_missing = "attachment_missing"
    report_generation = "report_generation"
    internal = "internal"


class SmtpSettings(Base):
    """Single-row outbound SMTP configuration. The password is app-private: it is
    never returned by the API, logged, or placed in diagnostics."""

    __tablename__ = "smtp_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    security_mode: Mapped[str] = mapped_column(
        String(20), default=SmtpSecurityMode.starttls.value, nullable=False
    )
    auth_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Secret; never serialised back out. Empty string distinct from NULL=unset.
    password_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connection_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    verify_certificates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_insecure_plain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_to_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_cc_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_bcc_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_attachment_bytes: Mapped[int] = mapped_column(
        Integer, default=20 * 1024 * 1024, nullable=False
    )
    site_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # sanitized
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class ReportSchedule(Base):
    """An automated schedule that generates an existing report type and emails it."""

    __tablename__ = "report_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    period_rule: Mapped[str] = mapped_column(
        String(30), default="previous_month", nullable=False
    )
    storage_unit_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    locale: Mapped[str] = mapped_column(String(10), default="de", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin", nullable=False)
    detail_level: Mapped[str] = mapped_column(String(20), default="standard", nullable=False)
    recipients_to_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recipients_cc_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recipients_bcc_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    attachment_formats_json: Mapped[str] = mapped_column(
        Text, nullable=False, default='["pdf"]'
    )
    run_day: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 1 = 1st of month
    run_time: Mapped[str] = mapped_column(String(5), default="06:00", nullable=False)  # HH:MM
    catch_up_mode: Mapped[str] = mapped_column(
        String(10), default="one", nullable=False
    )  # one | none
    next_run_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_run_utc: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class ScheduleRun(Base):
    """A persistent execution record for one (schedule, reporting period). The
    UNIQUE(schedule, period) constraint guarantees no duplicate run per period."""

    __tablename__ = "schedule_runs"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "period_year", "period_month", name="uq_schedule_run_period"
        ),
        Index("ix_schedule_runs_schedule", "schedule_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("report_schedules.id", ondelete="CASCADE"), nullable=False
    )
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_for_utc: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), default=ScheduleRunState.pending.value, nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )
    report_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # sanitized
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Execution lock (single-process; stale locks recovered after a timeout).
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class EmailDelivery(Base):
    """A logical email delivery for a schedule run, idempotent on ``delivery_key``
    (schedule + report + period + recipient set + attachment set). Retries continue
    the same record; a manual resend is an explicit new, audited delivery."""

    __tablename__ = "email_deliveries"
    __table_args__ = (
        UniqueConstraint("delivery_key", name="uq_email_delivery_key"),
        Index("ix_email_deliveries_run", "schedule_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_key: Mapped[str] = mapped_column(String(80), nullable=False)
    schedule_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"), nullable=True
    )
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )
    recipients_to_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recipients_cc_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recipients_bcc_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    attachment_set_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(
        String(20), default=DeliveryState.pending.value, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_utc: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    last_error_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # sanitized
    per_recipient_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_manual_resend: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


# ── Phase 7: Backup jobs ───────────────────────────────────────────────────────


class BackupStatus(str, enum.Enum):
    completed = "completed"
    failed = "failed"


class BackupJob(Base):
    """Tracks every backup archive created by the application.

    Each row corresponds to one ZIP file on disk under ``/data/backups/``.
    Safety backups (auto-created before a restore) are also tracked here with
    ``is_safety_backup = True``.
    """

    __tablename__ = "backup_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=BackupStatus.completed.value, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    app_version: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    schema_revision: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_safety_backup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
