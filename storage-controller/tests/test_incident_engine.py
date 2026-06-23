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
             last_update=None, lower=0.0, upper=8.0):
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
