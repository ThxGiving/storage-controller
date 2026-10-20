from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import db as db_module
from app.incident_engine import UnitReading
from app.models import Incident, IncidentState, IncidentType

T0 = datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)


def _engine(client):
    return client._app.state.incident_engine  # type: ignore[attr-defined]


async def _make_unit(client, **over):
    payload = {
        "name": "Kühlhaus 1",
        "lower_limit_c": 0.0,
        "upper_limit_c": 8.0,
        "violation_delay_seconds": 900,
        "recovery_delay_seconds": 300,
        "offline_delay_seconds": 600,
        "assignments": [
            {"role": "room_temperature", "entity_id": "sensor.kuhlhaus_1_temperatur"}
        ],
    }
    payload.update(over)
    resp = await client.post("/api/storage-units", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _reading(unit_id, now, *, value=None, quality="valid", connected=True, defrost=None,
             last_update=None, lower=0.0, upper=8.0, link_up=None):
    return UnitReading(
        storage_unit_id=unit_id,
        now=now,
        connected=connected,
        has_room=True,
        room_exists=True,
        quality=quality,
        normalized_c=value,
        last_update=last_update if last_update is not None else now,
        defrost_on=defrost,
        lower=lower,
        upper=upper,
        warning_margin=0.5,
        violation_delay=900,
        recovery_delay=300,
        offline_delay=600,
        link_up=link_up,
    )


async def _incidents(unit_id=None):
    factory = db_module.get_session_factory()
    async with factory() as session:
        stmt = select(Incident).order_by(Incident.id)
        if unit_id is not None:
            stmt = stmt.where(Incident.storage_unit_id == unit_id)
        return (await session.scalars(stmt)).all()


@pytest.mark.asyncio
async def test_high_temperature_full_lifecycle(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)

    # Crossing -> pending
    await eng.evaluate_readings([_reading(uid, T0, value=9.0)], connected=True)
    incs = await _incidents(uid)
    assert len(incs) == 1
    assert incs[0].type == IncidentType.temperature_high.value
    assert incs[0].state == IncidentState.pending_violation.value
    assert incs[0].extreme_value_c == 9.0

    # Still high but before violation_delay -> stays pending; extreme rises
    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=10), value=9.5)], connected=True
    )
    incs = await _incidents(uid)
    assert incs[0].state == IncidentState.pending_violation.value
    assert incs[0].extreme_value_c == 9.5

    # After violation_delay -> active
    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=15), value=9.2)], connected=True
    )
    incs = await _incidents(uid)
    assert incs[0].state == IncidentState.active_violation.value
    assert incs[0].confirmed_at is not None

    # Back in range -> recovering
    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=20), value=7.0)], connected=True
    )
    incs = await _incidents(uid)
    assert incs[0].state == IncidentState.recovering.value

    # After recovery_delay -> closed
    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=26), value=7.0)], connected=True
    )
    incs = await _incidents(uid)
    assert incs[0].state == IncidentState.closed.value
    assert incs[0].closed_at is not None
    # Only ever one incident for this crossing.
    assert len(incs) == 1


@pytest.mark.asyncio
async def test_single_crossing_does_not_create_repeated_incidents(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    for m in (0, 5, 16, 30):
        await eng.evaluate_readings(
            [_reading(uid, T0 + timedelta(minutes=m), value=9.0)], connected=True
        )
    incs = await _incidents(uid)
    assert len(incs) == 1  # one ongoing incident, not one per tick


@pytest.mark.asyncio
async def test_brief_excursion_recovers_without_confirmation(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await eng.evaluate_readings([_reading(uid, T0, value=9.0)], connected=True)
    # recovers after 2 min (< 15 min violation delay)
    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=2), value=7.0)], connected=True
    )
    incs = await _incidents(uid)
    assert incs[0].state == IncidentState.recovering.value
    assert incs[0].confirmed_at is None  # never became an active violation


