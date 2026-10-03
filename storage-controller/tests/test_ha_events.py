"""Home Assistant incident events (0.9.12): REST call, outbox publisher, migration."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from app import db as db_module
from app.ha.client import HomeAssistantRestClient
from app.ha_events import EVENT_TYPE, IncidentEventPublisher
from app.incident_engine import UnitReading
from app.models import Incident, IncidentState
from sqlalchemy import select

T0 = datetime(2026, 6, 23, 10, 0, 0, tzinfo=UTC)


# ---- REST client ---------------------------------------------------------- #


@pytest.mark.asyncio
async def test_fire_event_posts_to_events_endpoint():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": "Event storage_controller_incident fired."})

    client = HomeAssistantRestClient(
        "http://supervisor/core/api", "secret-token", transport=httpx.MockTransport(handler)
    )
    await client.fire_event(EVENT_TYPE, {"event": "active", "incident_id": 7})

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "http://supervisor/core/api/events/storage_controller_incident"
    assert req.headers["Authorization"] == "Bearer secret-token"
    assert json.loads(req.content) == {"event": "active", "incident_id": 7}


@pytest.mark.asyncio
async def test_fire_event_raises_on_http_error():
    client = HomeAssistantRestClient(
        "http://supervisor/core/api",
        "secret-token",
        transport=httpx.MockTransport(lambda r: httpx.Response(502)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.fire_event(EVENT_TYPE, {})


# ---- publisher ------------------------------------------------------------ #


class FakeEvents:
    """Records fired events; can be told to fail on specific call numbers."""

    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.events: list[tuple[str, dict]] = []
        self.calls = 0
        self._fail_on = fail_on or set()

    async def fire_event(self, event_type: str, data: dict) -> None:
        self.calls += 1
        if self.calls in self._fail_on:
            raise httpx.ConnectError("home assistant unreachable")
        self.events.append((event_type, data))


def _engine(client):
    return client._app.state.incident_engine  # type: ignore[attr-defined]


def _publisher(fake: FakeEvents) -> IncidentEventPublisher:
    return IncidentEventPublisher(db_module.get_session_factory(), fake)


async def _make_unit(client, name="Kühlhaus 1", entity="sensor.kuhlhaus_1_temperatur"):
    resp = await client.post(
        "/api/storage-units",
        json={
            "name": name,
            "lower_limit_c": 0.0,
            "upper_limit_c": 8.0,
            "violation_delay_seconds": 900,
            "recovery_delay_seconds": 300,
            "offline_delay_seconds": 600,
            "assignments": [{"role": "room_temperature", "entity_id": entity}],
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _reading(unit_id, now, value):
    return UnitReading(
        storage_unit_id=unit_id,
        now=now,
        connected=True,
        has_room=True,
        room_exists=True,
        quality="valid",
        normalized_c=value,
        last_update=now,
        defrost_on=None,
        lower=0.0,
        upper=8.0,
        warning_margin=0.5,
        violation_delay=900,
        recovery_delay=300,
        offline_delay=600,
    )


async def _feed(client, uid, steps):
    """steps: list of (minutes after T0, value)."""
    eng = _engine(client)
    for minutes, value in steps:
        await eng.evaluate_readings(
            [_reading(uid, T0 + timedelta(minutes=minutes), value)], connected=True
        )


async def _incidents():
    async with db_module.get_session_factory()() as session:
        return (await session.scalars(select(Incident).order_by(Incident.id))).all()


@pytest.mark.asyncio
async def test_confirmed_incident_announced_once_then_closed(app_client):
    uid = await _make_unit(app_client)
    fake = FakeEvents()
    pub = _publisher(fake)

    # Crossing only -> pending: nothing is announced yet.
    await _feed(app_client, uid, [(0, 9.0), (10, 9.5)])
    assert await pub.publish_pending() == 0
    assert fake.events == []

    # Violation delay elapsed -> active: exactly one "active" event.
    await _feed(app_client, uid, [(15, 9.2)])
    assert await pub.publish_pending() == 1
    event_type, data = fake.events[0]
    assert event_type == EVENT_TYPE
    assert data["event"] == "active"
    assert data["type"] == "temperature_high"
    assert data["state"] == IncidentState.active_violation.value
    assert data["storage_unit_id"] == uid
    assert data["storage_unit"] == "Kühlhaus 1"
    assert data["limit_c"] == 8.0
    assert data["extreme_c"] == 9.5
    assert data["opened_at"] == T0.isoformat()
    assert data["closed_at"] is None

    # No duplicate on the next tick.
    assert await pub.publish_pending() == 0

    # Recover + close -> one "closed" event with the incident duration.
    await _feed(app_client, uid, [(20, 7.0), (26, 7.0)])
    assert await pub.publish_pending() == 1
    _, closed = fake.events[1]
    assert closed["event"] == "closed"
    assert closed["incident_id"] == data["incident_id"]
    assert closed["closed_at"] is not None
    assert closed["duration_seconds"] == 26 * 60
    assert await pub.publish_pending() == 0


@pytest.mark.asyncio
async def test_unconfirmed_excursion_is_never_announced(app_client):
    uid = await _make_unit(app_client)
    fake = FakeEvents()
    pub = _publisher(fake)

    # Short excursion (e.g. door opening) that clears before the violation delay.
    await _feed(app_client, uid, [(0, 9.0), (5, 7.0), (11, 7.0), (30, 7.0)])
    assert await pub.publish_pending() == 0
    assert fake.events == []


@pytest.mark.asyncio
async def test_flapping_excursion_is_not_announced_before_violation_delay(app_client):
    """Repeated door openings: the temperature dips below the limit between
    openings. Each new crossing must not confirm the incident immediately."""
    uid = await _make_unit(app_client)
    fake = FakeEvents()
    pub = _publisher(fake)

    await _feed(app_client, uid, [(0, 9.0), (1, 7.0), (3, 9.5), (4, 7.0), (6, 10.0), (7, 7.0)])
    assert await pub.publish_pending() == 0
    await _feed(app_client, uid, [(13, 7.0)])  # recovery delay elapsed -> closed silently
    assert await pub.publish_pending() == 0
    assert fake.events == []
    assert (await _incidents())[0].state == IncidentState.closed.value
    assert (await _incidents())[0].confirmed_at is None


@pytest.mark.asyncio
async def test_flapping_excursion_confirms_after_violation_delay(app_client):
    uid = await _make_unit(app_client)
    fake = FakeEvents()
    pub = _publisher(fake)

    # Keeps re-crossing within the recovery delay for longer than 15 min.
    await _feed(app_client, uid, [(0, 9.0), (4, 7.0), (8, 9.0), (12, 7.0), (14, 9.0)])
    assert await pub.publish_pending() == 0
    await _feed(app_client, uid, [(15, 9.0)])
    assert await pub.publish_pending() == 1
    assert fake.events[0][1]["opened_at"] == T0.isoformat()


@pytest.mark.asyncio
async def test_failed_delivery_is_retried_on_next_run(app_client):
    uid = await _make_unit(app_client)
    await _feed(app_client, uid, [(0, 9.0), (15, 9.2)])

    failing = FakeEvents(fail_on={1})
    pub = IncidentEventPublisher(db_module.get_session_factory(), failing)
    assert await pub.publish_pending() == 0
    assert (await _incidents())[0].ha_notified_active_at is None  # not marked

    assert await pub.publish_pending() == 1  # second call succeeds
    assert failing.events[0][1]["event"] == "active"
    assert (await _incidents())[0].ha_notified_active_at is not None


@pytest.mark.asyncio
async def test_backlog_sends_active_before_closed(app_client):
    uid = await _make_unit(app_client)
    # Confirmed AND closed while Home Assistant was unreachable.
    await _feed(app_client, uid, [(0, 9.0), (15, 9.2), (20, 7.0), (26, 7.0)])

    fake = FakeEvents()
    assert await _publisher(fake).publish_pending() == 2
    assert [d["event"] for _, d in fake.events] == ["active", "closed"]


@pytest.mark.asyncio
async def test_failure_keeps_earlier_deliveries_and_retries_rest(app_client):
    u1 = await _make_unit(app_client, "Kühlhaus 1", "sensor.kh1")
    u2 = await _make_unit(app_client, "Kühlhaus 2", "sensor.kh2")
    eng = _engine(app_client)
    for minutes, value in [(0, 9.0), (15, 9.2)]:
        now = T0 + timedelta(minutes=minutes)
        await eng.evaluate_readings([_reading(u1, now, value), _reading(u2, now, value)],
                                    connected=True)

    flaky = FakeEvents(fail_on={2})
    pub = IncidentEventPublisher(db_module.get_session_factory(), flaky)
    assert await pub.publish_pending() == 1
    incs = await _incidents()
    assert incs[0].ha_notified_active_at is not None
    assert incs[1].ha_notified_active_at is None

    assert await pub.publish_pending() == 1
    assert [d["storage_unit"] for _, d in flaky.events] == ["Kühlhaus 1", "Kühlhaus 2"]


@pytest.mark.asyncio
async def test_manager_tick_publishes_only_while_connected():
    from app.ha.manager import STATUS_CONNECTED, STATUS_DISCONNECTED, HAConnectionManager

    class Engine:
        runs = 0

        async def run(self, get_entity, *, connected):
            Engine.runs += 1

    class Pub:
        calls = 0

        async def publish_pending(self):
            Pub.calls += 1
            return 0

    mgr = HAConnectionManager("ws://x", HomeAssistantRestClient("http://x", None), None)
    mgr.set_incident_engine(Engine())
    mgr.set_event_publisher(Pub())

    mgr._status = STATUS_DISCONNECTED
    await mgr._incident_tick()
    assert (Engine.runs, Pub.calls) == (1, 0)  # engine still evaluates, nothing sent

    mgr._status = STATUS_CONNECTED
    await mgr._incident_tick()
    assert (Engine.runs, Pub.calls) == (2, 1)


@pytest.mark.asyncio
async def test_manager_tick_survives_publisher_error():
    from app.ha.manager import STATUS_CONNECTED, HAConnectionManager

    class Engine:
        async def run(self, get_entity, *, connected):
            return None

    class BrokenPub:
        async def publish_pending(self):
            raise RuntimeError("boom")

    mgr = HAConnectionManager("ws://x", HomeAssistantRestClient("http://x", None), None)
    mgr.set_incident_engine(Engine())
    mgr.set_event_publisher(BrokenPub())
    mgr._status = STATUS_CONNECTED
    await mgr._incident_tick()  # must not raise — the evaluation loop keeps running
    assert mgr.last_incident_eval_at is not None


# ---- migration backfill --------------------------------------------------- #


def test_migration_marks_existing_incidents_as_delivered(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from app.config import get_settings

    monkeypatch.setenv("SC_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    try:
        command.upgrade(cfg, "0012_backups")
        db_file = get_settings().database_path
        conn = sqlite3.connect(str(db_file))
        cols = (
            "type, state, opened_at, confirmed_at, closed_at, defrost_overlap, "
            "created_at, updated_at"
        )
        conn.execute(
            f"INSERT INTO incidents ({cols}) VALUES "
            "('temperature_high','closed','2026-06-01 10:00:00','2026-06-01 10:15:00',"
            "'2026-06-01 11:00:00',0,'2026-06-01 10:00:00','2026-06-01 11:00:00')"
        )
        conn.execute(
            f"INSERT INTO incidents ({cols}) VALUES "
            "('temperature_high','active_violation','2026-06-02 10:00:00',"
            "'2026-06-02 10:15:00',NULL,0,'2026-06-02 10:00:00','2026-06-02 10:15:00')"
        )
        conn.execute(
            f"INSERT INTO incidents ({cols}) VALUES "
            "('temperature_high','pending_violation','2026-06-03 10:00:00',NULL,NULL,0,"
            "'2026-06-03 10:00:00','2026-06-03 10:00:00')"
        )
        conn.commit()
        conn.close()

        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        rows = conn.execute(
            "SELECT state, ha_notified_active_at IS NOT NULL, ha_notified_closed_at IS NOT NULL "
            "FROM incidents ORDER BY id"
        ).fetchall()
        conn.close()
        assert rows == [
            ("closed", 1, 1),             # historic: nothing re-sent
            ("active_violation", 1, 0),   # already active: no new "active"; "closed" later
            ("pending_violation", 0, 0),  # not yet confirmed: will be announced if it confirms
        ]
    finally:
        get_settings.cache_clear()
