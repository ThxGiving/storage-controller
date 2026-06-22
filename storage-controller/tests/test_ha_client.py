from __future__ import annotations

import pytest

from app.ha.client import HomeAssistantRestClient
from app.ha.manager import parse_entity
from app.ha.websocket import AuthenticationError, HAWebSocketConnection


def test_rest_auth_headers_present():
    client = HomeAssistantRestClient("http://supervisor/core/api", "secret-token")
    headers = client._headers()
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Content-Type"] == "application/json"
    assert client.configured is True


def test_rest_unconfigured_without_token():
    client = HomeAssistantRestClient("http://supervisor/core/api", None)
    assert client.configured is False
    assert "Authorization" not in client._headers()


def test_parse_entity_normalizes_fields():
    entity = parse_entity(
        {
            "entity_id": "sensor.kuhlhaus_1_temperatur",
            "state": "6.1",
            "attributes": {
                "friendly_name": "Kühlhaus 1 Temperatur",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
            },
            "last_changed": "2026-06-22T10:00:00+00:00",
        }
    )
    assert entity.domain == "sensor"
    assert entity.available is True
    assert entity.unit_of_measurement == "°C"
    assert entity.last_changed is not None


def test_parse_entity_unavailable_not_zeroed():
    entity = parse_entity({"entity_id": "sensor.x", "state": "unavailable", "attributes": {}})
    assert entity.state == "unavailable"
    assert entity.available is False


# ---- WebSocket protocol -------------------------------------------------- #


class FakeWS:
    """Minimal fake of a websockets connection driven by a scripted message list."""

    def __init__(self, incoming: list[dict]):
        import json

        self._incoming = [json.dumps(m) for m in incoming]
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, raw: str):
        import json

        self.sent.append(json.loads(raw))

    async def recv(self):
        if not self._incoming:
            raise AssertionError("no more scripted messages")
        return self._incoming.pop(0)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_ws_authentication_success():
    ws = FakeWS([{"type": "auth_required"}, {"type": "auth_ok"}])
    conn = HAWebSocketConnection(ws)  # type: ignore[arg-type]
    await conn.authenticate("token")
    assert ws.sent[0] == {"type": "auth", "access_token": "token"}


@pytest.mark.asyncio
async def test_ws_authentication_invalid_raises():
    ws = FakeWS([{"type": "auth_required"}, {"type": "auth_invalid", "message": "nope"}])
    conn = HAWebSocketConnection(ws)  # type: ignore[arg-type]
    with pytest.raises(AuthenticationError):
        await conn.authenticate("bad")


@pytest.mark.asyncio
async def test_ws_get_states_returns_list():
    ws = FakeWS(
        [
            {"id": 1, "type": "result", "success": True, "result": [{"entity_id": "sensor.a"}]},
        ]
    )
    conn = HAWebSocketConnection(ws)  # type: ignore[arg-type]
    states = await conn.get_states()
    assert states == [{"entity_id": "sensor.a"}]
    assert ws.sent[0]["type"] == "get_states"


@pytest.mark.asyncio
async def test_ws_subscribe_state_changed():
    ws = FakeWS([{"id": 1, "type": "result", "success": True}])
    conn = HAWebSocketConnection(ws)  # type: ignore[arg-type]
    sub_id = await conn.subscribe_state_changed()
    assert sub_id == 1
    assert ws.sent[0]["type"] == "subscribe_events"
    assert ws.sent[0]["event_type"] == "state_changed"
