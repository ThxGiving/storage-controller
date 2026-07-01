"""Report schedules + execution history + manual actions (Phase 6)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db, get_session_factory
from ..errors import AppError
from ..mailer import normalize_recipients, valid_email
from ..models import (
    AuditEvent,
    DeliveryState,
    EmailDelivery,
    Report,
    ReportSchedule,
    ScheduleRun,
    ScheduleRunState,
    StorageUnit,
)
from ..scheduler import SchedulerRunner
from ..scheduling import next_run_utc
from ..schemas import (
    EmailDeliveryOut,
    ScheduleIn,
    ScheduleOut,
    ScheduleRunOut,
)
from ..smtp_store import mask_email

log = logging.getLogger("api")
router = APIRouter(prefix="/api/schedules", tags=["schedules"])

_FORMATS = {"pdf", "csv", "json"}
_LOCALES = {"de", "en"}


def _user(request: Request) -> str | None:
    return request.headers.get("X-Remote-User-Name") or request.headers.get("X-Remote-User-Id")


def _utc(dt: datetime | None) -> datetime | None:
    """Tag naive datetimes as UTC. SQLite returns naive values even for
    ``DateTime(timezone=True)`` columns, so without this the API serializes them
    without an offset and browsers misread stored UTC as local time (e.g. a
    06:00 Europe/Berlin run shows as 04:00)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _loads(raw: str | None) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def _runner() -> SchedulerRunner:
    return SchedulerRunner(get_session_factory())


def _sched_out(s: ReportSchedule) -> ScheduleOut:
    runner = _runner()
    py, pm = runner.run_now_period(s)
    to = [str(x) for x in _loads(s.recipients_to_json)]
    cc = [str(x) for x in _loads(s.recipients_cc_json)]
    bcc = [str(x) for x in _loads(s.recipients_bcc_json)]
    return ScheduleOut(
        id=s.id, name=s.name, enabled=s.enabled, report_type=s.report_type,
        period_rule=s.period_rule,
        storage_unit_ids=[int(x) for x in _loads(s.storage_unit_ids_json)],
        locale=s.locale, timezone=s.timezone, detail_level=s.detail_level,
        recipients_to=to, recipients_cc=cc, recipients_bcc=bcc,
        recipient_count=len(to) + len(cc) + len(bcc),
        attachment_formats=[str(x) for x in _loads(s.attachment_formats_json)],
        run_day=s.run_day, run_time=s.run_time, catch_up_mode=s.catch_up_mode,
        next_run_utc=_utc(s.next_run_utc)
        or next_run_utc(s.run_day, s.run_time, s.timezone, datetime.now(UTC)),
        last_run_utc=_utc(s.last_run_utc), last_result=s.last_result,
        run_now_period=f"{py:04d}-{pm:02d}",
    )


def _delivery_out(d: EmailDelivery | None) -> EmailDeliveryOut | None:
    if d is None:
        return None
    to = [str(x) for x in _loads(d.recipients_to_json)]
    cc = [str(x) for x in _loads(d.recipients_cc_json)]
    bcc = [str(x) for x in _loads(d.recipients_bcc_json)]
    per = None
    if d.per_recipient_json:
        try:
            raw = json.loads(d.per_recipient_json)
            per = {mask_email(k): v for k, v in raw.items()}
        except (ValueError, TypeError):
            per = None
    return EmailDeliveryOut(
        id=d.id, state=d.state, attempt_count=d.attempt_count,
        next_attempt_utc=_utc(d.next_attempt_utc), last_error_category=d.last_error_category,
        last_error=d.last_error,
        recipients_masked=[mask_email(a) for a in [*to, *cc, *bcc]],
        recipient_count=len(to) + len(cc) + len(bcc),
        per_recipient=per, size_bytes=d.size_bytes, is_manual_resend=d.is_manual_resend,
        sent_at=_utc(d.sent_at),
    )


