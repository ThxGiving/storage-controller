"""incident Home Assistant event outbox markers (0.9.12)

Revision ID: 0013_ha_incident_events
Revises: 0012_backups
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_ha_incident_events"
down_revision = "0012_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incidents", sa.Column("ha_notified_active_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "incidents", sa.Column("ha_notified_closed_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Incidents that existed before this feature must not flood Home Assistant
    # with historic alerts on first start: mark their transitions as delivered.
    op.execute(
        "UPDATE incidents SET ha_notified_active_at = confirmed_at "
        "WHERE confirmed_at IS NOT NULL"
    )
    op.execute(
        "UPDATE incidents SET ha_notified_closed_at = closed_at "
        "WHERE closed_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("incidents", "ha_notified_closed_at")
    op.drop_column("incidents", "ha_notified_active_at")
