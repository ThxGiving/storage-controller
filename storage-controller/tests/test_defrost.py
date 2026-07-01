from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import db as db_module
from app.incident_engine import (
    DefrostSettings,
    IncidentEngine,
    LearnedEnvelope,
    UnitReading,
)
from app.models import DefrostCycle, Incident, IncidentType

T0 = datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)


def _env(**over) -> LearnedEnvelope:
    base = dict(
        max_room_peak_c=12.0,
        max_evaporator_peak_c=20.0,
        max_defrost_seconds=1800,
        max_recovery_seconds=3600,
    )
    base.update(over)
    return LearnedEnvelope(**base)


def _ds(*, learned: bool = True, **over) -> DefrostSettings:
    # ``learned`` mirrors an APPROVED model existing — only then may excursions be
    # suppressed. Recovery target equals the unit's upper safety limit.
    base = dict(
        enabled=True,
        recovery_target_c=8.0,
        abnormal_creates_incident=True,
        learned=_env() if learned else None,
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
async def test_excursion_not_suppressed_without_approved_model(app_client):
    """Toggle on but NO approved learned model -> excursion stays a real incident,
    flagged potentially-defrost-related (never auto-suppressed)."""
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    no_model = _ds(learned=False)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True, ds=no_model),
        _r(uid, T0 + timedelta(minutes=5), value=10.0, defrost_on=True, ds=no_model),  # >8
    ])
    highs = [i for i in await _incidents(uid) if i.type == IncidentType.temperature_high.value]
    assert len(highs) == 1  # excursion is a real incident, not suppressed
    assert highs[0].defrost_overlap is True  # marked potentially-defrost-related
    cycles = await _cycles(uid)
    assert cycles[0].classification != "expected_defrost_excursion"


@pytest.mark.asyncio
async def test_freezer_without_upper_limit_completes_via_baseline(app_client):
    """A freezer with only a lower limit (no upper) must still complete a cycle:
    recovery falls back to the pre-defrost baseline instead of never finishing."""
    resp = await app_client.post(
        "/api/storage-units",
        json={
            "name": "TK",
            "lower_limit_c": -25.0,  # only a lower limit; no upper
            "assignments": [
                {"role": "room_temperature", "entity_id": "sensor.tk_temp"},
                {"role": "defrost", "entity_id": "switch.tk_defrost"},
            ],
        },
    )
    uid = resp.json()["id"]
    eng = _engine(app_client)

    def rr(now, *, value, defrost_on):
        return UnitReading(
            storage_unit_id=uid, now=now, connected=True, has_room=True, room_exists=True,
            quality="valid", normalized_c=value, last_update=now, defrost_on=defrost_on,
            lower=-25.0, upper=None, warning_margin=0.5, violation_delay=900,
            recovery_delay=300, offline_delay=600, evaporator_c=None,
            defrost_entity_id="switch.tk_defrost",
            defrost=_ds(learned=False, recovery_target_c=None),
        )

    await _feed(eng, [
        rr(T0, value=-20.0, defrost_on=True),                       # baseline -20
        rr(T0 + timedelta(minutes=4), value=-10.0, defrost_on=True),  # peak -10
        rr(T0 + timedelta(minutes=8), value=-12.0, defrost_on=False),  # recovering
        rr(T0 + timedelta(minutes=20), value=-20.5, defrost_on=False),  # <= -20+1 -> done
    ])
    cycles = await _cycles(uid)
    assert len(cycles) == 1
    assert cycles[0].status == "completed"
    assert cycles[0].classification == "expected_defrost"


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
async def test_recovery_timeout_suppressed_when_room_data_missing(app_client):
    """A room-sensor gap through the whole recovery window must NOT be reported as
    a recovery_timeout defrost anomaly (that is a data-availability problem with
    its own incident). The cycle closes as `incomplete` so it never hangs open."""
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=5), value=10.0, defrost_on=False),  # recovering
        # sensor unavailable past the recovery limit — cannot judge recovery
        _r(uid, T0 + timedelta(minutes=70), value=None, quality="unavailable", defrost_on=False),
    ])
    assert not any(
        i.type == IncidentType.recovery_timeout.value for i in await _incidents(uid)
    )
    cycle = (await _cycles(uid))[0]
    assert cycle.status == "incomplete"
    assert cycle.recovered_at is None


