"""Low-level Home Assistant WebSocket protocol helper.

Implements the authentication handshake and the minimal command set needed by
Storage Controller (get_states, subscribe_events). Reconnect orchestration lives
in :mod:`app.ha.manager`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import websockets

log = logging.getLogger("ha_client")


class AuthenticationError(RuntimeError):
    """Raised when Home Assistant rejects the access token."""


class HAWebSocketConnection:
    """A single authenticated Home Assistant WebSocket connection."""

    def __init__(self, ws: websockets.WebSocketClientProtocol) -> None:
        self._ws = ws
        self._cmd_id = 0

    @property
    def raw(self) -> websockets.WebSocketClientProtocol:
        return self._ws

    def _next_id(self) -> int:
        self._cmd_id += 1
        return self._cmd_id

    async def _send(self, payload: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(payload))

    async def _recv(self) -> dict[str, Any]:
        raw = await self._ws.recv()
        return json.loads(raw)

    async def authenticate(self, token: str) -> None:
        """Perform the auth handshake. Raises AuthenticationError on rejection."""
        first = await self._recv()
        if first.get("type") == "auth_required":
            await self._send({"type": "auth", "access_token": token})
            result = await self._recv()
        else:
            result = first

        if result.get("type") == "auth_invalid":
            raise AuthenticationError(result.get("message", "invalid authentication"))
        if result.get("type") != "auth_ok":
            raise AuthenticationError(f"unexpected auth response: {result.get('type')}")

    async def get_states(self) -> list[dict[str, Any]]:
        cmd_id = self._next_id()
        await self._send({"id": cmd_id, "type": "get_states"})
        while True:
            msg = await self._recv()
            if msg.get("id") == cmd_id and msg.get("type") == "result":
                if not msg.get("success", False):
                    return []
                result = msg.get("result")
                return result if isinstance(result, list) else []

    async def subscribe_state_changed(self) -> int:
        cmd_id = self._next_id()
        await self._send(
            {"id": cmd_id, "type": "subscribe_events", "event_type": "state_changed"}
        )
        while True:
            msg = await self._recv()
            if msg.get("id") == cmd_id and msg.get("type") == "result":
                if not msg.get("success", False):
                    raise RuntimeError("failed to subscribe to state_changed")
                return cmd_id

    async def receive(self) -> dict[str, Any]:
        """Receive the next message (e.g. an event)."""
        return await self._recv()

    async def statistics_during_period(
        self, entity_id: str, start_iso: str, end_iso: str, *, period: str = "hour"
    ) -> list[dict[str, Any]]:
        """Long-term statistics (min/max/mean) for one entity. Used for older
        periods the recorder no longer keeps at raw resolution."""
        cmd_id = self._next_id()
        await self._send(
            {
                "id": cmd_id,
                "type": "recorder/statistics_during_period",
                "start_time": start_iso,
                "end_time": end_iso,
                "statistic_ids": [entity_id],
                "period": period,
                "types": ["min", "max", "mean"],
            }
        )
        while True:
            msg = await self._recv()
            if msg.get("id") == cmd_id and msg.get("type") == "result":
                result = msg.get("result") or {}
                rows = result.get(entity_id)
                return rows if isinstance(rows, list) else []


async def connect(url: str) -> HAWebSocketConnection:
    ws = await websockets.connect(url, max_size=8 * 1024 * 1024, ping_interval=30)
    return HAWebSocketConnection(ws)


async def fetch_statistics(
    url: str, token: str, entity_id: str, start_iso: str, end_iso: str, *, period: str = "hour"
) -> list[dict[str, Any]]:
    """Open a short-lived authenticated WS connection just to pull statistics, so
    the long-lived event connection is never disturbed. Returns [] on any failure."""
    conn = await connect(url)
    try:
        await conn.authenticate(token)
        return await conn.statistics_during_period(entity_id, start_iso, end_iso, period=period)
    finally:
        try:
            await conn.raw.close()
        except Exception:  # noqa: BLE001
            pass
