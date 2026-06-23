"""incidents & incident_events (Phase 4)

Revision ID: 0003_incidents
Revises: 0002_sensor_samples
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_incidents"
down_revision = "0002_sensor_samples"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovering_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limit_value_c", sa.Float(), nullable=True),
        sa.Column("extreme_value_c", sa.Float(), nullable=True),
        sa.Column("extreme_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("defrost_overlap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=200), nullable=True),
        sa.Column("cause", sa.Text(), nullable=True),
        sa.Column("corrective_action", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_incidents_storage_unit_id", "incidents", ["storage_unit_id"])
    op.create_index("ix_incidents_unit_state", "incidents", ["storage_unit_id", "state"])
    op.create_index("ix_incidents_opened_at", "incidents", ["opened_at"])

    op.create_table(
        "incident_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("from_state", sa.String(length=30), nullable=True),
        sa.Column("to_state", sa.String(length=30), nullable=True),
        sa.Column("value_c", sa.Float(), nullable=True),
        sa.Column("user", sa.String(length=200), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_incident_events_incident", "incident_events", ["incident_id", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_incident_events_incident", table_name="incident_events")
    op.drop_table("incident_events")
    op.drop_index("ix_incidents_opened_at", table_name="incidents")
    op.drop_index("ix_incidents_unit_state", table_name="incidents")
    op.drop_index("ix_incidents_storage_unit_id", table_name="incidents")
    op.drop_table("incidents")
