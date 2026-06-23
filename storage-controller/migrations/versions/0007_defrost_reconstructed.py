"""defrost cycle reconstructed flag (Phase 4.7)

Revision ID: 0007_defrost_reconstructed
Revises: 0006_defrost_learning
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_defrost_reconstructed"
down_revision = "0006_defrost_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "defrost_cycles",
        sa.Column("reconstructed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("defrost_cycles", "reconstructed")
