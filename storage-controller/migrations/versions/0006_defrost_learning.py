"""defrost learned models + learning config (Phase 4.6)

Revision ID: 0006_defrost_learning
Revises: 0005_aggregates_maintenance
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_defrost_learning"
down_revision = "0005_aggregates_maintenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "storage_units",
        sa.Column(
            "defrost_learning_min_cycles",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
    )

    op.create_table(
        "defrost_learned_models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("storage_unit_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="suggested"),
        sa.Column(
            "confidence", sa.String(length=20), nullable=False, server_default="insufficient"
        ),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("valid_cycle_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("typical_defrost_seconds", sa.Integer(), nullable=True),
        sa.Column("max_defrost_seconds", sa.Integer(), nullable=True),
        sa.Column("typical_recovery_seconds", sa.Integer(), nullable=True),
        sa.Column("max_recovery_seconds", sa.Integer(), nullable=True),
        sa.Column("typical_room_peak_c", sa.Float(), nullable=True),
        sa.Column("max_room_peak_c", sa.Float(), nullable=True),
        sa.Column("typical_evaporator_peak_c", sa.Float(), nullable=True),
        sa.Column("max_evaporator_peak_c", sa.Float(), nullable=True),
        sa.Column("typical_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("room_peak_variation_c", sa.Float(), nullable=True),
        sa.Column("duration_variation_seconds", sa.Integer(), nullable=True),
        sa.Column("safety_margin_c", sa.Float(), nullable=False, server_default="2"),
        sa.Column("drift_warning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("drift_detail", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["storage_unit_id"], ["storage_units.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_defrost_models_unit_status",
        "defrost_learned_models",
        ["storage_unit_id", "status"],
    )
    op.create_index(
        "ix_defrost_learned_models_storage_unit_id",
        "defrost_learned_models",
        ["storage_unit_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_defrost_learned_models_storage_unit_id", table_name="defrost_learned_models"
    )
    op.drop_index("ix_defrost_models_unit_status", table_name="defrost_learned_models")
    op.drop_table("defrost_learned_models")
    op.drop_column("storage_units", "defrost_learning_min_cycles")
