from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import db as db_module
from app.incident_engine import UnitReading
from app.models import Incident

T0 = datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)


async def _make_unit(client):
    resp = await client.post(
        "/api/storage-units",
        json={
            "name": "Kühlhaus 1",
            "upper_limit_c": 8.0,
            "lower_limit_c": 0.0,
            "assignments": [
                {"role": "room_temperature", "entity_id": "sensor.kuhlhaus_1_temperatur"}
            ],
        },
    )
    return resp.json()


async def _open_incident(client, unit_id):
    eng = client._app.state.incident_engine  # type: ignore[attr-defined]
    reading = UnitReading(
        storage_unit_id=unit_id, now=T0, connected=True, has_room=True, room_exists=True,
        quality="valid", normalized_c=9.0, last_update=T0, defrost_on=None,
        lower=0.0, upper=8.0, warning_margin=0.5, violation_delay=900,
        recovery_delay=300, offline_delay=600,
    )
    await eng.evaluate_readings([reading], connected=True)
    factory = db_module.get_session_factory()
    async with factory() as session:
        inc = await session.scalar(select(Incident).where(Incident.storage_unit_id == unit_id))
    return inc.id


@pytest.mark.asyncio
async def test_list_and_get_incident(app_client):
    unit = await _make_unit(app_client)
    iid = await _open_incident(app_client, unit["id"])

    listed = await app_client.get("/api/incidents?state=open")
    assert listed.status_code == 200
    assert any(i["id"] == iid for i in listed.json())

    detail = await app_client.get(f"/api/incidents/{iid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["type"] == "temperature_high"
    assert body["storage_unit_name"] == "Kühlhaus 1"
    assert len(body["events"]) >= 1  # opened transition

    # DB-sourced timestamps must serialize UTC-aware (Z / +00:00) — the
    # UtcDateTime column type guarantees this so the frontend never misreads a
    # stored UTC instant as local time. Covers incident + nested event times.
    opened = body["opened_at"]
    assert opened.endswith("Z") or "+00:00" in opened
    evt_ts = body["events"][0]["timestamp"]
    assert evt_ts.endswith("Z") or "+00:00" in evt_ts


@pytest.mark.asyncio
async def test_acknowledge_and_document(app_client):
    unit = await _make_unit(app_client)
    iid = await _open_incident(app_client, unit["id"])

    resp = await app_client.patch(
        f"/api/incidents/{iid}",
        json={"acknowledge": True, "cause": "Tür offen", "corrective_action": "Tür geschlossen"},
        headers={"X-Remote-User-Name": "Sebastian"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["acknowledged_at"] is not None
    assert body["acknowledged_by"] == "Sebastian"
    assert body["cause"] == "Tür offen"
    assert body["corrective_action"] == "Tür geschlossen"
    assert any(e["kind"] == "doc" for e in body["events"])


@pytest.mark.asyncio
async def test_incident_not_found(app_client):
    resp = await app_client.get("/api/incidents/9999")
    assert resp.status_code == 404
    assert resp.json()["code"] == "incident_not_found"


@pytest.mark.asyncio
async def test_dashboard_includes_active_incident(app_client):
    unit = await _make_unit(app_client)
    await _open_incident(app_client, unit["id"])
    resp = await app_client.get("/api/dashboard")
    body = resp.json()
    assert body["summary"]["open_incidents"] >= 1
    assert body["summary"]["undocumented_incidents"] >= 1
    u = next(u for u in body["units"] if u["id"] == unit["id"])
    assert len(u["active_incidents"]) >= 1
    assert u["active_incidents"][0]["type"] == "temperature_high"
