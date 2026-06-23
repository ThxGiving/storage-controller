"""Defrost/entity/event diagnostics + configurable value mappings."""

from __future__ import annotations

import pytest

from app.models import SampleSource
from app.normalization import normalize_bool, parse_bool_mapping
from .conftest import get_collector, get_manager, ha_state, set_entities

TS = "2026-06-23T10:00:00+00:00"


# --------------------------------------------------------------------------- #
# Normalization + mappings (pure)
# --------------------------------------------------------------------------- #


def test_parse_bool_mapping_robust():
    assert not parse_bool_mapping(None).configured
    assert not parse_bool_mapping("not json").configured
    m = parse_bool_mapping('{"active": ["Defrost", "1"], "inactive": ["Cooling"], "invert": false}')
    assert m.configured
    assert "defrost" in m.active and "cooling" in m.inactive


def test_normalize_bool_unrecognized_has_reason():
    res = normalize_bool("defrosting")
    assert res.normalized_bool is None
    assert res.reason == "unrecognized_state"


def test_normalize_bool_with_mapping():
    m = parse_bool_mapping('{"active": ["defrosting"], "inactive": ["cooling"]}')
    assert normalize_bool("defrosting", mapping=m).normalized_bool is True
    assert normalize_bool("Cooling", mapping=m).normalized_bool is False
    # falls back to the built-in vocabulary
    assert normalize_bool("on", mapping=m).normalized_bool is True
    # still unrecognized -> invalid with a reason
    bad = normalize_bool("weird", mapping=m)
    assert bad.normalized_bool is None and bad.reason == "unrecognized_state"


def test_mapping_invert_combines():
    m = parse_bool_mapping('{"active": ["x"], "invert": true}')
    assert normalize_bool("x", mapping=m).normalized_bool is False


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


async def _unit(client, *, enabled=True, mapping=None):
    defrost = {"role": "defrost", "entity_id": "switch.tk_defrost"}
    if mapping is not None:
        defrost["value_mapping"] = mapping
    resp = await client.post(
        "/api/storage-units",
        json={
            "name": "TK",
            "lower_limit_c": -25.0,
            "upper_limit_c": -18.0,
            "defrost_evaluation_enabled": enabled,
            "assignments": [
                {"role": "room_temperature", "entity_id": "sensor.tk_temp"},
                defrost,
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_defrost_diagnostic_flags_normalization_failure(app_client):
    await _unit(app_client)
    # A controller exposing "defrosting" (not on/off) cannot be normalized.
    set_entities(app_client, [ha_state("switch.tk_defrost", "defrosting", unit=None, last_updated=TS)])
    resp = await app_client.get("/api/diagnostics/defrost")
    assert resp.status_code == 200, resp.text
    item = resp.json()["mappings"][0]
    assert item["normalized_bool"] is None
    assert item["normalization_reason"] == "unrecognized_state"
    assert item["problem"].startswith("normalization_failed")


@pytest.mark.asyncio
async def test_defrost_diagnostic_ok_with_mapping(app_client):
    await _unit(app_client, mapping={"active": ["defrosting"], "inactive": ["cooling"]})
    set_entities(app_client, [ha_state("switch.tk_defrost", "defrosting", unit=None, last_updated=TS)])
    resp = await app_client.get("/api/diagnostics/defrost")
    item = resp.json()["mappings"][0]
    assert item["normalized_bool"] is True
    assert item["problem"] is None
    assert item["value_mapping"]["active"] == ["defrosting"]


@pytest.mark.asyncio
async def test_defrost_diagnostic_disabled(app_client):
    await _unit(app_client, enabled=False)
    set_entities(app_client, [ha_state("switch.tk_defrost", "off", unit=None, last_updated=TS)])
    item = (await app_client.get("/api/diagnostics/defrost")).json()["mappings"][0]
    assert item["problem"] == "evaluation_disabled"


@pytest.mark.asyncio
async def test_recent_events_and_collector_records(app_client):
    await _unit(app_client, mapping={"active": ["defrosting"], "inactive": ["cooling"]})
    get_manager(app_client)  # ensure app wired
    collector = get_collector(app_client)
    await collector.refresh_index()
    # Feed an unmapped-by-default state that the mapping resolves.
    await collector.handle_state(
        "switch.tk_defrost",
        ha_state("switch.tk_defrost", "defrosting", unit=None, last_updated=TS),
        SampleSource.live_websocket,
        old_raw="cooling",
    )
    resp = await app_client.get("/api/diagnostics/events/recent?entity_id=switch.tk_defrost")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) >= 1
    ev = events[0]
    assert ev["new_raw"] == "defrosting"
    assert ev["result"] == "stored"
    assert ev["normalized_new"] == "on"


@pytest.mark.asyncio
async def test_trace_mode_requires_user(app_client):
    await _unit(app_client)
    # No forwarded user -> 403
    resp = await app_client.post("/api/diagnostics/trace", json={"entity_id": "switch.tk_defrost"})
    assert resp.status_code == 403
    # With a user header -> active, then stop.
    headers = {"X-Remote-User-Name": "admin"}
    resp = await app_client.post(
        "/api/diagnostics/trace", json={"entity_id": "switch.tk_defrost"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True and body["entity_id"] == "switch.tk_defrost"
    assert 0 < body["remaining_seconds"] <= 15 * 60
    stop = await app_client.request("DELETE", "/api/diagnostics/trace", headers=headers)
    assert stop.status_code == 200 and stop.json()["active"] is False