@pytest.mark.asyncio
async def test_abnormal_defrost_auto_closes_after_recovery(app_client):
    """An abnormal_defrost incident is opened directly in active_violation; once the
    defrost is over and the room is back within limits the engine closes it itself
    (it has no per-condition tick to advance it otherwise)."""
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=31), value=6.0, defrost_on=True),   # >30 min -> abnormal
        _r(uid, T0 + timedelta(minutes=40), value=5.0, defrost_on=False),  # defrost off, <=8 -> recovered
    ])
    incs = [i for i in await _incidents(uid) if i.type == IncidentType.abnormal_defrost.value]
    assert len(incs) == 1
    assert incs[0].state == "closed"
    assert incs[0].closed_at is not None


@pytest.mark.asyncio
async def test_abnormal_defrost_stays_open_until_recovered(app_client):
    """While the room is still above the upper limit the anomaly must stay open."""
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=31), value=6.0, defrost_on=True),   # abnormal
        _r(uid, T0 + timedelta(minutes=40), value=10.0, defrost_on=False),  # off but still >8
    ])
    incs = [i for i in await _incidents(uid) if i.type == IncidentType.abnormal_defrost.value]
    assert len(incs) == 1
    assert incs[0].state == "active_violation"


@pytest.mark.asyncio
async def test_recovery_timeout_auto_closes_after_recovery(app_client):
    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)
    await _feed(eng, [
        _r(uid, T0, value=6.0, defrost_on=True),
        _r(uid, T0 + timedelta(minutes=5), value=10.0, defrost_on=False),   # recovering
        _r(uid, T0 + timedelta(minutes=70), value=10.0, defrost_on=False),  # >60 min -> recovery_timeout
        _r(uid, T0 + timedelta(minutes=80), value=7.0, defrost_on=False),   # <=8 -> recovered
    ])
    incs = [i for i in await _incidents(uid) if i.type == IncidentType.recovery_timeout.value]
    assert len(incs) == 1
    assert incs[0].state == "closed"


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
async def test_reconstructed_cycle_on_restart_while_defrosting(app_client):
    """If defrost was already 'on' (persisted) well before the first observation,
    the cycle start is reconstructed from the prior sample, not fabricated as now."""
    from app.models import EntityAssignment, EntityRole, StateSample

    unit = await _make_unit(app_client)
    uid = unit["id"]
    eng = _engine(app_client)

    factory = db_module.get_session_factory()
    async with factory() as s:
        aid = await s.scalar(
            select(EntityAssignment.id).where(
                EntityAssignment.storage_unit_id == uid,
                EntityAssignment.role == EntityRole.defrost.value,
            )
        )
        # A persisted 'on' sample from 20 minutes ago (before any observation).
        s.add(
            StateSample(
                storage_unit_id=uid, entity_assignment_id=aid,
                entity_id="switch.kh_defrost", role="defrost",
                event_timestamp=T0 - timedelta(minutes=20),
                received_timestamp=T0 - timedelta(minutes=20),
                raw_state="on", normalized_bool=True, quality="valid",
                source="reconcile", source_context_id=None,
            )
        )
        await s.commit()

    reading = UnitReading(
        storage_unit_id=uid, now=T0, connected=True, has_room=True, room_exists=True,
        quality="valid", normalized_c=6.0, last_update=T0, defrost_on=True,
        lower=0.0, upper=8.0, warning_margin=0.5, violation_delay=900,
        recovery_delay=300, offline_delay=600, evaporator_c=None,
        defrost_entity_id="switch.kh_defrost", defrost_assignment_id=aid,
        defrost=_ds(learned=False),
    )
    await eng.evaluate_readings([reading], connected=True)

    cycles = await _cycles(uid)
    assert len(cycles) == 1
    assert cycles[0].reconstructed is True
    assert cycles[0].triggering_rule == "reconstructed_on_restart"
    # started_at reconstructed to ~20 min ago, not 'now'
    assert _utc_naive(cycles[0].started_at) < T0 - timedelta(minutes=10)


def _utc_naive(ts):
    from datetime import timezone as _tz
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=_tz.utc)


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