async def _run_out(db: AsyncSession, run: ScheduleRun) -> ScheduleRunOut:
    report = await db.get(Report, run.report_id) if run.report_id else None
    delivery = await db.scalar(
        select(EmailDelivery).where(EmailDelivery.schedule_run_id == run.id)
    )
    return ScheduleRunOut(
        id=run.id, schedule_id=run.schedule_id, period_year=run.period_year,
        period_month=run.period_month, period_label=f"{run.period_year:04d}-{run.period_month:02d}",
        scheduled_for_utc=_utc(run.scheduled_for_utc), state=run.state, trigger=run.trigger,
        report_id=run.report_id, report_uuid=report.uuid if report else None,
        report_status=run.report_status, generation_error=run.generation_error,
        attempt_count=run.attempt_count,
        started_at=_utc(run.started_at), finished_at=_utc(run.finished_at),
        delivery=_delivery_out(delivery),
    )


def _validate(payload: ScheduleIn) -> None:
    if payload.locale not in _LOCALES:
        raise AppError("invalid_locale", status_code=422)
    fmts = set(payload.attachment_formats)
    if not fmts or not fmts.issubset(_FORMATS):
        raise AppError("invalid_attachment_formats", status_code=422)
    for addr in [*payload.recipients_to, *payload.recipients_cc, *payload.recipients_bcc]:
        if not valid_email(addr):
            raise AppError("invalid_recipient", status_code=422)


async def _apply(db: AsyncSession, s: ReportSchedule, p: ScheduleIn) -> None:
    ids_q = select(StorageUnit.id).where(StorageUnit.id.in_(p.storage_unit_ids or [0]))
    valid_ids = set((await db.scalars(ids_q)).all())
    ids = [i for i in p.storage_unit_ids if i in valid_ids]
    s.name = p.name.strip()
    s.enabled = p.enabled
    s.report_type = "monthly"
    s.period_rule = "previous_month"
    s.storage_unit_ids_json = json.dumps(ids)
    s.locale = p.locale
    s.timezone = p.timezone
    s.detail_level = p.detail_level
    # Normalize: trim, validate, strip header-injection, de-duplicate across buckets.
    rcpts = normalize_recipients(p.recipients_to, p.recipients_cc, p.recipients_bcc)
    s.recipients_to_json = json.dumps(rcpts.to)
    s.recipients_cc_json = json.dumps(rcpts.cc)
    s.recipients_bcc_json = json.dumps(rcpts.bcc)
    # PDF is always included; dedupe + order pdf,csv,json.
    fmts = [f for f in ("pdf", "csv", "json") if f in set(p.attachment_formats) | {"pdf"}]
    s.attachment_formats_json = json.dumps(fmts)
    s.run_day = p.run_day
    s.run_time = p.run_time
    s.catch_up_mode = "none" if p.catch_up_mode == "none" else "one"
    s.next_run_utc = next_run_utc(s.run_day, s.run_time, s.timezone, datetime.now(UTC))
    s.updated_at = datetime.now(UTC)


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(db: AsyncSession = Depends(get_db)) -> list[ScheduleOut]:
    q = select(ReportSchedule).order_by(ReportSchedule.created_at.asc())
    rows = (await db.scalars(q)).all()
    return [_sched_out(s) for s in rows]


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    payload: ScheduleIn, request: Request, db: AsyncSession = Depends(get_db)
) -> ScheduleOut:
    _validate(payload)
    s = ReportSchedule(created_by=_user(request), created_at=datetime.now(UTC))
    await _apply(db, s, payload)
    db.add(s)
    await db.flush()
    db.add(AuditEvent(component="scheduler", action="schedule_created", user=_user(request),
                      object_type="schedule", object_id=str(s.id), detail=s.name))
    await db.commit()
    return _sched_out(s)


async def _get(db: AsyncSession, schedule_id: int) -> ReportSchedule:
    s = await db.get(ReportSchedule, schedule_id)
    if s is None:
        raise AppError("schedule_not_found", status_code=404)
    return s


@router.get("/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(schedule_id: int, db: AsyncSession = Depends(get_db)) -> ScheduleOut:
    return _sched_out(await _get(db, schedule_id))


@router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: int, payload: ScheduleIn, request: Request, db: AsyncSession = Depends(get_db)
) -> ScheduleOut:
    _validate(payload)
    s = await _get(db, schedule_id)
    await _apply(db, s, payload)
    db.add(AuditEvent(component="scheduler", action="schedule_updated", user=_user(request),
                      object_type="schedule", object_id=str(s.id), detail=s.name))
    await db.commit()
    return _sched_out(s)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    s = await _get(db, schedule_id)
    db.add(AuditEvent(component="scheduler", action="schedule_deleted", user=_user(request),
                      object_type="schedule", object_id=str(s.id), detail=s.name))
    await db.delete(s)
    await db.commit()


