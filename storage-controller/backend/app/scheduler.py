"""Persistent report scheduler (Phase 6).

A single-process background runner that, on each tick and on startup:

* creates the **one** due ``ScheduleRun`` per (schedule, reporting period) —
  ``UNIQUE(schedule, period)`` makes this idempotent and crash-safe,
* generates the report (reusing the immutable report pipeline) under an execution
  lock with stale-lock recovery,
* creates/continues the idempotent email delivery and applies the retry policy,
* performs bounded catch-up of one missed period after downtime,
* keeps ``next_run_utc`` current for the UI.

Generation success and delivery success are tracked separately; a generated
report is preserved even when delivery fails.
"""

from __future__ import annotations

import json
import logging
import os
import uuid as uuidlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .delivery import attempt_delivery, get_or_create_delivery
from .models import (
    AuditEvent,
    DeliveryState,
    EmailDelivery,
    Report,
    ReportSchedule,
    ScheduleRun,
    ScheduleRunState,
    SmtpSettings,
)
from .reporting.service import generate
from .scheduling import (
    latest_fire_utc,
    month_range_utc,
    next_run_utc,
    previous_month,
    reporting_period_for_fire,
)
from .smtp_store import default_recipients, merge_recipients, to_config

log = logging.getLogger("scheduler")

LOCK_TIMEOUT = timedelta(minutes=15)  # stale-lock recovery window
CATCHUP_GRACE = timedelta(hours=6)  # within this of the fire time = a normal run
REPORT_MODEL_VERSION = "2"

_ACTIVE_RUN_STATES = [
    ScheduleRunState.pending.value,
    ScheduleRunState.generating.value,
    ScheduleRunState.generated.value,
    ScheduleRunState.sending.value,
]


def _loads(raw: str | None) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


