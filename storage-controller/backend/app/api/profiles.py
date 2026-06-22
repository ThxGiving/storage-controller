"""Monitoring-profile endpoints.

Built-in profiles are read-only templates; users may duplicate and edit copies.
Applying a profile to a storage unit copies its values (handled in the
storage-units router), so later profile edits never change existing units.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..errors import (
    ERROR_PROFILE_NOT_FOUND,
    ERROR_PROFILE_READ_ONLY,
    AppError,
)
from ..models import MonitoringProfile
from ..schemas import (
    MonitoringProfileCreate,
    MonitoringProfileOut,
    MonitoringProfileUpdate,
)

router = APIRouter(prefix="/api/monitoring-profiles", tags=["monitoring-profiles"])


async def _get_profile(db: AsyncSession, profile_id: int) -> MonitoringProfile:
    profile = await db.get(MonitoringProfile, profile_id)
    if profile is None:
        raise AppError(ERROR_PROFILE_NOT_FOUND, status_code=404)
    return profile


@router.get("", response_model=list[MonitoringProfileOut])
async def list_profiles(
    include_archived: bool = False, db: AsyncSession = Depends(get_db)
) -> list[MonitoringProfile]:
    stmt = select(MonitoringProfile).order_by(
        MonitoringProfile.built_in.desc(), MonitoringProfile.name
    )
    if not include_archived:
        stmt = stmt.where(MonitoringProfile.archived.is_(False))
    return list((await db.scalars(stmt)).all())


@router.post("", response_model=MonitoringProfileOut, status_code=201)
async def create_profile(
    payload: MonitoringProfileCreate, db: AsyncSession = Depends(get_db)
) -> MonitoringProfile:
    data = payload.model_dump(exclude={"duplicate_of_id"})
    profile = MonitoringProfile(built_in=False, archived=False, **data)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.patch("/{profile_id}", response_model=MonitoringProfileOut)
async def update_profile(
    profile_id: int,
    payload: MonitoringProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> MonitoringProfile:
    profile = await _get_profile(db, profile_id)
    if profile.built_in:
        # Built-in templates are read-only; duplicate to edit.
        raise AppError(ERROR_PROFILE_READ_ONLY, status_code=409)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: int, db: AsyncSession = Depends(get_db)) -> None:
    profile = await _get_profile(db, profile_id)
    if profile.built_in:
        raise AppError(ERROR_PROFILE_READ_ONLY, status_code=409)
    # Effective values are copied into units, so deleting a custom profile is safe.
    await db.delete(profile)
    await db.commit()
