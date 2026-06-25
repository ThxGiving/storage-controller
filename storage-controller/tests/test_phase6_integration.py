"""End-to-end scheduler + delivery integration (Phase 6).

Real report generation (immutable artifacts) with the SMTP transport mocked at
``app.delivery.send_message``: covers generate+deliver, idempotency, retry,
generation-ok/delivery-fail (report preserved), attachments, size limit, catch-up,
and DE/EN templates.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import db as db_module
from app import delivery as delivery_mod
from app.mailer import SmtpError
from app.models import (
    DeliveryState,
    EmailDelivery,
    Report,
    ReportSchedule,
    ScheduleRun,
    ScheduleRunState,
)
from app.scheduler import SchedulerRunner
from app.smtp_store import get_or_create


class _Sender:
    """Records sent messages; configurable failure behaviour."""

    def __init__(self, behavior="ok"):
        self.behavior = behavior
        self.calls = 0
        self.sent = []

    def __call__(self, cfg, msg, rcpts):
        self.calls += 1
        if self.behavior == "temp" or (self.behavior == "temp_then_ok" and self.calls == 1):
            raise SmtpError("temporary_smtp", "temporary")
        self.sent.append(msg)
        return {a: "accepted" for a in rcpts.all}


async def _unit(client):
    r = await client.post(
        "/api/storage-units",
        json={"name": "U", "lower_limit_c": 2.0, "upper_limit_c": 8.0,
              "assignments": [{"role": "room_temperature", "entity_id": "sensor.u"}]},
    )
    return r.json()["id"]


async def _setup_smtp(factory, **over):
    async with factory() as s:
        row = await get_or_create(s)
        row.host = "smtp.local"
        row.sender_email = "from@example.com"
        row.sender_name = "Connie's Diner"
        row.site_name = "Connie's Diner"
        row.default_to_json = json.dumps(["ops@example.com"])
        for k, v in over.items():
            setattr(row, k, v)
        await s.commit()


async def _schedule(factory, uid, *, locale="de", formats=("pdf",), recipients=None):
    async with factory() as s:
        sc = ReportSchedule(
            name="Monthly", enabled=True, storage_unit_ids_json=json.dumps([uid]),
            locale=locale, attachment_formats_json=json.dumps(list(formats)),
            recipients_to_json=json.dumps(recipients or []),
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        s.add(sc)
        await s.commit()
        return sc.id


@pytest.mark.asyncio
async def test_run_now_generates_and_delivers(app_client, monkeypatch):
    sender = _Sender("ok")
    monkeypatch.setattr(delivery_mod, "send_message", sender)
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid)
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        run = await SchedulerRunner(factory).run_now(s, sched, send=True)
        assert run.state == ScheduleRunState.completed.value
        assert run.report_id is not None and run.report_status == "completed"
    assert len(sender.sent) == 1
    assert "Connie's Diner" in sender.sent[0]["Subject"]


@pytest.mark.asyncio
async def test_generation_ok_delivery_fail_preserves_report(app_client, monkeypatch):
    monkeypatch.setattr(delivery_mod, "send_message", _Sender("temp"))
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid)
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        run = await SchedulerRunner(factory).run_now(s, sched, send=True)
        report = await s.get(Report, run.report_id)
        assert report is not None and report.status == "completed"  # report preserved
        delivery = await s.scalar(
            select(EmailDelivery).where(EmailDelivery.schedule_run_id == run.id)
        )
        assert delivery.state == DeliveryState.pending.value  # queued for retry
        assert delivery.next_attempt_utc is not None
        assert run.state == ScheduleRunState.sending.value  # not "failed"; report kept


@pytest.mark.asyncio
async def test_duplicate_run_and_report_prevention(app_client, monkeypatch):
    monkeypatch.setattr(delivery_mod, "send_message", _Sender("ok"))
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid)
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        runner = SchedulerRunner(factory)
        run1 = await runner.run_now(s, sched, send=True)
        run2 = await runner.run_now(s, sched, send=True)
        assert run1.id == run2.id  # same period -> same run
        n_runs = await s.scalar(select(func.count()).select_from(ScheduleRun))
        assert n_runs == 1
        # one delivery (idempotent on key), one report for the period
        n_del = await s.scalar(select(func.count()).select_from(EmailDelivery))
        assert n_del == 1


@pytest.mark.asyncio
async def test_retry_then_success(app_client, monkeypatch):
    sender = _Sender("temp_then_ok")
    monkeypatch.setattr(delivery_mod, "send_message", sender)
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid)
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        runner = SchedulerRunner(factory)
        run = await runner.run_now(s, sched, send=True)
        assert run.state == ScheduleRunState.sending.value  # first attempt failed
        # make the retry due and process it
        delivery = await s.scalar(
            select(EmailDelivery).where(EmailDelivery.schedule_run_id == run.id)
        )
        delivery.next_attempt_utc = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
        await runner._process_retries(s, datetime.now(UTC))
        await s.refresh(delivery)
        assert delivery.state == DeliveryState.completed.value
        assert sender.calls == 2


@pytest.mark.asyncio
async def test_pdf_csv_json_attachments(app_client, monkeypatch):
    sender = _Sender("ok")
    monkeypatch.setattr(delivery_mod, "send_message", sender)
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid, formats=("pdf", "csv", "json"))
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        await SchedulerRunner(factory).run_now(s, sched, send=True)
    names = [p.get_filename() for p in sender.sent[0].iter_attachments()]
    assert sum(n.endswith(".pdf") for n in names) == 1
    assert sum(n.endswith(".csv") for n in names) == 1
    assert sum(n.endswith(".json") for n in names) == 1


@pytest.mark.asyncio
async def test_attachment_size_limit_fails_but_keeps_report(app_client, monkeypatch):
    monkeypatch.setattr(delivery_mod, "send_message", _Sender("ok"))
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory, max_attachment_bytes=1024)  # tiny -> too large
    sid = await _schedule(factory, uid)
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        run = await SchedulerRunner(factory).run_now(s, sched, send=True)
        report = await s.get(Report, run.report_id)
        assert report.status == "completed"  # report preserved + downloadable
        delivery = await s.scalar(
            select(EmailDelivery).where(EmailDelivery.schedule_run_id == run.id)
        )
        assert delivery.state == DeliveryState.failed.value
        assert delivery.last_error_category == "message_too_large"


@pytest.mark.asyncio
async def test_generate_without_sending(app_client, monkeypatch):
    sender = _Sender("ok")
    monkeypatch.setattr(delivery_mod, "send_message", sender)
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid)
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        run = await SchedulerRunner(factory).run_now(s, sched, send=False)
        assert run.state == ScheduleRunState.generated.value
        assert run.report_id is not None
    assert sender.calls == 0  # nothing sent


@pytest.mark.asyncio
async def test_english_template_subject(app_client, monkeypatch):
    sender = _Sender("ok")
    monkeypatch.setattr(delivery_mod, "send_message", sender)
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid, locale="en")
    async with factory() as s:
        sched = await s.get(ReportSchedule, sid)
        await SchedulerRunner(factory).run_now(s, sched, send=True)
    assert sender.sent[0]["Subject"].startswith("HACCP Temperature Report")


@pytest.mark.asyncio
async def test_catch_up_runs_one_missed_period(app_client, monkeypatch):
    monkeypatch.setattr(delivery_mod, "send_message", _Sender("ok"))
    uid = await _unit(app_client)
    factory = db_module.get_session_factory()
    await _setup_smtp(factory)
    sid = await _schedule(factory, uid)
    async with factory() as s:
        # A normal tick (now is well past this month's fire) creates + runs one run.
        await SchedulerRunner(factory).tick(datetime.now(UTC))
        runs = (await s.scalars(select(ScheduleRun).where(ScheduleRun.schedule_id == sid))).all()
        assert len(runs) == 1  # exactly one missed period, not a backlog
