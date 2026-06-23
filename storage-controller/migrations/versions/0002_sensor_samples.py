"""sensor & state samples (Phase 3)

Revision ID: 0002_sensor_samples
Revises: 0001_initial
Create Date: 2026-06-23

Independent recording of temperature/numeric samples and operational state
samples for entities assigned to storage units. A UNIQUE(entity_assignment_id,
event_timestamp) constraint enforces deduplication across reconnects/restarts.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_sensor_samples"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensor_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=False),
        sa.Column("entity_assignment_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_value", sa.String(length=255), nullable=True),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("normalized_value_c", sa.Float(), nullable=True),
        sa.Column("original_unit", sa.String(length=20), nullable=True),
        sa.Column("quality", sa.String(length=20), nullable=False, server_default="valid"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="live_websocket"),
        sa.Column("source_context_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["entity_assignment_id"], ["entity_assignments.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "entity_assignment_id", "event_timestamp", name="uq_sensor_sample_assignment_ts"
        ),
    )
    op.create_index(
        "ix_sensor_samples_unit_ts", "sensor_samples", ["storage_unit_id", "event_timestamp"]
    )
    op.create_index(
        "ix_sensor_samples_assignment_ts",
        "sensor_samples",
        ["entity_assignment_id", "event_timestamp"],
    )
    op.create_index("ix_sensor_samples_role_ts", "sensor_samples", ["role", "event_timestamp"])

    op.create_table(
        "state_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=False),
        sa.Column("entity_assignment_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_state", sa.String(length=255), nullable=True),
        sa.Column("normalized_bool", sa.Boolean(), nullable=True),
        sa.Column("quality", sa.String(length=20), nullable=False, server_default="valid"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="live_websocket"),
        sa.Column("source_context_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["entity_assignment_id"], ["entity_assignments.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "entity_assignment_id", "event_timestamp", name="uq_state_sample_assignment_ts"
        ),
    )
    op.create_index(
        "ix_state_samples_unit_role_ts",
        "state_samples",
        ["storage_unit_id", "role", "event_timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_state_samples_unit_role_ts", table_name="state_samples")
    op.drop_table("state_samples")
    op.drop_index("ix_sensor_samples_role_ts", table_name="sensor_samples")
    op.drop_index("ix_sensor_samples_assignment_ts", table_name="sensor_samples")
    op.drop_index("ix_sensor_samples_unit_ts", table_name="sensor_samples")
    op.drop_table("sensor_samples")
