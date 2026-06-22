"""Storage-unit CRUD with free, role-based entity assignment.

Storage units are identified by their own surrogate id (never by an entity id).
Each (unit, role) pair is unique. Only ``room_temperature`` is mandatory; all
other roles are optional and can be assigned, replaced or cleared freely.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..errors import (
    ERROR_DUPLICATE_ROLE,
    ERROR_INVALID_LIMITS,
    ERROR_ROOM_TEMPERATURE_REQUIRED,
    ERROR_STORAGE_UNIT_NOT_FOUND,
    AppError,
)
from ..ha.manager import HAConnectionManager
from ..models import AuditEvent, EntityAssignment, EntityRole, StorageUnit
from ..schemas import (
    AssignmentCurrentValue,
    EntityAssignmentIn,
    StorageUnitCreate,
    StorageUnitOut,
    StorageUnitUpdate,
)
from .deps import get_manager

log = logging.getLogger("api")

router = APIRouter(prefix="/api/storage-units", tags=["storage-units"])

_TEMPERATURE_ROLES = {EntityRole.room_temperature, EntityRole.evaporator_temperature}


def _ingress_user(request: Request) -> str | None:
    """Best-effort Home Assistant user identity from trusted Ingress headers."""
    return request.headers.get("X-Remote-User-Name") or request.headers.get(
        "X-Remote-User-Id"
    )


async def _audit(
    db: AsyncSession, *, action: str, unit: StorageUnit, user: str | None, detail: str | None
) -> None:
    db.add(
        AuditEvent(
            component="api",
            action=action,
            user=user,
            object_type="storage_unit",
            object_id=str(unit.id),
            detail=detail,
        )
    )


async def _get_unit(db: AsyncSession, unit_id: int) -> StorageUnit:
    unit = await db.scalar(
        select(StorageUnit)
        .where(StorageUnit.id == unit_id)
        .options(selectinload(StorageUnit.assignments))
    )
    if unit is None:
        raise AppError(ERROR_STORAGE_UNIT_NOT_FOUND, status_code=404)
    return unit


def _validate_assignments(assignments: list[EntityAssignmentIn]) -> None:
    """Business validation with stable error codes (room temp mandatory, unique roles)."""
    roles = [a.role for a in assignments]
    if len(roles) != len(set(roles)):
        raise AppError(ERROR_DUPLICATE_ROLE, status_code=422)
    if EntityRole.room_temperature not in roles:
        raise AppError(ERROR_ROOM_TEMPERATURE_REQUIRED, status_code=422)


def _validate_limits(lower: float | None, upper: float | None) -> None:
    if lower is not None and upper is not None and lower >= upper:
        raise AppError(ERROR_INVALID_LIMITS, status_code=422)


def _apply_assignments(unit: StorageUnit, assignments) -> None:
    unit.assignments.clear()
    for a in assignments:
        unit.assignments.append(
            EntityAssignment(
                role=a.role.value,
                entity_id=a.entity_id,
                enabled=a.enabled,
                invert_state=a.invert_state,
            )
        )


@router.get("", response_model=list[StorageUnitOut])
async def list_units(db: AsyncSession = Depends(get_db)) -> list[StorageUnit]:
    units = (
        await db.scalars(
            select(StorageUnit)
            .options(selectinload(StorageUnit.assignments))
            .order_by(StorageUnit.sort_order, StorageUnit.id)
        )
    ).all()
    return list(units)


@router.post("", response_model=StorageUnitOut, status_code=201)
async def create_unit(
    payload: StorageUnitCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StorageUnit:
    _validate_assignments(payload.assignments)
    _validate_limits(payload.lower_limit_c, payload.upper_limit_c)

    data = payload.model_dump(exclude={"assignments"})
    data["unit_type"] = payload.unit_type.value
    unit = StorageUnit(**data)
    _apply_assignments(unit, payload.assignments)
    db.add(unit)
    await db.flush()
    await _audit(
        db, action="create", unit=unit, user=_ingress_user(request), detail=unit.name
    )
    await db.commit()
    return await _get_unit(db, unit.id)


@router.get("/{unit_id}", response_model=StorageUnitOut)
async def get_unit(unit_id: int, db: AsyncSession = Depends(get_db)) -> StorageUnit:
    return await _get_unit(db, unit_id)


@router.patch("/{unit_id}", response_model=StorageUnitOut)
async def update_unit(
    unit_id: int,
    payload: StorageUnitUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StorageUnit:
    unit = await _get_unit(db, unit_id)

    fields = payload.model_dump(exclude_unset=True, exclude={"assignments"})
    if "unit_type" in fields and fields["unit_type"] is not None:
        fields["unit_type"] = payload.unit_type.value
    for key, value in fields.items():
        setattr(unit, key, value)

    if payload.assignments is not None:
        _validate_assignments(payload.assignments)
        _apply_assignments(unit, payload.assignments)

    _validate_limits(unit.lower_limit_c, unit.upper_limit_c)

    await _audit(
        db, action="update", unit=unit, user=_ingress_user(request), detail=unit.name
    )
    await db.commit()
    return await _get_unit(db, unit_id)


@router.delete("/{unit_id}", status_code=204)
async def delete_unit(
    unit_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    unit = await _get_unit(db, unit_id)
    await _audit(
        db, action="delete", unit=unit, user=_ingress_user(request), detail=unit.name
    )
    await db.delete(unit)
    await db.commit()


@router.get("/{unit_id}/current", response_model=list[AssignmentCurrentValue])
async def current_values(
    unit_id: int,
    db: AsyncSession = Depends(get_db),
    manager: HAConnectionManager = Depends(get_manager),
) -> list[AssignmentCurrentValue]:
    unit = await _get_unit(db, unit_id)
    out: list[AssignmentCurrentValue] = []
    for a in unit.assignments:
        role = EntityRole(a.role)
        entity = manager.get_entity(a.entity_id)
        warning: str | None = None
        if entity is None:
            warning = "Entity not found in Home Assistant"
        elif not entity.available:
            warning = "Entity is currently unavailable"
        elif role in _TEMPERATURE_ROLES:
            try:
                float(str(entity.state))
            except (TypeError, ValueError):
                warning = "Entity does not provide a numeric temperature"
        out.append(
            AssignmentCurrentValue(
                role=role,
                entity_id=a.entity_id,
                exists=entity is not None,
                available=bool(entity and entity.available),
                state=entity.state if entity else None,
                unit_of_measurement=entity.unit_of_measurement if entity else None,
                friendly_name=entity.friendly_name if entity else None,
                warning=warning,
            )
        )
    return out