@router.post("/{schedule_id}/enable", response_model=ScheduleOut)
async def enable_schedule(
    schedule_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> ScheduleOut:
    return await _toggle(db, schedule_id, True, _user(request))


@router.post("/{schedule_id}/disable", response_model=ScheduleOut)
async def disable_schedule(
    schedule_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> ScheduleOut:
    return await _toggle(db, schedule_id, False, _user(request))


async def _toggle(
    db: AsyncSession, schedule_id: int, enabled: bool, user: str | None
) -> ScheduleOut:
    s = await _get(db, schedule_id)
    s.enabled = enabled
    s.updated_at = datetime.now(UTC)
    db.add(AuditEvent(
        component="scheduler",
        action="schedule_enabled" if enabled else "schedule_disabled",
        user=user, object_type="schedule", object_id=str(s.id), detail=s.name,
    ))
    await db.commit()
    return _sched_out(s)


@router.post("/{schedule_id}/run-now", response_model=ScheduleRunOut)
async def run_now(
    schedule_id: int, request: Request, send: bool = True, db: AsyncSession = Depends(get_db)
) -> ScheduleRunOut:
    s = await _get(db, schedule_id)
    run = await _runner().run_now(db, s, send=send)
    return await _run_out(db, run)


@router.get("/{schedule_id}/runs", response_model=list[ScheduleRunOut])
async def list_runs(
    schedule_id: int, db: AsyncSession = Depends(get_db)
) -> list[ScheduleRunOut]:
    await _get(db, schedule_id)
    runs = (
        await db.scalars(
            select(ScheduleRun)
            .where(ScheduleRun.schedule_id == schedule_id)
            .order_by(ScheduleRun.scheduled_for_utc.desc())
            .limit(100)
        )
    ).all()
    return [await _run_out(db, r) for r in runs]


async def _run(db: AsyncSession, run_id: int) -> ScheduleRun:
    run = await db.get(ScheduleRun, run_id)
    if run is None:
        raise AppError("run_not_found", status_code=404)
    return run


@router.get("/runs/{run_id}", response_model=ScheduleRunOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> ScheduleRunOut:
    return await _run_out(db, await _run(db, run_id))


@router.post("/runs/{run_id}/send", response_model=ScheduleRunOut)
async def send_existing(
    run_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> ScheduleRunOut:
    run = await _run(db, run_id)
    if not run.report_id or run.report_status != "completed":
        raise AppError("no_generated_report", status_code=409)
    await _runner().deliver_existing(db, run)
    return await _run_out(db, run)


@router.post("/runs/{run_id}/resend", response_model=ScheduleRunOut)
async def resend(
    run_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> ScheduleRunOut:
    from ..delivery import reopen_for_manual_resend

    run = await _run(db, run_id)
    delivery = await db.scalar(select(EmailDelivery).where(EmailDelivery.schedule_run_id == run.id))
    if delivery is None:
        raise AppError("no_delivery", status_code=409)
    reopen_for_manual_resend(delivery)
    db.add(AuditEvent(
        component="scheduler", action="delivery_manual_resend", user=_user(request),
        object_type="schedule_run", object_id=str(run.id), detail=f"delivery={delivery.id}",
    ))
    await db.commit()
    await _runner().deliver_existing(db, run)
    return await _run_out(db, run)


@router.post("/runs/{run_id}/cancel", response_model=ScheduleRunOut)
async def cancel_run(
    run_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> ScheduleRunOut:
    run = await _run(db, run_id)
    if run.state not in (ScheduleRunState.pending.value, ScheduleRunState.sending.value):
        raise AppError("run_not_cancellable", status_code=409)
    run.state = ScheduleRunState.cancelled.value
    run.finished_at = datetime.now(UTC)
    delivery = await db.scalar(select(EmailDelivery).where(EmailDelivery.schedule_run_id == run.id))
    if delivery is not None and delivery.state in (DeliveryState.pending.value,):
        delivery.state = DeliveryState.cancelled.value
        delivery.next_attempt_utc = None
    db.add(AuditEvent(component="scheduler", action="run_cancelled", user=_user(request),
                      object_type="schedule_run", object_id=str(run.id), detail=""))
    await db.commit()
    return await _run_out(db, run)
