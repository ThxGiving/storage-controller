from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import db as db_module
from app.incident_engine import DefrostSettings, IncidentEngine, UnitReading
from app.models import DefrostCycle, Incident, IncidentType

T0 = datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)


def _ds(**over) -> DefrostSettings:
    base = dict(
        enabled=True,
        max_defrost_seconds=1800,
        pre_correlation_seconds=300,
        post_recovery_seconds=1800,
        max_room_c=12.0,
        max_evaporator_c=20.0,
        recovery_target_c=8.0,
        max_recovery_seconds=3600,
        excursions_visible=False,
        abnormal_creates_incident=True,
    )
    base.update(over)
    return DefrostSettings(**base)


def _r(uid, now, *, value, defrost_on, quality="valid", evap=None, ds=None):
    return UnitReading(
        storage_unit_id=uid, now=now, connected=True, has_room=True, room_exists=True,
        quality=quality, normalized_c=value, last_update=now, defrost_on=defrost_on,
        lower=0.0, upper=8.0, warning_margin=0.5, violation_delay=900,
        recovery_delay=300, offline_delay=600, evaporator_c=evap,
        defrost_entity_id="switch.kh_defrost", defrost=ds if ds is not None else _ds(),
    )


def _engine(client):
    return client._app.state.incident_engine  # type: ignore[attr-defined]


async def _make_unit(client):
    resp = await client.post(
        "/api/storage-units",
        json={
            "name": "TK",
            "lower_limit_c": -25.0,
            "upper_limit_c": 8.0,
            "assignments": [
                {"role": "room_temperature", "entity_id": "sensor.kh_temp"},
                {"role": "defrost", "entity_id": "switch.kh_defrost"},
            ],
        },
    )
    return resp.json()


async def _cycles(uid):
    factory = db_module.get_session_factory()
    async with factory() as s:
        return (await s.scalars(select(DefrostCycle).where(DefrostCycle.storage_unit_id == uid))).all()


async def _incidents(uid):
    factory = db_module.get_session_factory()
    async with factory() as s:
        return (await s.scalars(select(Incident).where(Incident.storage_unit_id == uid))).all()


async def _feed(eng, readings):
    for r in readings:
        await eng.evaluate_readings([r], connected=True)


@pytest.mark.asyncio
async def test_normal_defrost_with_expected_excursion_no_temperature_incident(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=5), value=10.0, defrost_on=True),   # >8 <12 -> expected
        _r(uid, T0 + timedelta(minutes=10), value=10.0, defrost_on=False),  # recovering
        _r(uid, T0 + timedelta(minutes=15), value=7.0, defrost_on=False),   # <=8 target -> completed
    ])
    incs = await _incidents(uid)
    assert not any(i.type == IncidentType.temperature_high.value for i in incs)
    cycles = await _cycles(uid)
    assert len(cycles) == 1
    assert cycles[0].status == "completed"
    assert cycles[0].classification == "expected_defrost_excursion"
    assert cycles[0].peak_room_temperature_c == 10.0


@pytest.mark.asyncio
async def test_normal_defrost_without_excursion(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=5.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=8), value=5.0, defrost_on=False),
        _r(uid, T0 + timedelta(minutes=12), value=4.0, defrost_on=False),  # <=8 -> completed
    ])
    cycles = await _cycles(uid)
    assert cycles[0].status == "completed"
    assert cycles[0].classification == "expected_defrost"
    assert not await _incidents(uid)


@pytest.mark.asyncio
async def test_defrost_duration_exceeded_creates_abnormal(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=31), value=6.0, defrost_on=True),  # > 30 min
    ])
    incs = await _incidents(uid)
    assert any(i.type == IncidentType.abnormal_defrost.value for i in incs)
    assert (await _cycles(uid))[0].status == "abnormal"


@pytest.mark.asyncio
async def test_room_envelope_exceeded_coexists_with_temperature_incident(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=5), value=13.0, defrost_on=True),  # > 12 envelope
    ])
    types = {i.type for i in await _incidents(uid)}
    assert IncidentType.abnormal_defrost.value in types
    assert IncidentType.temperature_high.value in types  # coexist, not suppressed


@pytest.mark.asyncio
async def test_recovery_timeout(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=5), value=10.0, defrost_on=False),   # recovering
        _r(uid, T0 + timedelta(minutes=70), value=10.0, defrost_on=False),  # > 60 min, not recovered
    ])
    assert any(i.type == IncidentType.recovery_timeout.value for i in await _incidents(uid))
    assert (await _cycles(uid))[0].classification == "recovery_timeout"


@pytest.mark.asyncio
async def test_pre_existing_high_not_suppressed_by_defrost(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=9.0, defrost_on=False),                    # high before defrost
        _r(uid, T0 + timedelta(minutes=16), value=9.0, defrost_on=False),  # confirmed
        _r(uid, T0 + timedelta(minutes=20), value=10.0, defrost_on=True),  # defrost starts
    ])
    highs = [i for i in await _incidents(uid) if i.type == IncidentType.temperature_high.value]
    assert len(highs) == 1
    assert highs[0].state == "active_violation"  # retained, not suppressed


@pytest.mark.asyncio
async def test_no_defrost_entity_uses_normal_logic(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    # defrost evaluation disabled -> a high peak is a normal temperature incident
    r = _r(uid, T0, value=9.0, defrost_on=None, ds=_ds(enabled=False))
    await eng.evaluate_readings([r], connected=True)
    assert any(i.type == IncidentType.temperature_high.value for i in await _incidents(uid))
    assert not await _cycles(uid)


@pytest.mark.asyncio
async def test_restart_no_duplicate_cycle(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await eng.evaluate_readings([_r(uid, T0, value=6.0, defrost_on=True)], connected=True)
    fresh = IncidentEngine(db_module.get_session_factory())
    await fresh.evaluate_readings(
        [_r(uid, T0 + timedelta(minutes=5), value=6.0, defrost_on=True)], connected=True
    )
    assert len(await _cycles(uid)) == 1  # continued, not duplicated


@pytest.mark.asyncio
async def test_missing_data_during_defrost_not_classified_expected(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=5), value=None, quality="unavailable", defrost_on=True),
    ])
    # Sensor incident fires; cycle is not silently classified safe.
    assert any(i.type == IncidentType.sensor_unavailable.value for i in await _incidents(uid))
