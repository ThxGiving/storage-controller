"""Home Assistant history import: ranges, raw import, dedup, statistics, no incidents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import db as db_module
from app import history_import as hi
from app.models import (
    EntityAssignment,
    HistoryImport,
    Incident,
    SampleSource,
    SensorAggregate,
    SensorSample,
)

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def test_range_window_variants():
    s, e = hi.range_window("last_30_days", NOW, "Europe/Berlin")
    assert (e - s).days == 30
    s, e = hi.range_window("last_90_days", NOW, "Europe/Berlin")
    assert (e - s).days == 90
    s, _ = hi.range_window("current_month", NOW, "Europe/Berlin")
    assert s == datetime(2026, 5, 31, 22, tzinfo=UTC)  # 01.06 local in CEST
    s, e = hi.range_window("all", NOW, "Europe/Berlin")
    assert (e - s).days >= 365


class _FakeRest:
    def __init__(self, points):
        self._points = points

    async def get_history(self, entity_id, start_iso, end_iso):
        return self._points


def _points(n, start=NOW - timedelta(days=5)):
    return [
        {"state": f"{4.0 + (i % 3) * 0.5:.2f}", "last_changed": (start + timedelta(minutes=10 * i)).isoformat()}
        for i in range(n)
    ]


async def _unit_with_assignment(client):
    r = await client.post(
        "/api/storage-units",
        json={"name": "KH", "lower_limit_c": 0.0, "upper_limit_c": 8.0,
              "assignments": [{"role": "room_temperature", "entity_id": "sensor.kh"}]},
    )
    uid = r.json()["id"]
    factory = db_module.get_session_factory()
    async with factory() as s:
        aid = await s.scalar(select(EntityAssignment.id).where(EntityAssignment.storage_unit_id == uid))
    return uid, aid


async def _run(uid, aid, rest, *, token=None):
    factory = db_module.get_session_factory()
    async with factory() as s:
        job = HistoryImport(storage_unit_id=uid, entity_id="sensor.kh", requested_range="last_30_days",
                            status="importing", created_at=NOW)
        s.add(job)
        assignment = await s.get(EntityAssignment, aid)
        await s.flush()
        await hi.run_import(s, job=job, assignment=assignment, storage_unit_id=uid,
                            rest=rest, ws_url="ws://x", token=token, entity_unit="°C",
                            tz_name="Europe/Berlin", now=NOW)
        await s.commit()
        return job.status, job.raw_count


@pytest.mark.asyncio
async def test_import_inserts_marked_samples(app_client):
    uid, aid = await _unit_with_assignment(app_client)
    status, raw_count = await _run(uid, aid, _FakeRest(_points(20)))
    assert status == "completed" and raw_count == 20
    factory = db_module.get_session_factory()
    async with factory() as s:
        rows = (await s.scalars(select(SensorSample).where(SensorSample.entity_assignment_id == aid))).all()
        assert len(rows) == 20
        assert all(r.source == SampleSource.home_assistant_history_import.value for r in rows)


@pytest.mark.asyncio
async def test_reimport_is_deduplicated(app_client):
    uid, aid = await _unit_with_assignment(app_client)
    await _run(uid, aid, _FakeRest(_points(20)))
    status, raw_count = await _run(uid, aid, _FakeRest(_points(20)))  # same data again
    assert raw_count == 0  # nothing new
    factory = db_module.get_session_factory()
    async with factory() as s:
        n = await s.scalar(select(func.count()).select_from(SensorSample).where(
            SensorSample.entity_assignment_id == aid))
        assert n == 20  # not duplicated


@pytest.mark.asyncio
async def test_import_never_creates_incidents(app_client):
    uid, aid = await _unit_with_assignment(app_client)
    # values well above the upper limit (8) -> would be a live violation, but an
    # import must NOT create incidents.
    pts = [{"state": "20.0", "last_changed": (NOW - timedelta(days=3) + timedelta(minutes=15 * i)).isoformat()}
           for i in range(10)]
    await _run(uid, aid, _FakeRest(pts))
    factory = db_module.get_session_factory()
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Incident)) == 0


@pytest.mark.asyncio
async def test_empty_history_is_no_history(app_client):
    uid, aid = await _unit_with_assignment(app_client)
    status, raw_count = await _run(uid, aid, _FakeRest([]))
    assert status == "no_history" and raw_count == 0


@pytest.mark.asyncio
async def test_statistics_fallback_imports_hourly_aggregates(app_client, monkeypatch):
    uid, aid = await _unit_with_assignment(app_client)

    async def fake_stats(url, token, entity_id, start_iso, end_iso, period="hour"):
        base = NOW - timedelta(days=40)
        return [
            {"start": (base + timedelta(hours=i)).isoformat(), "min": 3.0, "max": 6.0, "mean": 4.5}
            for i in range(24)
        ]

    monkeypatch.setattr(hi.ws_proto, "fetch_statistics", fake_stats)
    # No raw history -> only statistics -> partial.
    status, raw_count = await _run(uid, aid, _FakeRest([]), token="tok")
    assert status == "partial"
    factory = db_module.get_session_factory()
    async with factory() as s:
        aggs = (await s.scalars(select(SensorAggregate).where(
            SensorAggregate.entity_assignment_id == aid, SensorAggregate.tier == "hourly"))).all()
        assert len(aggs) == 24
        assert all(a.source == "ha_statistics" for a in aggs)
        assert aggs[0].min_c == 3.0 and aggs[0].max_c == 6.0 and aggs[0].avg_c == 4.5


class _WindowRest:
    """Realistic fake: returns only points inside [start, end); can fail chosen
    windows (always, or only the first N calls to exercise retry)."""

    def __init__(self, points, fail_days=None, fail_times=0):
        self._points = points
        self.calls: dict[str, int] = {}
        self._fail_days = set(fail_days or [])
        self._fail_times = fail_times  # 0 == always fail

    async def get_history(self, entity_id, start_iso, end_iso):
        day = start_iso[:10]
        self.calls[day] = self.calls.get(day, 0) + 1
        if day in self._fail_days and (self._fail_times == 0 or self.calls[day] <= self._fail_times):
            raise TimeoutError("boom")
        s = datetime.fromisoformat(start_iso)
        e = datetime.fromisoformat(end_iso)
        return [
            p for p in self._points
            if s <= datetime.fromisoformat(p["last_changed"]) < e
        ]


def _spread(days, per_day=4, end=NOW):
    """Points spread across the last `days` days."""
    pts = []
    for d in range(days):
        for h in range(per_day):
            t = end - timedelta(days=days - d) + timedelta(hours=6 * h)
            pts.append({"state": "4.0", "last_changed": t.isoformat()})
    return pts


async def _run_job(uid, aid, rest, *, token=None, resume=False, job_id=None):
    factory = db_module.get_session_factory()
    async with factory() as s:
        if job_id is None:
            job = HistoryImport(storage_unit_id=uid, entity_id="sensor.kh",
                                requested_range="last_30_days", status="importing", created_at=NOW)
            s.add(job)
            await s.flush()
        else:
            job = await s.get(HistoryImport, job_id)
        assignment = await s.get(EntityAssignment, aid)
        await hi.run_import(s, job=job, assignment=assignment, storage_unit_id=uid, rest=rest,
                            ws_url="ws://x", token=token, entity_unit="°C",
                            tz_name="Europe/Berlin", now=NOW, resume=resume)
        await s.commit()
        return job.id, job.status, job.raw_count


@pytest.mark.asyncio
async def test_seven_day_import(app_client):
    uid, aid = await _unit_with_assignment(app_client)
    _, status, count = await _run_job(uid, aid, _WindowRest(_spread(7)))
    assert status == "completed" and count == 7 * 4


@pytest.mark.asyncio
async def test_chunk_timeout_yields_partial_with_failed_range(app_client):
    uid, aid = await _unit_with_assignment(app_client)
    # Fail the window that starts 25 days before NOW (one 5-day chunk).
    fail_day = (NOW - timedelta(days=25)).date().isoformat()
    rest = _WindowRest(_spread(30), fail_days=[fail_day])
    job_id, status, count = await _run_job(uid, aid, rest)
    assert status == "partial" and count > 0
    factory = db_module.get_session_factory()
    async with factory() as s:
        job = await s.get(HistoryImport, job_id)
        ranges = hi.summarize_chunks(job.chunks_json)
        assert len(ranges["failed"]) == 1  # exactly the failed window is reported
        assert ranges["imported"]  # the rest imported


@pytest.mark.asyncio
async def test_failed_window_is_retried_with_backoff(app_client, monkeypatch):
    monkeypatch.setattr(hi, "_RETRY_BASE_DELAY", 0.0)  # no real sleeping
    uid, aid = await _unit_with_assignment(app_client)
    fail_day = (NOW - timedelta(days=25)).date().isoformat()
    rest = _WindowRest(_spread(30), fail_days=[fail_day], fail_times=2)  # fail twice, then ok
    _, status, count = await _run_job(uid, aid, rest)
    assert status == "completed" and count == 30 * 4
    assert rest.calls[fail_day] == 3  # 2 failures + 1 success


@pytest.mark.asyncio
async def test_resume_skips_done_and_retries_failed(app_client, monkeypatch):
    monkeypatch.setattr(hi, "_RETRY_BASE_DELAY", 0.0)
    uid, aid = await _unit_with_assignment(app_client)
    fail_day = (NOW - timedelta(days=25)).date().isoformat()
    rest1 = _WindowRest(_spread(30), fail_days=[fail_day])  # one window fails
    job_id, status, count1 = await _run_job(uid, aid, rest1)
    assert status == "partial"
    # Resume with a healthy client: only the failed window is re-fetched.
    rest2 = _WindowRest(_spread(30))
    _, status2, count2 = await _run_job(uid, aid, rest2, resume=True, job_id=job_id)
    assert status2 == "completed"
    assert count2 == 30 * 4  # cumulative full coverage after resume, no duplicates
    assert count1 < count2  # resume added the previously-failed window
    assert list(rest2.calls.keys()) == [fail_day]  # done windows not re-fetched


@pytest.mark.asyncio
async def test_restart_orphaned_import_resumes(app_client, monkeypatch):
    monkeypatch.setattr(hi, "_RETRY_BASE_DELAY", 0.0)
    uid, aid = await _unit_with_assignment(app_client)
    # Simulate a crash mid-import: an "importing" job with a half-done plan.
    import json
    factory = db_module.get_session_factory()
    async with factory() as s:
        plan = [
            {"s": (NOW - timedelta(days=30)).isoformat(), "e": (NOW - timedelta(days=25)).isoformat(), "st": "done"},
            {"s": (NOW - timedelta(days=25)).isoformat(), "e": (NOW - timedelta(days=20)).isoformat(), "st": "pending"},
        ]
        job = HistoryImport(storage_unit_id=uid, entity_id="sensor.kh", requested_range="last_30_days",
                            status="importing", created_at=NOW, chunks_json=json.dumps(plan))
        s.add(job)
        await s.commit()
        jid = job.id
    rest = _WindowRest(_spread(30))
    _, status, _count = await _run_job(uid, aid, rest, resume=True, job_id=jid)
    # The already-done window must not be refetched; pending ones complete.
    assert (NOW - timedelta(days=30)).date().isoformat() not in rest.calls
    assert status in ("completed", "partial")


@pytest.mark.asyncio
async def test_sparse_history_completes_without_bridging(app_client):
    uid, aid = await _unit_with_assignment(app_client)
    # Data on a single day only, inside a 30-day request.
    one_day = [{"state": "4.0", "last_changed": (NOW - timedelta(days=12) + timedelta(hours=h)).isoformat()}
               for h in range(6)]
    _, status, count = await _run_job(uid, aid, _WindowRest(one_day))
    assert status == "completed" and count == 6  # only the real points, no filling


@pytest.mark.asyncio
async def test_unit_or_sensor_removed_mid_import_is_safe(app_client):
    # The background runner must no-op when the job/assignment vanished.
    from app.api import history_import as api
    await api._run(999999, 999999, 999999, _FakeRest([]), "ws://x", None, "°C", "Europe/Berlin")


@pytest.mark.asyncio
async def test_api_availability_no_ha(app_client):
    uid, _ = await _unit_with_assignment(app_client)
    r = await app_client.get(f"/api/storage-units/{uid}/history/availability?entity_id=sensor.kh")
    assert r.status_code == 200
    assert r.json()["state"] == "no_history"  # no HA configured in tests


@pytest.mark.asyncio
async def test_api_import_requires_assigned_entity(app_client):
    uid, _ = await _unit_with_assignment(app_client)
    r = await app_client.post(
        f"/api/storage-units/{uid}/history/import",
        json={"entity_id": "sensor.not_assigned", "range": "last_30_days"},
    )
    assert r.status_code == 422
