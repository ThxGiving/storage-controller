"""Application status endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..db import check_database, get_db
from ..ha.manager import HAConnectionManager
from ..models import StorageUnit
from ..schemas import AppStatus
from .deps import get_manager

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status", response_model=AppStatus)
async def get_status(
    db: AsyncSession = Depends(get_db),
    manager: HAConnectionManager = Depends(get_manager),
) -> AppStatus:
    count = await db.scalar(select(func.count()).select_from(StorageUnit))
    return AppStatus(
        version=__version__,
        home_assistant=manager.status(),
        storage_unit_count=int(count or 0),
        database_ok=await check_database(),
    )
