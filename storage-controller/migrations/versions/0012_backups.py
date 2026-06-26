"""backup jobs table (Phase 7)

Revision ID: 0012_backups
Revises: 0011_scheduling_email
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_backups"
down_revision = "0011_scheduling_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("format_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("app_version", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("schema_revision", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "is_safety_backup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_backup_jobs_created", "backup_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_jobs_created", table_name="backup_jobs")
    op.drop_table("backup_jobs")
