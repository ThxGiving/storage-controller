"""resumable history import: per-chunk progress (Phase 5.2)

Revision ID: 0010_history_chunks
Revises: 0009_history_import
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_history_chunks"
down_revision = "0009_history_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("history_imports", sa.Column("chunks_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("history_imports", "chunks_json")
