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


def test_normalization_variants():
    # on/off
    assert normalize_bool("on").normalized_bool is True
    assert normalize_bool("off").normalized_bool is False
    # true/false text
    assert normalize_bool("true").normalized_bool is True
    assert normalize_bool("False").normalized_bool is False
    # 1/0 text
    assert normalize_bool("1").normalized_bool is True
    assert normalize_bool("0").normalized_bool is False
    # unknown value -> not guessed
    bad = normalize_bool("schräg")
    assert bad.normalized_bool is None and bad.reason == "unrecognized_state"
    # unavailable / missing keep a reason and never become a boolean
    assert normalize_bool("unavailable").reason == "unavailable"
    assert normalize_bool(None).reason == "missing"


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
async def test_logging_mode_requires_admin_and_expires_default_30m(app_client):
    # No forwarded user -> 403 (admin only)
    resp = await app_client.post("/api/diagnostics/logging/enable", json={})
    assert resp.status_code == 403
    # /logs is also admin-gated
    assert (await app_client.get("/api/diagnostics/logs")).status_code == 403

    headers = {"X-Remote-User-Name": "admin"}
    resp = await app_client.post("/api/diagnostics/logging/enable", json={}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True and body["enabled_by"] == "admin"
    assert 0 < body["remaining_seconds"] <= 30 * 60  # default 30 minutes

    status = await app_client.get("/api/diagnostics/logging/status")
    assert status.json()["enabled"] is True  # status readable without admin

    off = await app_client.post("/api/diagnostics/logging/disable", json={}, headers=headers)
    assert off.status_code == 200 and off.json()["enabled"] is False


@pytest.mark.asyncio
async def test_logs_only_collected_while_mode_active_and_filtered(app_client):
    await _unit(app_client, mapping={"active": ["defrosting"], "inactive": ["cooling"]})
    collector = get_collector(app_client)
    await collector.refresh_index()
    headers = {"X-Remote-User-Name": "admin"}

    # Mode OFF -> events still traced, but no structured logs collected.
    await collector.handle_state(
        "switch.tk_defrost",
        ha_state("switch.tk_defrost", "cooling", unit=None, last_updated="2026-06-23T09:59:00+00:00"),
        SampleSource.live_websocket,
    )
    logs = (await app_client.get("/api/diagnostics/logs", headers=headers)).json()
    assert logs["count"] == 0

    # Mode ON -> subsequent events produce structured, filterable logs.
    await app_client.post("/api/diagnostics/logging/enable", json={}, headers=headers)
    await collector.handle_state(
        "switch.tk_defrost",
        ha_state("switch.tk_defrost", "defrosting", unit=None, last_updated="2026-06-23T10:01:00+00:00"),
        SampleSource.live_websocket,
        old_raw="cooling",
    )
    logs = (
        await app_client.get(
            "/api/diagnostics/logs?component=collector&entity_id=switch.tk_defrost", headers=headers
        )
    ).json()
    assert logs["count"] >= 1
    assert all(e["component"] == "collector" for e in logs["entries"])


@pytest.mark.asyncio
async def test_out_of_order_event_result(app_client):
    await _unit(app_client)
    collector = get_collector(app_client)
    await collector.refresh_index()
    await collector.handle_state(
        "sensor.tk_temp",
        ha_state("sensor.tk_temp", "5.0", last_updated="2026-06-23T10:00:00+00:00"),
        SampleSource.live_websocket,
    )
    # An older timestamp for the same entity -> out_of_order_event
    await collector.handle_state(
        "sensor.tk_temp",
        ha_state("sensor.tk_temp", "6.0", last_updated="2026-06-23T09:00:00+00:00"),
        SampleSource.live_websocket,
    )
    events = (
        await app_client.get("/api/diagnostics/events/recent?entity_id=sensor.tk_temp")
    ).json()["events"]
    assert events[0]["result"] == "out_of_order_event"
