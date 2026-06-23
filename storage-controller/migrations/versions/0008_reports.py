"""reports + report branding (Phase 5)

Revision ID: 0008_reports
Revises: 0007_defrost_reconstructed
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_reports"
down_revision = "0007_defrost_reconstructed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_branding_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_name", sa.String(length=200), nullable=True),
        sa.Column("site_name", sa.String(length=200), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("contact", sa.Text(), nullable=True),
        sa.Column("logo_filename", sa.String(length=255), nullable=True),
        sa.Column("report_title", sa.String(length=200), nullable=True),
        sa.Column("subtitle", sa.String(length=200), nullable=True),
        sa.Column("accent", sa.String(length=20), nullable=True),
        sa.Column("footer_text", sa.Text(), nullable=True),
        sa.Column("disclaimer", sa.Text(), nullable=True),
        sa.Column("signature_labels_json", sa.Text(), nullable=True),
        sa.Column("default_locale", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column(
            "default_timezone", sa.String(length=64), nullable=False, server_default="Europe/Berlin"
        ),
        sa.Column(
            "default_detail_level", sa.String(length=20), nullable=False, server_default="standard"
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("period_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False, server_default="en"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Berlin"),
        sa.Column("detail_level", sa.String(length=20), nullable=False, server_default="standard"),
        sa.Column("storage_unit_ids_json", sa.Text(), nullable=False),
        sa.Column("report_model_version", sa.String(length=10), nullable=False),
        sa.Column("model_json", sa.Text(), nullable=True),
        sa.Column("branding_snapshot_json", sa.Text(), nullable=True),
        sa.Column("pdf_filename", sa.String(length=255), nullable=True),
        sa.Column("csv_filename", sa.String(length=255), nullable=True),
        sa.Column("json_filename", sa.String(length=255), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("failure_category", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("uuid", name="uq_report_uuid"),
    )
    op.create_index("ix_reports_period", "reports", ["period_year", "period_month"])


def downgrade() -> None:
    op.drop_index("ix_reports_period", table_name="reports")
    op.drop_table("reports")
    op.drop_table("report_branding_settings")
