from __future__ import annotations

import pytest

from .conftest import set_entities

ROOM = "sensor.kuhlhaus_1_temperatur"


async def _make_unit(client):
    resp = await client.post(
        "/api/storage-units",
        json={
            "name": "Kühlhaus 1",
            "lower_limit_c": 0.0,
            "upper_limit_c": 8.0,
            "warning_margin_c": 0.5,
            "assignments": [
                {"role": "room_temperature", "entity_id": ROOM},
                {"role": "compressor", "entity_id": "binary_sensor.kh1_kompressor"},
            ],
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_dashboard_structure_and_status(app_client):
    await _make_unit(app_client)
    set_entities(
        app_client,
        [
            {
                "entity_id": ROOM,
                "state": "6.1",
                "attributes": {"unit_of_measurement": "°C", "device_class": "temperature"},
            },
            {
                "entity_id": "binary_sensor.kh1_kompressor",
                "state": "on",
                "attributes": {},
            },
        ],
    )
    resp = await app_client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()

    assert body["summary"]["total"] == 1
    assert len(body["units"]) == 1
    unit = body["units"][0]
    assert unit["name"] == "Kühlhaus 1"
    # Not connected in tests (no token) => status disconnected, but room value present.
    assert unit["room"]["numeric_c"] == 6.1
    # Compressor chip present as an assigned operational role.
    roles = {r["role"]: r for r in unit["roles"]}
    assert "compressor" in roles
    assert roles["compressor"]["bool_value"] is True


@pytest.mark.asyncio
async def test_dashboard_empty(app_client):
    resp = await app_client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total"] == 0
    assert body["units"] == []


@pytest.mark.asyncio
async def test_dashboard_connectivity_chip_from_last_read_timestamp(app_client):
    from datetime import UTC, datetime, timedelta

    resp = await app_client.post(
        "/api/storage-units",
        json={
            "name": "Kühlhaus 2",
            "assignments": [
                {"role": "room_temperature", "entity_id": ROOM},
                {"role": "connectivity", "entity_id": "sensor.kh2_letzte_abfrage"},
            ],
        },
    )
    assert resp.status_code == 201
    fresh = (datetime.now(UTC) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S%z")
    set_entities(
        app_client,
        [
            {"entity_id": ROOM, "state": "-20.2", "attributes": {"unit_of_measurement": "°C"}},
            {"entity_id": "sensor.kh2_letzte_abfrage", "state": fresh, "attributes": {}},
        ],
    )
    unit = (await app_client.get("/api/dashboard")).json()["units"][0]
    link = next(r for r in unit["roles"] if r["role"] == "connectivity")
    assert link["bool_value"] is True
    assert link["quality"] == "valid"
