"""report scheduling + email delivery (Phase 6)

Revision ID: 0011_scheduling_email
Revises: 0010_history_chunks
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_scheduling_email"
down_revision = "0010_history_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smtp_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("security_mode", sa.String(length=20), nullable=False, server_default="starttls"),
        sa.Column("auth_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password_secret", sa.Text(), nullable=True),
        sa.Column("sender_name", sa.String(length=200), nullable=True),
        sa.Column("sender_email", sa.String(length=255), nullable=True),
        sa.Column("reply_to", sa.String(length=255), nullable=True),
        sa.Column("connection_timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("verify_certificates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_insecure_plain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_to_json", sa.Text(), nullable=True),
        sa.Column("default_cc_json", sa.Text(), nullable=True),
        sa.Column("default_bcc_json", sa.Text(), nullable=True),
        sa.Column("max_attachment_bytes", sa.Integer(), nullable=False, server_default="20971520"),
        sa.Column("site_name", sa.String(length=200), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "report_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("report_type", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("period_rule", sa.String(length=30), nullable=False, server_default="previous_month"),
        sa.Column("storage_unit_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("locale", sa.String(length=10), nullable=False, server_default="de"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/Berlin"),
        sa.Column("detail_level", sa.String(length=20), nullable=False, server_default="standard"),
        sa.Column("recipients_to_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recipients_cc_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recipients_bcc_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("attachment_formats_json", sa.Text(), nullable=False, server_default='["pdf"]'),
        sa.Column("run_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("run_time", sa.String(length=5), nullable=False, server_default="06:00"),
        sa.Column("catch_up_mode", sa.String(length=10), nullable=False, server_default="one"),
        sa.Column("next_run_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(length=30), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("scheduled_for_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("report_status", sa.String(length=20), nullable=True),
        sa.Column("generation_error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_by", sa.String(length=80), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["schedule_id"], ["report_schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("schedule_id", "period_year", "period_month", name="uq_schedule_run_period"),
    )
    op.create_index("ix_schedule_runs_schedule", "schedule_runs", ["schedule_id"])

    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("delivery_key", sa.String(length=80), nullable=False),
        sa.Column("schedule_run_id", sa.Integer(), nullable=True),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("recipients_to_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recipients_cc_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recipients_bcc_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("attachment_set_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=30), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("per_recipient_json", sa.Text(), nullable=True),
        sa.Column("is_manual_resend", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["schedule_run_id"], ["schedule_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("delivery_key", name="uq_email_delivery_key"),
    )
    op.create_index("ix_email_deliveries_run", "email_deliveries", ["schedule_run_id"])


def downgrade() -> None:
    op.drop_index("ix_email_deliveries_run", table_name="email_deliveries")
    op.drop_table("email_deliveries")
    op.drop_index("ix_schedule_runs_schedule", table_name="schedule_runs")
    op.drop_table("schedule_runs")
    op.drop_table("report_schedules")
    op.drop_table("smtp_settings")
