"""defrost-aware settings + defrost_cycles (Phase 4 defrost)

Revision ID: 0004_defrost
Revises: 0003_incidents
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_defrost"
down_revision = "0003_incidents"
branch_labels = None
depends_on = None

_BOOL_COLS = [
    ("defrost_evaluation_enabled", sa.false()),
    ("expected_defrost_excursions_visible_in_incident_list", sa.false()),
    ("abnormal_defrost_creates_incident", sa.true()),
    ("manual_review_required_after_abnormal_defrost", sa.false()),
]
_INT_COLS = [
    ("maximum_expected_defrost_duration_seconds", "1800"),
    ("pre_defrost_correlation_seconds", "300"),
    ("post_defrost_recovery_seconds", "1800"),
    ("maximum_recovery_duration_seconds", "3600"),
]
_FLOAT_COLS = [
    "maximum_expected_room_temperature_c",
    "maximum_expected_evaporator_temperature_c",
    "recovery_target_temperature_c",
]


def upgrade() -> None:
    for name, default in _BOOL_COLS:
        op.add_column(
            "storage_units",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=default),
        )
    for name, default in _INT_COLS:
        op.add_column(
            "storage_units",
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )
    for name in _FLOAT_COLS:
        op.add_column("storage_units", sa.Column(name, sa.Float(), nullable=True))

    op.create_table(
        "defrost_cycles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=False),
        sa.Column("source_entity_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initial_room_temperature_c", sa.Float(), nullable=True),
        sa.Column("peak_room_temperature_c", sa.Float(), nullable=True),
        sa.Column("initial_evaporator_temperature_c", sa.Float(), nullable=True),
        sa.Column("peak_evaporator_temperature_c", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("classification", sa.String(length=40), nullable=True),
        sa.Column("triggering_rule", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_defrost_cycles_storage_unit_id", "defrost_cycles", ["storage_unit_id"])
    op.create_index(
        "ix_defrost_cycles_unit_status", "defrost_cycles", ["storage_unit_id", "status"]
    )
    op.create_index("ix_defrost_cycles_started_at", "defrost_cycles", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_defrost_cycles_started_at", table_name="defrost_cycles")
    op.drop_index("ix_defrost_cycles_unit_status", table_name="defrost_cycles")
    op.drop_index("ix_defrost_cycles_storage_unit_id", table_name="defrost_cycles")
    op.drop_table("defrost_cycles")
    for name in _FLOAT_COLS:
        op.drop_column("storage_units", name)
    for name, _ in _INT_COLS:
        op.drop_column("storage_units", name)
    for name, _ in _BOOL_COLS:
        op.drop_column("storage_units", name)
