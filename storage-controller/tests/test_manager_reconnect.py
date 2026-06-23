from __future__ import annotations

import pytest

from app.ha.client import HomeAssistantRestClient
from app.ha.manager import (
    STATUS_AUTH_ERROR,
    STATUS_DISCONNECTED,
    HAConnectionManager,
)
from app.ha.websocket import AuthenticationError


def make_manager(token="token"):
    rest = HomeAssistantRestClient("http://x", token)
    return HAConnectionManager(
        "ws://x", rest, token, reconnect_initial=0.01, reconnect_max=0.05
    )


@pytest.mark.asyncio
async def test_no_token_stays_disconnected():
    manager = make_manager(token=None)
    await manager._run()  # returns immediately when no token
    assert manager.status().status == STATUS_DISCONNECTED


@pytest.mark.asyncio
async def test_handle_event_updates_and_removes_entities():
    manager = make_manager()
    await manager._handle_event(
        {
            "data": {
                "entity_id": "sensor.a",
                "new_state": {"entity_id": "sensor.a", "state": "5.0", "attributes": {}},
            }
        }
    )
    assert manager.get_entity("sensor.a") is not None
    assert manager.status().last_event_at is not None

    # new_state None => entity removed
    await manager._handle_event({"data": {"entity_id": "sensor.a", "new_state": None}})
    assert manager.get_entity("sensor.a") is None


@pytest.mark.asyncio
async def test_reconnect_backoff_on_auth_error(monkeypatch):
    """An authentication error sets the auth-error status and keeps retrying
    with exponential backoff until the manager is stopped."""
    manager = make_manager()
    attempts = {"n": 0}

    async def failing_connect():
        attempts["n"] += 1
        if attempts["n"] >= 3:
            manager._stop.set()
        raise AuthenticationError("invalid")

    monkeypatch.setattr(manager, "_connect_once", failing_connect)
    await manager._run()

    assert attempts["n"] >= 3
    assert manager.status().status in (STATUS_AUTH_ERROR, STATUS_DISCONNECTED)
    assert manager.status().reconnect_attempts >= 2