@pytest.mark.asyncio
async def test_sensor_unavailable_incident(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await eng.evaluate_readings(
        [_reading(uid, T0, value=None, quality="unavailable")], connected=True
    )
    incs = await _incidents(uid)
    assert any(i.type == IncidentType.sensor_unavailable.value for i in incs)


@pytest.mark.asyncio
async def test_sensor_invalid_incident(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await eng.evaluate_readings(
        [_reading(uid, T0, value=None, quality="invalid")], connected=True
    )
    incs = await _incidents(uid)
    assert any(i.type == IncidentType.sensor_invalid.value for i in incs)


@pytest.mark.asyncio
async def test_defrost_overlap_marked(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await eng.evaluate_readings([_reading(uid, T0, value=9.0, defrost=True)], connected=True)
    incs = await _incidents(uid)
    assert incs[0].defrost_overlap is True


@pytest.mark.asyncio
async def test_unknown_while_unavailable_freezes_temperature_incident(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    # Confirm a high incident first.
    await eng.evaluate_readings([_reading(uid, T0, value=9.0)], connected=True)
    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=16), value=9.0)], connected=True
    )
    high = [i for i in await _incidents(uid) if i.type == IncidentType.temperature_high.value][0]
    assert high.state == IncidentState.active_violation.value
    # Now sensor goes unavailable -> temperature incident must NOT auto-recover.
    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=30), value=None, quality="unavailable")],
        connected=True,
    )
    high = [i for i in await _incidents(uid) if i.type == IncidentType.temperature_high.value][0]
    assert high.state == IncidentState.active_violation.value  # frozen, not recovering


@pytest.mark.asyncio
async def test_restart_during_incident_continues_not_duplicates(app_client):
    """A fresh engine (simulating a restart) re-evaluates the same open incident
    rather than creating a new one."""
    from app.incident_engine import IncidentEngine

    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await eng.evaluate_readings([_reading(uid, T0, value=9.0)], connected=True)

    fresh = IncidentEngine(db_module.get_session_factory())
    await fresh.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=16), value=9.0)], connected=True
    )
    incs = await _incidents(uid)
    assert len(incs) == 1
    assert incs[0].state == IncidentState.active_violation.value


@pytest.mark.asyncio
async def test_steady_temperature_is_not_stale(app_client):
    # ESPHome drops unchanged values, so HA's timestamp stands still while the
    # room holds a steady temperature (observed up to ~25 min). Not a fault.
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    for minutes in (0, 15, 30, 40):
        await eng.evaluate_readings(
            [_reading(uid, T0 + timedelta(minutes=minutes), value=4.0, last_update=T0)],
            connected=True,
        )
    assert [i for i in await _incidents(uid) if i.type == IncidentType.sensor_stale.value] == []


