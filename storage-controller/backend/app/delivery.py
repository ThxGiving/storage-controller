"""Email delivery orchestration (Phase 6).

One logical ``EmailDelivery`` per (schedule, report, recipient set, attachment
set), idempotent on ``delivery_key``. A retry continues the same record; a manual
resend re-opens the same record (audited). Failures are classified; transient
ones retry on a bounded backoff, permanent ones stop. A generated report is never
lost because delivery failed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .mailer import RecipientSet, SmtpConfig, SmtpError, send_message
from .models import DeliveryFailureCategory, DeliveryState, EmailDelivery, Report
from .report_email import compose
from .smtp_store import MAX_ATTEMPTS, RETRY_SCHEDULE_SECONDS, delivery_key

log = logging.getLogger("delivery")

# Permanent failures never retry; transient ones back off on the retry schedule.
_PERMANENT = {
    DeliveryFailureCategory.authentication.value,
    DeliveryFailureCategory.recipient_rejected.value,
    DeliveryFailureCategory.message_too_large.value,
    DeliveryFailureCategory.attachment_missing.value,
    DeliveryFailureCategory.permanent.value,
    DeliveryFailureCategory.report_generation.value,
}


def _loads(raw: str | None) -> list[str]:
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


async def get_or_create_delivery(
    session: AsyncSession,
    *,
    report: Report,
    rcpts: RecipientSet,
    formats: list[str],
    schedule_id: int | None,
    schedule_run_id: int | None,
) -> EmailDelivery:
    key = delivery_key(
        schedule_id=schedule_id, report_uuid=report.uuid, rcpts=rcpts, formats=formats
    )
    existing = await session.scalar(
        select(EmailDelivery).where(EmailDelivery.delivery_key == key)
    )
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    d = EmailDelivery(
        delivery_key=key,
        schedule_run_id=schedule_run_id,
        report_id=report.id,
        recipients_to_json=json.dumps(rcpts.to),
        recipients_cc_json=json.dumps(rcpts.cc),
        recipients_bcc_json=json.dumps(rcpts.bcc),
        attachment_set_json=json.dumps(sorted(formats)),
        state=DeliveryState.pending.value,
        next_attempt_utc=now,
        created_at=now,
        updated_at=now,
    )
    session.add(d)
    await session.flush()
    return d


def reopen_for_manual_resend(delivery: EmailDelivery) -> None:
    """Explicitly re-attempt a finished delivery (same logical record, audited)."""
    delivery.state = DeliveryState.pending.value
    delivery.attempt_count = 0
    delivery.next_attempt_utc = datetime.now(UTC)
    delivery.is_manual_resend = True
    delivery.last_error = None
    delivery.last_error_category = None


async def attempt_delivery(
    session: AsyncSession,
    delivery: EmailDelivery,
    report: Report,
    cfg: SmtpConfig,
    *,
    max_bytes: int,
    site_name: str | None,
) -> EmailDelivery:
    """Make one send attempt and update state/retry. Never raises for SMTP errors."""
    now = datetime.now(UTC)
    rcpts = RecipientSet(
        to=_loads(delivery.recipients_to_json),
        cc=_loads(delivery.recipients_cc_json),
        bcc=_loads(delivery.recipients_bcc_json),
    )
    formats = _loads(delivery.attachment_set_json)
    delivery.attempt_count += 1
    delivery.state = DeliveryState.sending.value
    delivery.updated_at = now
    await session.flush()

    try:
        msg, size = compose(
            report, cfg, rcpts, formats, max_bytes=max_bytes, site_name=site_name
        )
        delivery.size_bytes = size
        outcome = await asyncio.to_thread(send_message, cfg, msg, rcpts)
    except SmtpError as exc:
        _record_failure(delivery, exc.category, exc.message)
        log.info("delivery %s failed: %s", delivery.id, exc.category)
        delivery.updated_at = datetime.now(UTC)
        return delivery

    rejected = [a for a, o in outcome.items() if o == "rejected"]
    delivery.per_recipient_json = json.dumps(outcome)
    if not rejected:
        delivery.state = DeliveryState.completed.value
        delivery.sent_at = datetime.now(UTC)
        delivery.next_attempt_utc = None
        delivery.last_error = None
        delivery.last_error_category = None
    elif len(rejected) < len(outcome):
        # Some accepted, some refused — partial; do not auto-resend to accepted.
        delivery.state = DeliveryState.partially_failed.value
        delivery.sent_at = datetime.now(UTC)
        delivery.next_attempt_utc = None
        delivery.last_error_category = DeliveryFailureCategory.recipient_rejected.value
        delivery.last_error = f"{len(rejected)} recipient(s) refused."
    else:
        _record_failure(
            delivery,
            DeliveryFailureCategory.recipient_rejected.value,
            "All recipients refused.",
        )
    delivery.updated_at = datetime.now(UTC)
    return delivery


def _record_failure(delivery: EmailDelivery, category: str, message: str) -> None:
    delivery.last_error_category = category
    delivery.last_error = message  # already sanitized by the mailer
    permanent = category in _PERMANENT
    if permanent or delivery.attempt_count >= MAX_ATTEMPTS:
        delivery.state = DeliveryState.failed.value
        delivery.next_attempt_utc = None
    else:
        delay = RETRY_SCHEDULE_SECONDS[min(delivery.attempt_count, MAX_ATTEMPTS - 1)]
        delivery.state = DeliveryState.pending.value
        delivery.next_attempt_utc = datetime.now(UTC) + timedelta(seconds=delay)
