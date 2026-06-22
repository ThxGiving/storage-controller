"""Health endpoint.

Reports HTTP 200 only when the web server is up, the database is reachable and
the expected schema (migrations) is present. Home Assistant disconnection alone
must NOT make the container unhealthy.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from ..db import get_session_factory

router = APIRouter(tags=["health"])


async def _schema_ready() -> bool:
    try:
        factory = get_session_factory()
        async with factory() as session:
            # storage_units is created by the initial migration.
            await session.execute(text("SELECT 1 FROM storage_units LIMIT 1"))
        return True
    except Exception:
        return False


@router.get("/health")
async def health(response: Response) -> dict[str, object]:
    schema_ok = await _schema_ready()
    healthy = schema_ok
    response.status_code = 200 if healthy else 503
    return {
        "status": "ok" if healthy else "unhealthy",
        "database": schema_ok,
        "migrations": schema_ok,
    }
