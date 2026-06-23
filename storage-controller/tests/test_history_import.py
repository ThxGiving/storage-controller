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
