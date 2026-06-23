from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import httpx
import pytest

from app import db as db_module
from app.config import get_settings


@pytest.fixture
async def app_client(tmp_path, monkeypatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Build the app against a temporary database and yield an HTTP client.

    No Home Assistant token is set, so the connection manager stays cleanly
    disconnected. Tables are created directly (Alembic is exercised separately).
    """
    monkeypatch.setenv("SC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    get_settings.cache_clear()

    # Fresh engine bound to the temp data dir.
    await db_module.dispose_engine()
    engine = db_module.get_engine()

    # Import models so metadata is populated, then create the schema.
    from app.models import Base  # noqa: F401  (Base is shared)

    async with engine.begin() as conn:
        await conn.run_sync(db_module.Base.metadata.create_all)

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            client._app = app  # type: ignore[attr-defined]
            yield client

    await db_module.dispose_engine()
    get_settings.cache_clear()


def set_entities(client: httpx.AsyncClient, states: list[dict]) -> None:
    """Inject Home Assistant states into the running connection manager."""
    from app.ha.manager import parse_entity

    manager = client._app.state.ha_manager  # type: ignore[attr-defined]
    manager._entities = {
        s["entity_id"]: parse_entity(s) for s in states if s.get("entity_id")
    }


def get_collector(client: httpx.AsyncClient):
    return client._app.state.collector  # type: ignore[attr-defined]


def get_manager(client: httpx.AsyncClient):
    return client._app.state.ha_manager  # type: ignore[attr-defined]


def ha_state(
    entity_id: str,
    state: str,
    *,
    unit: str | None = "°C",
    last_updated: str,
    context_id: str | None = None,
) -> dict:
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": {"unit_of_measurement": unit} if unit else {},
        "last_updated": last_updated,
        "last_changed": last_updated,
        "context": {"id": context_id} if context_id else {},
    }


# Some environments require an explicit event loop policy for async fixtures.
os.environ.setdefault("PYTEST_ASYNCIO_MODE", "auto")
