"""sensor aggregates + maintenance runs (Phase 4.5)

Revision ID: 0005_aggregates_maintenance
Revises: 0004_defrost
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_aggregates_maintenance"
down_revision = "0004_defrost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensor_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=False),
        sa.Column("entity_assignment_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_c", sa.Float(), nullable=True),
        sa.Column("max_c", sa.Float(), nullable=True),
        sa.Column("avg_c", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["entity_assignment_id"], ["entity_assignments.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "entity_assignment_id", "tier", "bucket_start", name="uq_aggregate_bucket"
        ),
    )
    op.create_index(
        "ix_aggregates_unit_tier_bucket",
        "sensor_aggregates",
        ["storage_unit_id", "tier", "bucket_start"],
    )

    op.create_table(
        "maintenance_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aggregated_15min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aggregated_hourly", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aggregates_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wal_checkpointed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("integrity_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("app_total_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("maintenance_runs")
    op.drop_index("ix_aggregates_unit_tier_bucket", table_name="sensor_aggregates")
    op.drop_table("sensor_aggregates")
