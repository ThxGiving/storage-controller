"""Home Assistant connection manager.

Maintains one long-lived WebSocket connection with automatic, exponential
backoff reconnect; keeps an in-memory cache of current entity states; and
exposes the connection health as an application status.

In Phase 1 + 2 the manager does not yet persist samples (that is Phase 3); it
only tracks connection health and the current entity snapshot used by the entity
browser and the storage-unit editor.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from ..models import SampleSource
from ..schemas import ConnectionStatus, HAEntity
from . import websocket as ws_proto
from .client import HomeAssistantRestClient
from .websocket import AuthenticationError

log = logging.getLogger("ha_client")

STATUS_CONNECTED = "connected"
STATUS_RECONNECTING = "reconnecting"
STATUS_DISCONNECTED = "disconnected"
STATUS_AUTH_ERROR = "authentication_error"

_UNAVAILABLE_STATES = {"unavailable", "unknown", "none", ""}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_entity(
    state: dict[str, Any], device_names: dict[str, str] | None = None
) -> HAEntity:
    entity_id = state.get("entity_id", "")
    domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
    attrs = state.get("attributes") or {}
    raw_state = state.get("state")
    available = str(raw_state).lower() not in {"unavailable", "unknown"}
    return HAEntity(
        entity_id=entity_id,
        domain=domain,
        friendly_name=attrs.get("friendly_name"),
        state=raw_state,
        unit_of_measurement=attrs.get("unit_of_measurement"),
        device_class=attrs.get("device_class"),
        device_name=(device_names or {}).get(entity_id),
        available=available,
        last_changed=_parse_dt(state.get("last_changed")),
        last_updated=_parse_dt(state.get("last_updated")),
    )


class HAConnectionManager:
    def __init__(
        self,
        ws_url: str,
        rest_client: HomeAssistantRestClient,
        token: str | None,
        *,
        reconnect_initial: float = 1.0,
        reconnect_max: float = 60.0,
    ) -> None:
        self._ws_url = ws_url
        self._rest = rest_client
        self._token = token
        self._reconnect_initial = reconnect_initial
        self._reconnect_max = reconnect_max

        self._status = STATUS_DISCONNECTED
        self._detail: str | None = None
        self._last_event_at: datetime | None = None
        self._last_connected_at: datetime | None = None
        self._reconnect_attempts = 0

        self._entities: dict[str, HAEntity] = {}
        self._device_names: dict[str, str] = {}

        self._task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._incident_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

        # Optional sample collector (Phase 3) and incident engine (Phase 4).
        self._collector = None
        self._incident_engine = None

    # -- public API -------------------------------------------------------- #

    def set_collector(self, collector) -> None:
        self._collector = collector

    def set_incident_engine(self, engine) -> None:
        self._incident_engine = engine

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def status(self) -> ConnectionStatus:
        return ConnectionStatus(
            status=self._status,
            last_event_at=self._last_event_at,
            last_connected_at=self._last_connected_at,
            reconnect_attempts=self._reconnect_attempts,
            entity_count=len(self._entities),
            detail=self._detail,
        )

    def entities(self) -> list[HAEntity]:
        return sorted(self._entities.values(), key=lambda e: e.entity_id)

    def get_entity(self, entity_id: str) -> HAEntity | None:
        return self._entities.get(entity_id)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="ha-connection")
        if self._collector is not None and self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name="ha-heartbeat"
            )
        if self._incident_engine is not None and self._incident_task is None:
            self._incident_task = asyncio.create_task(
                self._incident_loop(), name="incident-engine"
            )

    async def _incident_loop(self) -> None:
        """Periodically evaluate incident conditions (runs even while disconnected
        so a Home Assistant disconnect is itself detected)."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
                break  # stop requested
            except TimeoutError:
                pass
            try:
                await self._incident_engine.run(
                    self.get_entity, connected=self._status == STATUS_CONNECTED
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("incident_engine: evaluation error: %s", type(exc).__name__)

    async def stop(self) -> None:
        self._stop.set()
        for task_attr in ("_task", "_heartbeat_task", "_incident_task"):
            task = getattr(self, task_attr)
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                setattr(self, task_attr, None)
        self._status = STATUS_DISCONNECTED

    async def _heartbeat_loop(self) -> None:
        """Periodically ask the collector to write heartbeat samples for stable
        temperatures. Ticks frequently; the collector decides what is due."""
        while not self._stop.is_set():
            interval = max(15, min(self._collector.heartbeat_interval, 60))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break  # stop requested
            except TimeoutError:
                pass
            if self._status != STATUS_CONNECTED:
                continue
            try:
                await self._collector.heartbeat_tick(self.get_entity)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("collector: heartbeat error: %s", type(exc).__name__)

    # -- internal loop ----------------------------------------------------- #

    async def _run(self) -> None:
        if not self._token:
            self._status = STATUS_DISCONNECTED
            self._detail = "No Home Assistant token available"
            log.warning("ha_client: no token configured, staying disconnected")
            return

        delay = self._reconnect_initial
        while not self._stop.is_set():
            try:
                await self._connect_once()
                delay = self._reconnect_initial  # reset on clean disconnect
            except AuthenticationError as exc:
                self._status = STATUS_AUTH_ERROR
                self._detail = "Authentication rejected by Home Assistant"
                log.error("ha_client: authentication error: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._status = STATUS_RECONNECTING
                self._detail = f"{type(exc).__name__}"
                log.warning("ha_client: connection error: %s", type(exc).__name__)

            if self._stop.is_set():
                break

            self._reconnect_attempts += 1
            self._status = (
                STATUS_AUTH_ERROR
                if self._status == STATUS_AUTH_ERROR
                else STATUS_RECONNECTING
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, self._reconnect_max)

        self._status = STATUS_DISCONNECTED

    async def _connect_once(self) -> None:
        log.info("ha_client: connecting to Home Assistant WebSocket")
        conn = await ws_proto.connect(self._ws_url)
        try:
            await conn.authenticate(self._token or "")
            self._status = STATUS_CONNECTED
            self._last_connected_at = datetime.now(UTC)
            self._detail = None
            log.info("ha_client: authenticated")

            await self._refresh_device_names()
            states = await conn.get_states()
            await self._replace_entities(states)
            await conn.subscribe_state_changed()
            log.info("ha_client: subscribed to state_changed (%d entities)", len(states))

            # Reconcile current states into the sample store (idempotent).
            if self._collector is not None:
                try:
                    await self._collector.reconcile(states)
                except Exception as exc:  # noqa: BLE001
                    log.warning("collector: reconcile error: %s", type(exc).__name__)

            while not self._stop.is_set():
                msg = await conn.receive()
                if msg.get("type") == "event":
                    await self._handle_event(msg.get("event", {}))
        finally:
            await conn.raw.close()

    async def _refresh_device_names(self) -> None:
        """Best-effort: enrich entities with device names if config is reachable.

        The device/entity registry is only available over privileged WebSocket
        commands; failures here are non-fatal and simply omit device names.
        """
        # Registry retrieval requires admin WS commands; kept best-effort and
        # intentionally minimal for Phase 1+2.
        self._device_names = {}

    async def _replace_entities(self, states: list[dict[str, Any]]) -> None:
        async with self._lock:
            self._entities = {
                s["entity_id"]: parse_entity(s, self._device_names)
                for s in states
                if s.get("entity_id")
            }

    async def _handle_event(self, event: dict[str, Any]) -> None:
        data = event.get("data") or {}
        new_state = data.get("new_state")
        entity_id = data.get("entity_id")
        if not entity_id:
            return
        self._last_event_at = datetime.now(UTC)
        if new_state is None:
            # Entity removed.
            self._entities.pop(entity_id, None)
            return
        self._entities[entity_id] = parse_entity(new_state, self._device_names)

        # Record the sample if this entity is assigned to a storage unit.
        if self._collector is not None:
            try:
                await self._collector.handle_state(
                    entity_id, new_state, SampleSource.live_websocket
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("collector: handle_state error: %s", type(exc).__name__)
