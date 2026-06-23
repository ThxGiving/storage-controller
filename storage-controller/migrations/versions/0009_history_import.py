"""history imports + aggregate source (Phase 5.1)

Revision ID: 0009_history_import
Revises: 0008_reports
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_history_import"
down_revision = "0008_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sensor_aggregates",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="computed"),
    )
    op.create_table(
        "history_imports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("requested_range", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="importing"),
        sa.Column("raw_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stats_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_history_imports_unit", "history_imports", ["storage_unit_id"])


def downgrade() -> None:
    op.drop_index("ix_history_imports_unit", table_name="history_imports")
    op.drop_table("history_imports")
    op.drop_column("sensor_aggregates", "source")
