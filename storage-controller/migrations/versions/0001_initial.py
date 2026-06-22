"""initial schema (Phase 1 + 2)

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-22

Creates application settings, storage units, role-based entity assignments and
the audit trail. Sample/incident/report tables are introduced by later phases.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "storage_units",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("short_report_name", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("unit_type", sa.String(length=40), nullable=False, server_default="custom"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lower_limit_c", sa.Float(), nullable=True),
        sa.Column("upper_limit_c", sa.Float(), nullable=True),
        sa.Column("warning_margin_c", sa.Float(), nullable=False, server_default="0"),
        sa.Column("violation_delay_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("recovery_delay_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("offline_delay_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column(
            "defrost_grace_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("defrost_grace_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plausible_min_c", sa.Float(), nullable=True),
        sa.Column("plausible_max_c", sa.Float(), nullable=True),
        sa.Column("chart_group", sa.String(length=60), nullable=True),
        sa.Column("report_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("applied_profile_key", sa.String(length=60), nullable=True),
        sa.Column("applied_profile_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "monitoring_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=60), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lower_limit_c", sa.Float(), nullable=True),
        sa.Column("upper_limit_c", sa.Float(), nullable=True),
        sa.Column("warning_margin_c", sa.Float(), nullable=False, server_default="0"),
        sa.Column("violation_delay_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("recovery_delay_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("offline_delay_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("plausible_min_c", sa.Float(), nullable=True),
        sa.Column("plausible_max_c", sa.Float(), nullable=True),
        sa.Column(
            "defrost_grace_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("defrost_grace_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chart_group", sa.String(length=60), nullable=True),
        sa.Column(
            "report_enabled_by_default", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_profile_key"),
    )

    op.create_table(
        "entity_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("invert_state", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("value_mapping_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("storage_unit_id", "role", name="uq_assignment_unit_role"),
    )
    op.create_index(
        "ix_entity_assignments_storage_unit_id",
        "entity_assignments",
        ["storage_unit_id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component", sa.String(length=60), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("user", sa.String(length=200), nullable=True),
        sa.Column("object_type", sa.String(length=60), nullable=True),
        sa.Column("object_id", sa.String(length=120), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(
        "ix_entity_assignments_storage_unit_id", table_name="entity_assignments"
    )
    op.drop_table("entity_assignments")
    op.drop_table("storage_units")
    op.drop_table("app_settings")
