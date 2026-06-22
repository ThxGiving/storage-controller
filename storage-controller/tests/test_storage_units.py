from __future__ import annotations

import pytest

from .conftest import set_entities

ROOM = {
    "role": "room_temperature",
    "entity_id": "sensor.kuhlhaus_1_temperatur",
}


def unit_payload(**overrides):
    data = {
        "name": "Kühlhaus 1",
        "lower_limit_c": 0.0,
        "upper_limit_c": 8.0,
        "assignments": [ROOM],
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_create_and_get_unit(app_client):
    resp = await app_client.post("/api/storage-units", json=unit_payload())
    assert resp.status_code == 201
    unit = resp.json()
    assert unit["name"] == "Kühlhaus 1"
    assert [a["role"] for a in unit["assignments"]] == ["room_temperature"]

    got = await app_client.get(f"/api/storage-units/{unit['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == unit["id"]


@pytest.mark.asyncio
async def test_room_temperature_is_mandatory(app_client):
    resp = await app_client.post(
        "/api/storage-units", json=unit_payload(assignments=[])
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_optional_roles_assignable_freely(app_client):
    payload = unit_payload(
        assignments=[
            ROOM,
            {"role": "defrost", "entity_id": "switch.kuhlhaus_1_defrost"},
            {"role": "light", "entity_id": "switch.kuhlhaus_1_licht"},
        ]
    )
    resp = await app_client.post("/api/storage-units", json=payload)
    assert resp.status_code == 201
    roles = {a["role"] for a in resp.json()["assignments"]}
    assert roles == {"room_temperature", "defrost", "light"}


@pytest.mark.asyncio
async def test_duplicate_role_rejected(app_client):
    payload = unit_payload(
        assignments=[
            ROOM,
            {"role": "room_temperature", "entity_id": "sensor.other"},
        ]
    )
    resp = await app_client.post("/api/storage-units", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_limit_validation(app_client):
    resp = await app_client.post(
        "/api/storage-units", json=unit_payload(lower_limit_c=8.0, upper_limit_c=0.0)
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_unit(app_client):
    created = await app_client.post("/api/storage-units", json=unit_payload())
    uid = created.json()["id"]

    resp = await app_client.patch(
        f"/api/storage-units/{uid}", json={"name": "Kühlhaus Eins", "upper_limit_c": 6.0}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Kühlhaus Eins"
    assert resp.json()["upper_limit_c"] == 6.0


@pytest.mark.asyncio
async def test_delete_unit(app_client):
    created = await app_client.post("/api/storage-units", json=unit_payload())
    uid = created.json()["id"]
    resp = await app_client.delete(f"/api/storage-units/{uid}")
    assert resp.status_code == 204
    assert (await app_client.get(f"/api/storage-units/{uid}")).status_code == 404


@pytest.mark.asyncio
async def test_current_values_warns_on_missing_entity(app_client):
    created = await app_client.post("/api/storage-units", json=unit_payload())
    uid = created.json()["id"]

    resp = await app_client.get(f"/api/storage-units/{uid}/current")
    assert resp.status_code == 200
    room = resp.json()[0]
    assert room["exists"] is False
    assert "not found" in room["warning"].lower()


@pytest.mark.asyncio
async def test_current_values_reads_live_state(app_client):
    set_entities(
        app_client,
        [
            {
                "entity_id": "sensor.kuhlhaus_1_temperatur",
                "state": "6.1",
                "attributes": {"unit_of_measurement": "°C", "device_class": "temperature"},
            }
        ],
    )
    created = await app_client.post("/api/storage-units", json=unit_payload())
    uid = created.json()["id"]
    resp = await app_client.get(f"/api/storage-units/{uid}/current")
    room = resp.json()[0]
    assert room["state"] == "6.1"
    assert room["warning"] is None
