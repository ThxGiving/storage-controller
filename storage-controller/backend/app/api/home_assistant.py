"""Home Assistant entity/connection endpoints.

The backend is the only Home Assistant API client; the browser reads entities
through these endpoints, never directly from Home Assistant.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..ha.manager import HAConnectionManager
from ..schemas import ConnectionStatus, HAEntity
from .deps import get_manager

router = APIRouter(prefix="/api/home-assistant", tags=["home-assistant"])


@router.get("/connection", response_model=ConnectionStatus)
async def connection(manager: HAConnectionManager = Depends(get_manager)) -> ConnectionStatus:
    return manager.status()


@router.get("/entities", response_model=list[HAEntity])
async def entities(
    manager: HAConnectionManager = Depends(get_manager),
    search: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    device_class: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[HAEntity]:
    items = manager.entities()

    if domain:
        items = [e for e in items if e.domain == domain]
    if device_class:
        items = [e for e in items if e.device_class == device_class]
    if search:
        needle = search.lower()
        items = [
            e
            for e in items
            if needle in e.entity_id.lower()
            or (e.friendly_name and needle in e.friendly_name.lower())
        ]

    return items[:limit]
