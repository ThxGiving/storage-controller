from __future__ import annotations

import pytest

from .conftest import set_entities

STATES = [
    {
        "entity_id": "sensor.kuhlhaus_1_temperatur",
        "state": "6.1",
        "attributes": {
            "friendly_name": "Kühlhaus 1 Temperatur",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
        },
        "last_changed": "2026-06-22T10:00:00+00:00",
    },
    {
        "entity_id": "switch.kuhlhaus_1_licht",
        "state": "off",
        "attributes": {"friendly_name": "Kühlhaus 1 Licht"},
    },
    {
        "entity_id": "sensor.broken",
        "state": "unavailable",
        "attributes": {"friendly_name": "Broken Sensor"},
    },
]


@pytest.mark.asyncio
async def test_entities_listed_and_parsed(app_client):
    set_entities(app_client, STATES)
    resp = await app_client.get("/api/home-assistant/entities")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3
    temp = next(e for e in items if e["entity_id"] == "sensor.kuhlhaus_1_temperatur")
    assert temp["domain"] == "sensor"
    assert temp["friendly_name"] == "Kühlhaus 1 Temperatur"
    assert temp["unit_of_measurement"] == "°C"
    assert temp["available"] is True


@pytest.mark.asyncio
async def test_unavailable_state_not_zeroed(app_client):
    set_entities(app_client, STATES)
    resp = await app_client.get("/api/home-assistant/entities?search=broken")
    items = resp.json()
    assert len(items) == 1
    assert items[0]["state"] == "unavailable"
    assert items[0]["available"] is False


@pytest.mark.asyncio
async def test_entity_search_filters(app_client):
    set_entities(app_client, STATES)
    resp = await app_client.get("/api/home-assistant/entities?search=licht")
    items = resp.json()
    assert len(items) == 1
    assert items[0]["entity_id"] == "switch.kuhlhaus_1_licht"


@pytest.mark.asyncio
async def test_entity_domain_filter(app_client):
    set_entities(app_client, STATES)
    resp = await app_client.get("/api/home-assistant/entities?domain=sensor")
    items = resp.json()
    assert {e["domain"] for e in items} == {"sensor"}