class SchedulerRunner:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory
        self.worker_id = f"sched-{os.getpid()}"

    def run_now_period(self, sched: ReportSchedule, now: datetime | None = None) -> tuple[int, int]:
        """The reporting period a manual 'Run now' uses: the previous *complete*
        calendar month relative to now (never the current incomplete month)."""
        from .scheduling import _zone  # local import: small helper

        now = now or datetime.now(UTC)
        local = now.astimezone(_zone(sched.timezone))
        return previous_month(local.year, local.month)

    async def run_now(
        self, session: AsyncSession, sched: ReportSchedule, *, send: bool,
        now: datetime | None = None,
    ) -> ScheduleRun:
        now = now or datetime.now(UTC)
        py, pm = self.run_now_period(sched, now)
        run = await session.scalar(
            select(ScheduleRun).where(
                ScheduleRun.schedule_id == sched.id,
                ScheduleRun.period_year == py,
                ScheduleRun.period_month == pm,
            )
        )
        if run is None:
            run = ScheduleRun(
                schedule_id=sched.id, period_year=py, period_month=pm,
                scheduled_for_utc=now, state=ScheduleRunState.pending.value, trigger="manual",
            )
            session.add(run)
        else:
            run.state = ScheduleRunState.pending.value
            run.trigger = "manual"
        run.locked_by = self.worker_id
        run.locked_at = now
        await session.commit()
        _audit(session, "manual_run", sched.id, f"{py}-{pm:02d} send={send}")

        report = await self._generate(session, sched, run, now)
        if report is None:
            run.locked_by = None
            await session.commit()
            return run
        if send:
            await self._deliver(session, sched, run, report, now)
        else:
            run.state = ScheduleRunState.generated.value
            run.finished_at = now
            sched.last_run_utc = now
            sched.last_result = run.state
            await session.commit()
        run.locked_by = None
        await session.commit()
        return run

    async def deliver_existing(
        self, session: AsyncSession, run: ScheduleRun, now: datetime | None = None
    ) -> ScheduleRun:
        """Send an already-generated report for a run (manual 'Send existing')."""
        now = now or datetime.now(UTC)
        sched = await session.get(ReportSchedule, run.schedule_id)
        report = await session.get(Report, run.report_id) if run.report_id else None
        if sched is None or report is None or report.status != "completed":
            return run
        await self._deliver(session, sched, run, report, now)
        return run

    async def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        async with self._sf() as session:
            schedules = (await session.scalars(select(ReportSchedule))).all()
            for sched in schedules:
                if sched.enabled:
                    await self._ensure_due_run(session, sched, now)
                sched.next_run_utc = next_run_utc(
                    sched.run_day, sched.run_time, sched.timezone, now
                )
            await session.commit()

            runs = (
                await session.scalars(
                    select(ScheduleRun)
                    .where(ScheduleRun.state.in_(_ACTIVE_RUN_STATES))
                    .order_by(ScheduleRun.scheduled_for_utc.asc())
                )
            ).all()
            for run in runs:
                await self._execute_run(session, run, now)

            await self._process_retries(session, now)

    # -- schedule → run --------------------------------------------------- #

    async def _ensure_due_run(self, session: AsyncSession, sched: ReportSchedule, now: datetime):
        fire = latest_fire_utc(sched.run_day, sched.run_time, sched.timezone, now)
        if fire > now:
            return
        py, pm = reporting_period_for_fire(fire, sched.timezone)
        existing = await session.scalar(
            select(ScheduleRun).where(
                ScheduleRun.schedule_id == sched.id,
                ScheduleRun.period_year == py,
                ScheduleRun.period_month == pm,
            )
        )
        if existing is not None:
            return
        catch_up = (now - fire) > CATCHUP_GRACE
        if catch_up and sched.catch_up_mode == "none":
            session.add(
                ScheduleRun(
                    schedule_id=sched.id, period_year=py, period_month=pm,
                    scheduled_for_utc=fire, state=ScheduleRunState.skipped.value,
                    trigger="catch_up", finished_at=now,
                )
            )
            _audit(session, "schedule_run_skipped", sched.id, f"{py}-{pm:02d} (catch-up disabled)")
            return
        session.add(
            ScheduleRun(
                schedule_id=sched.id, period_year=py, period_month=pm,
                scheduled_for_utc=fire, state=ScheduleRunState.pending.value,
                trigger="catch_up" if catch_up else "scheduled",
            )
        )
        await session.flush()

    # -- run execution ---------------------------------------------------- #

    async def _execute_run(self, session: AsyncSession, run: ScheduleRun, now: datetime):
        # Respect a fresh lock held by another worker; recover a stale one.
        if (
            run.locked_by
            and run.locked_by != self.worker_id
            and run.locked_at
            and (now - _aware(run.locked_at)) < LOCK_TIMEOUT
        ):
            return
        run.locked_by = self.worker_id
        run.locked_at = now
        await session.commit()

        sched = await session.get(ReportSchedule, run.schedule_id)
        if sched is None:
            return

        report = await self._generate(session, sched, run, now)
        if report is None:
            sched.last_run_utc = now
            sched.last_result = run.state
            run.locked_by = None
            await session.commit()
            return

        await self._deliver(session, sched, run, report, now)
        run.locked_by = None
        await session.commit()

    async def _generate(
        self, session: AsyncSession, sched: ReportSchedule, run: ScheduleRun, now: datetime
    ) -> Report | None:
        if run.report_id is not None:
            existing = await session.get(Report, run.report_id)
            if existing is not None and existing.status == "completed":
                return existing

        run.state = ScheduleRunState.generating.value
        run.started_at = run.started_at or now
        run.attempt_count += 1
        await session.commit()

        units = [int(x) for x in _loads(sched.storage_unit_ids_json)]
        start_utc, end_utc = month_range_utc(run.period_year, run.period_month, sched.timezone)
        report = Report(
            uuid=str(uuidlib.uuid4()),
            status="queued",
            period_year=run.period_year,
            period_month=run.period_month,
            period_start_utc=start_utc,
            period_end_utc=end_utc,
            locale=sched.locale,
            timezone=sched.timezone,
            detail_level=sched.detail_level,
            storage_unit_ids_json=json.dumps(units),
            report_model_version=REPORT_MODEL_VERSION,
            created_by=f"schedule:{sched.id}",
            created_at=now,
        )
        session.add(report)
        await session.flush()
        try:
            await generate(session, report)
        except Exception as exc:  # noqa: BLE001 — sanitized failure
            report.status = "failed"
            log.warning("scheduler: generation error: %s", type(exc).__name__)

        if report.status != "completed":
            run.report_id = report.id
            run.report_status = report.status
            run.generation_error = "Report generation failed."
            run.state = ScheduleRunState.failed.value
            run.finished_at = datetime.now(UTC)
            _audit(session, "report_generation_failed", sched.id, f"run={run.id}")
            await session.commit()
            return None

        run.report_id = report.id
        run.report_status = "completed"
        run.state = ScheduleRunState.generated.value
        await session.commit()
        _audit(session, "report_generated", sched.id, f"run={run.id} report={report.uuid}")
        return report

    async def _deliver(
        self, session: AsyncSession, sched: ReportSchedule, run: ScheduleRun,
        report: Report, now: datetime,
    ):
        smtp = await session.get(SmtpSettings, 1)
        defaults = default_recipients(smtp) if smtp else default_recipients(SmtpSettings())
        rcpts = merge_recipients(
            [str(x) for x in _loads(sched.recipients_to_json)],
            [str(x) for x in _loads(sched.recipients_cc_json)],
            [str(x) for x in _loads(sched.recipients_bcc_json)],
            defaults,
        )
        formats = [str(x) for x in _loads(sched.attachment_formats_json)] or ["pdf"]

        if rcpts.count == 0 or smtp is None or not smtp.host:
            # Generated successfully; nothing to send (or SMTP not configured).
            run.state = ScheduleRunState.completed.value
            run.finished_at = now
            sched.last_run_utc = now
            sched.last_result = run.state
            await session.commit()
            return

        delivery = await get_or_create_delivery(
            session, report=report, rcpts=rcpts, formats=formats,
            schedule_id=sched.id, schedule_run_id=run.id,
        )
        run.state = ScheduleRunState.sending.value
        await session.commit()

        # First delivery pass always attempts immediately; retries are gated by
        # next_attempt_utc in _process_retries.
        if delivery.state == DeliveryState.pending.value:
            await attempt_delivery(
                session, delivery, report, to_config(smtp),
                max_bytes=smtp.max_attachment_bytes, site_name=smtp.site_name,
            )
        _sync_run_with_delivery(run, delivery, now)
        sched.last_run_utc = now
        sched.last_result = run.state
        await session.commit()
        _audit(session, "delivery_attempt", sched.id, f"run={run.id} state={delivery.state}")

    async def _process_retries(self, session: AsyncSession, now: datetime):
        due = (
            await session.scalars(
                select(EmailDelivery).where(
                    EmailDelivery.state == DeliveryState.pending.value,
                    EmailDelivery.next_attempt_utc.is_not(None),
                    EmailDelivery.next_attempt_utc <= now,
                )
            )
        ).all()
        for delivery in due:
            if delivery.report_id is None:
                continue
            report = await session.get(Report, delivery.report_id)
            smtp = await session.get(SmtpSettings, 1)
            if report is None or smtp is None:
                continue
            await attempt_delivery(
                session, delivery, report, to_config(smtp),
                max_bytes=smtp.max_attachment_bytes, site_name=smtp.site_name,
            )
            if delivery.schedule_run_id is not None:
                run = await session.get(ScheduleRun, delivery.schedule_run_id)
                if run is not None:
                    _sync_run_with_delivery(run, delivery, now)
            await session.commit()


def _sync_run_with_delivery(run: ScheduleRun, delivery: EmailDelivery, now: datetime) -> None:
    """Map delivery state onto the run; the report is always preserved."""
    if delivery.state == DeliveryState.completed.value:
        run.state = ScheduleRunState.completed.value
        run.finished_at = now
    elif delivery.state == DeliveryState.partially_failed.value:
        run.state = ScheduleRunState.partially_failed.value
        run.finished_at = now
    elif delivery.state == DeliveryState.failed.value:
        run.state = ScheduleRunState.failed.value  # report stays available (report_id set)
        run.finished_at = now
    else:  # pending/sending → still in progress, retries will continue
        run.state = ScheduleRunState.sending.value


def _due(ts: datetime | None, now: datetime) -> bool:
    return ts is None or _aware(ts) <= now


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _audit(session: AsyncSession, action: str, schedule_id: int, detail: str) -> None:
    session.add(
        AuditEvent(
            component="scheduler", action=action, object_type="schedule",
            object_id=str(schedule_id), detail=detail,
        )
    )
