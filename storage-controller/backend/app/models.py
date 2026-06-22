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
