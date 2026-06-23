from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app import db as db_module
from app.models import SampleSource, SensorSample
from .conftest import get_collector, ha_state, set_entities

ROOM = "sensor.kuhlhaus_1_temperatur"


async def _make_unit(client, **overrides):
    payload = {
        "name": "Kühlhaus 1",
        "lower_limit_c": 0.0,
        "upper_limit_c": 8.0,
        "plausible_min_c": -30.0,
        "plausible_max_c": 40.0,
        "assignments": [{"role": "room_temperature", "entity_id": ROOM}],
    }
    payload.update(overrides)
    resp = await client.post("/api/storage-units", json=payload)
    assert resp.status_code == 201
    return resp.json()


async def _count_samples() -> int:
    factory = db_module.get_session_factory()
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(SensorSample)))


async def _samples():
    factory = db_module.get_session_factory()
    async with factory() as session:
        return (
            await session.execute(
                select(
                    SensorSample.normalized_value_c,
                    SensorSample.quality,
                    SensorSample.source,
                    SensorSample.source_context_id,
                ).order_by(SensorSample.event_timestamp)
            )
        ).all()


@pytest.mark.asyncio
async def test_records_room_temperature_sample(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    stored = await collector.handle_state(
        ROOM,
        ha_state(ROOM, "5.90000009536743", last_updated="2026-06-23T10:00:00+00:00", context_id="ctx1"),
        SampleSource.live_websocket,
    )
    assert stored == 1
    rows = await _samples()
    assert len(rows) == 1
    val, quality, source, ctx = rows[0]
    assert abs(val - 5.9) < 1e-6
    assert quality == "valid"
    assert source == "live_websocket"
    assert ctx == "ctx1"


@pytest.mark.asyncio
async def test_deduplicates_same_timestamp(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    s = ha_state(ROOM, "5.5", last_updated="2026-06-23T10:00:00+00:00")
    assert await collector.handle_state(ROOM, s, SampleSource.live_websocket) == 1
    assert await collector.handle_state(ROOM, s, SampleSource.live_websocket) == 0
    assert await _count_samples() == 1


@pytest.mark.asyncio
async def test_out_of_order_skipped(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    await collector.handle_state(
        ROOM, ha_state(ROOM, "6.0", last_updated="2026-06-23T10:05:00+00:00"),
        SampleSource.live_websocket,
    )
    # An older event must not be stored after a newer one.
    stored = await collector.handle_state(
        ROOM, ha_state(ROOM, "5.0", last_updated="2026-06-23T10:00:00+00:00"),
        SampleSource.live_websocket,
    )
    assert stored == 0
    assert await _count_samples() == 1


@pytest.mark.asyncio
async def test_unavailable_recorded_as_gap_not_zero(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    await collector.handle_state(
        ROOM, ha_state(ROOM, "unavailable", last_updated="2026-06-23T10:10:00+00:00"),
        SampleSource.live_websocket,
    )
    rows = await _samples()
    assert len(rows) == 1
    val, quality, _, _ = rows[0]
    assert quality == "unavailable"
    assert val is None  # never zeroed


@pytest.mark.asyncio
async def test_reconcile_is_idempotent(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    states = [ha_state(ROOM, "4.2", last_updated="2026-06-23T09:00:00+00:00")]
    assert await collector.reconcile(states) == 1
    assert await collector.reconcile(states) == 0
    assert await _count_samples() == 1


@pytest.mark.asyncio
async def test_persistence_high_water_mark_survives_index_rebuild(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    await collector.handle_state(
        ROOM, ha_state(ROOM, "3.0", last_updated="2026-06-23T08:00:00+00:00"),
        SampleSource.live_websocket,
    )
    # Simulate a restart: rebuild the index (re-seeds the high-water mark from DB).
    await collector.refresh_index()
    # An equal/older event is still skipped after the rebuild.
    stored = await collector.handle_state(
        ROOM, ha_state(ROOM, "3.0", last_updated="2026-06-23T08:00:00+00:00"),
        SampleSource.live_websocket,
    )
    assert stored == 0
    assert await _count_samples() == 1


@pytest.mark.asyncio
async def test_heartbeat_creates_sample_for_stable_value(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    manager = app_client._app.state.ha_manager  # type: ignore[attr-defined]
    set_entities(
        app_client,
        [{"entity_id": ROOM, "state": "5.0", "attributes": {"unit_of_measurement": "°C"}}],
    )
    # No prior sample => heartbeat is immediately due.
    stored = await collector.heartbeat_tick(manager.get_entity)
    assert stored == 1
    rows = await _samples()
    assert rows[0][2] == "heartbeat"
    assert abs(rows[0][0] - 5.0) < 1e-9


@pytest.mark.asyncio
async def test_only_assigned_entities_recorded(app_client):
    await _make_unit(app_client)
    collector = get_collector(app_client)
    stored = await collector.handle_state(
        "sensor.some_other_entity",
        ha_state("sensor.some_other_entity", "1.0", last_updated="2026-06-23T10:00:00+00:00"),
        SampleSource.live_websocket,
    )
    assert stored == 0
    assert await _count_samples() == 0