@pytest.mark.asyncio
async def test_stale_after_long_silence(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    for minutes in (46, 56):
        await eng.evaluate_readings(
            [_reading(uid, T0 + timedelta(minutes=minutes), value=4.0, last_update=T0)],
            connected=True,
        )
    stale = [i for i in await _incidents(uid) if i.type == IncidentType.sensor_stale.value]
    assert len(stale) == 1
    assert stale[0].state == IncidentState.active_violation.value


# --------------------------------------------------------------------------- #
# Connectivity entity (0.9.14): the controller link replaces the 45-min rule.
# --------------------------------------------------------------------------- #

ROOM = "sensor.kuhlhaus_1_temperatur"
LINK = "binary_sensor.kuhlhaus_1_modbus_verbunden"
LAST_READ = "sensor.kuhlhaus_1_letzte_abfrage"


def _types(incs, t):
    return [i for i in incs if i.type == t.value]


@pytest.mark.asyncio
async def test_constant_value_with_link_on_is_not_stale(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    # 55 min unchanged (2026-10-20: freezer at exactly −20.2 °C) — gateway connected.
    for minutes in (0, 46, 56, 120):
        await eng.evaluate_readings(
            [_reading(uid, T0 + timedelta(minutes=minutes), value=4.0, last_update=T0,
                      link_up=True)],
            connected=True,
        )
    incs = await _incidents(uid)
    assert _types(incs, IncidentType.sensor_stale) == []
    assert _types(incs, IncidentType.sensor_unavailable) == []


@pytest.mark.asyncio
async def test_link_off_raises_unavailable_after_offline_delay(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await eng.evaluate_readings([_reading(uid, T0, value=4.0, link_up=False)], connected=True)
    unav = _types(await _incidents(uid), IncidentType.sensor_unavailable)
    assert len(unav) == 1
    assert unav[0].state == IncidentState.pending_violation.value

    await eng.evaluate_readings(
        [_reading(uid, T0 + timedelta(minutes=11), value=4.0, last_update=T0, link_up=False)],
        connected=True,
    )
    incs = await _incidents(uid)
    unav = _types(incs, IncidentType.sensor_unavailable)
    assert unav[0].state == IncidentState.active_violation.value
    # Reported once, as unavailable — not additionally as stale.
    assert _types(incs, IncidentType.sensor_stale) == []

    # Link back: recovers and closes after the recovery delay.
    for minutes in (12, 18):
        await eng.evaluate_readings(
            [_reading(uid, T0 + timedelta(minutes=minutes), value=4.0, link_up=True)],
            connected=True,
        )
    unav = _types(await _incidents(uid), IncidentType.sensor_unavailable)
    assert unav[0].state == IncidentState.closed.value


@pytest.mark.asyncio
async def test_ha_disconnect_still_wins_over_link(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    for minutes in (0, 11):
        await eng.evaluate_readings(
            [_reading(uid, T0 + timedelta(minutes=minutes), value=4.0, connected=False,
                      link_up=False)],
            connected=False,
        )
    assert _types(await _incidents(uid), IncidentType.sensor_unavailable) == []


async def _run_at(app_client, monkeypatch, now, states):
    from app import incident_engine

    from .conftest import set_entities

    set_entities(app_client, states)
    monkeypatch.setattr(incident_engine, "_now", lambda: now)
    await _engine(app_client).run(
        app_client._app.state.ha_manager.get_entity, connected=True  # type: ignore[attr-defined]
    )


def _room_state(last_seen):
    ts = last_seen.isoformat()
    return {
        "entity_id": ROOM, "state": "4.0",
        "attributes": {"unit_of_measurement": "°C", "device_class": "temperature"},
        "last_changed": ts, "last_updated": ts, "last_reported": ts,
    }


async def _make_linked_unit(client, link_entity):
    return await _make_unit(client, assignments=[
        {"role": "room_temperature", "entity_id": ROOM},
        {"role": "connectivity", "entity_id": link_entity},
    ])


@pytest.mark.asyncio
async def test_binary_link_entity_from_ha_cache(app_client, monkeypatch):
    uid = (await _make_linked_unit(app_client, LINK))["id"]
    link_on = {"entity_id": LINK, "state": "on", "attributes": {}}
    for minutes in (50, 70):
        await _run_at(app_client, monkeypatch, T0 + timedelta(minutes=minutes),
                      [_room_state(T0), link_on])
    assert await _incidents(uid) == []

    for state in ("off", "unavailable"):
        await _run_at(app_client, monkeypatch, T0 + timedelta(minutes=80),
                      [_room_state(T0), {"entity_id": LINK, "state": state, "attributes": {}}])
    await _run_at(app_client, monkeypatch, T0 + timedelta(minutes=91),
                  [_room_state(T0), {"entity_id": LINK, "state": "unknown", "attributes": {}}])
    incs = await _incidents(uid)
    assert [i.type for i in incs] == [IncidentType.sensor_unavailable.value]
    assert incs[0].state == IncidentState.active_violation.value


@pytest.mark.asyncio
async def test_timestamp_link_entity(app_client, monkeypatch):
    # ESPHome text sensor with the last successful Modbus read (strftime %z).
    uid = (await _make_linked_unit(app_client, LAST_READ))["id"]

    def last_read(ts):
        return {"entity_id": LAST_READ, "state": ts, "attributes": {}}

    now = T0 + timedelta(minutes=60)
    fresh = (now - timedelta(seconds=30)).astimezone(
        timezone(timedelta(hours=2))).strftime("%Y-%m-%dT%H:%M:%S%z")
    await _run_at(app_client, monkeypatch, now, [_room_state(T0), last_read(fresh)])
    assert await _incidents(uid) == []

    # Last read 11 min ago (offline delay 10 min) → not connected.
    old = (now - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await _run_at(app_client, monkeypatch, now, [_room_state(T0), last_read(old)])
    incs = await _incidents(uid)
    assert [i.type for i in incs] == [IncidentType.sensor_unavailable.value]
    assert incs[0].state == IncidentState.pending_violation.value

    # Unparseable text stays "not connected"; confirmed after the offline delay.
    await _run_at(app_client, monkeypatch, now + timedelta(minutes=11),
                  [_room_state(T0), last_read("not a time")])
    incs = await _incidents(uid)
    assert [i.type for i in incs] == [IncidentType.sensor_unavailable.value]
    assert incs[0].state == IncidentState.active_violation.value


@pytest.mark.asyncio
async def test_missing_link_entity_does_not_crash(app_client, monkeypatch):
    uid = (await _make_linked_unit(app_client, LINK))["id"]
    await _run_at(app_client, monkeypatch, T0, [_room_state(T0)])
    assert [i.type for i in await _incidents(uid)] == [IncidentType.sensor_unavailable.value]
