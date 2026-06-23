from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app import db as db_module
from app.maintenance import (
    aggregate,
    cleanup_aggregates,
    cleanup_raw,
    storage_usage,
)
from app.models import Incident, SampleSource, SensorAggregate, SensorSample
from app.timezone import resolve_timezone
from .conftest import get_collector, ha_state

UTC = timezone.utc


# ---- Timezone (CET/CEST) --------------------------------------------------- #


def test_timezone_cet_in_winter():
    info = resolve_timezone("Europe/Berlin", datetime(2026, 1, 15, 12, tzinfo=UTC))
    assert info.abbreviation == "CET"
    assert info.offset == "UTC+01:00"
    assert "CET" in info.label


def test_timezone_cest_in_summer():
    info = resolve_timezone("Europe/Berlin", datetime(2026, 7, 15, 12, tzinfo=UTC))
    assert info.abbreviation == "CEST"
    assert info.offset == "UTC+02:00"


def test_timezone_invalid_falls_back_to_utc():
    info = resolve_timezone("Not/AZone")
    assert info.iana == "UTC"


# ---- Bounded recording ----------------------------------------------------- #

ROOM = "sensor.kuhlhaus_1_temperatur"


async def _unit_with(client, assignments):
    resp = await client.post(
        "/api/storage-units",
        json={"name": "KH", "upper_limit_c": 8, "assignments": assignments},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_min_delta_suppresses_small_changes(app_client):
    await _unit_with(app_client, [{"role": "room_temperature", "entity_id": ROOM}])
    c = get_collector(app_client)
    base = datetime(2026, 6, 23, 10, 0, tzinfo=UTC)
    await c.handle_state(ROOM, ha_state(ROOM, "5.00", last_updated=base.isoformat()), SampleSource.live_websocket)
    # +0.05 < 0.1 default delta -> suppressed
    await c.handle_state(ROOM, ha_state(ROOM, "5.05", last_updated=(base + timedelta(minutes=1)).isoformat()), SampleSource.live_websocket)
    # +0.12 from last STORED (5.00) -> stored
    await c.handle_state(ROOM, ha_state(ROOM, "5.12", last_updated=(base + timedelta(minutes=2)).isoformat()), SampleSource.live_websocket)
    factory = db_module.get_session_factory()
    async with factory() as s:
        count = await s.scalar(select(func.count()).select_from(SensorSample))
    assert count == 2


@pytest.mark.asyncio
async def test_unavailable_transition_recorded_once(app_client):
    await _unit_with(app_client, [{"role": "room_temperature", "entity_id": ROOM}])
    c = get_collector(app_client)
    base = datetime(2026, 6, 23, 10, 0, tzinfo=UTC)
    await c.handle_state(ROOM, ha_state(ROOM, "5.0", last_updated=base.isoformat()), SampleSource.live_websocket)
    await c.handle_state(ROOM, ha_state(ROOM, "unavailable", last_updated=(base + timedelta(minutes=1)).isoformat()), SampleSource.live_websocket)
    # repeated unavailable -> not stored again
    await c.handle_state(ROOM, ha_state(ROOM, "unavailable", last_updated=(base + timedelta(minutes=2)).isoformat()), SampleSource.live_websocket)
    factory = db_module.get_session_factory()
    async with factory() as s:
        qs = (await s.scalars(select(SensorSample.quality).order_by(SensorSample.event_timestamp))).all()
    assert qs == ["valid", "unavailable"]


@pytest.mark.asyncio
async def test_binary_role_stores_changes_only(app_client):
    await _unit_with(
        app_client,
        [
            {"role": "room_temperature", "entity_id": ROOM},
            {"role": "compressor", "entity_id": "binary_sensor.komp"},
        ],
    )
    c = get_collector(app_client)
    base = datetime(2026, 6, 23, 10, 0, tzinfo=UTC)
    K = "binary_sensor.komp"
    await c.handle_state(K, ha_state(K, "on", unit=None, last_updated=base.isoformat()), SampleSource.live_websocket)
    await c.handle_state(K, ha_state(K, "on", unit=None, last_updated=(base + timedelta(minutes=1)).isoformat()), SampleSource.live_websocket)
    await c.handle_state(K, ha_state(K, "off", unit=None, last_updated=(base + timedelta(minutes=2)).isoformat()), SampleSource.live_websocket)
    from app.models import StateSample

    factory = db_module.get_session_factory()
    async with factory() as s:
        count = await s.scalar(select(func.count()).select_from(StateSample))
    assert count == 2  # on, off (repeated on suppressed)


# ---- Aggregation + retention ----------------------------------------------- #


async def _insert_raw(unit, samples):
    factory = db_module.get_session_factory()
    aid = unit["assignments"][0]["id"]
    async with factory() as s:
        for ts, value in samples:
            s.add(
                SensorSample(
                    storage_unit_id=unit["id"], entity_assignment_id=aid,
                    entity_id=ROOM, role="room_temperature", event_timestamp=ts,
                    received_timestamp=ts, raw_value=str(value), numeric_value=value,
                    normalized_value_c=value, original_unit="°C", quality="valid",
                    source=SampleSource.live_websocket.value,
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_aggregation_15min_and_hourly(app_client):
    unit = await _unit_with(app_client, [{"role": "room_temperature", "entity_id": ROOM}])
    base = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
    # 4 samples within one 15-min bucket
    await _insert_raw(unit, [(base + timedelta(minutes=m), 5.0 + m * 0.1) for m in (0, 5, 10, 14)])
    now = base + timedelta(hours=2)
    factory = db_module.get_session_factory()
    async with factory() as s:
        n15 = await aggregate(s, "15min", now)
        nh = await aggregate(s, "hourly", now)
        await s.commit()
        rows = (await s.scalars(select(SensorAggregate))).all()
    assert n15 == 1 and nh == 1
    agg15 = next(a for a in rows if a.tier == "15min")
    assert agg15.sample_count == 4 and agg15.valid_count == 4
    # values 5.0, 5.5, 6.0, 6.4
    assert abs(agg15.min_c - 5.0) < 1e-9 and abs(agg15.max_c - 6.4) < 1e-9


@pytest.mark.asyncio
async def test_cleanup_raw_guarded_by_aggregates(app_client):
    unit = await _unit_with(app_client, [{"role": "room_temperature", "entity_id": ROOM}])
    old = datetime.now(UTC) - timedelta(days=800)
    await _insert_raw(unit, [(old + timedelta(minutes=m), 5.0) for m in (0, 5, 10, 14)])
    factory = db_module.get_session_factory()

    # Without aggregates covering the cutoff, raw cleanup must be a no-op.
    async with factory() as s:
        deleted = await cleanup_raw(s, retention_days=730, now=datetime.now(UTC))
    assert deleted == 0
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(SensorSample)) == 4

    # After aggregating, cleanup may delete the old raw rows.
    async with factory() as s:
        await aggregate(s, "15min", datetime.now(UTC))
        await s.commit()
        deleted = await cleanup_raw(s, retention_days=730, now=datetime.now(UTC))
    assert deleted == 4
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(SensorSample)) == 0
        # The aggregate (and thus the history) survives.
        assert await s.scalar(select(func.count()).select_from(SensorAggregate)) >= 1


@pytest.mark.asyncio
async def test_cleanup_never_touches_incidents(app_client):
    unit = await _unit_with(app_client, [{"role": "room_temperature", "entity_id": ROOM}])
    factory = db_module.get_session_factory()
    async with factory() as s:
        s.add(Incident(storage_unit_id=unit["id"], type="temperature_high",
                       state="active_violation", opened_at=datetime.now(UTC) - timedelta(days=900)))
        await s.commit()
    async with factory() as s:
        await cleanup_raw(s, retention_days=1, now=datetime.now(UTC))
        await cleanup_aggregates(s, "15min", 1, datetime.now(UTC))
        count = await s.scalar(select(func.count()).select_from(Incident))
    assert count == 1  # incidents are never deleted by maintenance


# ---- Storage thresholds ---------------------------------------------------- #


def test_storage_usage_levels(tmp_path):
    (tmp_path / "storage-controller.db").write_bytes(b"x" * 800)
    warn = storage_usage(tmp_path, budget=1000, warn_pct=70, crit_pct=85, emerg_pct=95)
    assert warn.level == "warning"  # 80% of budget
    assert warn.database_bytes == 800

    (tmp_path / "storage-controller.db").write_bytes(b"x" * 970)
    emerg = storage_usage(tmp_path, budget=1000, warn_pct=70, crit_pct=85, emerg_pct=95)
    assert emerg.level == "emergency"  # 97%


@pytest.mark.asyncio
async def test_maintenance_status_endpoint(app_client):
    resp = await app_client.get("/api/maintenance/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["level"] in ("ok", "warning", "critical", "emergency")
    assert "app_total_bytes" in body
    assert any(c["name"] == "database" for c in body["categories"])
