"""Incidents API (Phase 4): list, detail, acknowledge & document."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..errors import AppError
from ..models import (
    OPEN_INCIDENT_STATES,
    AuditEvent,
    Incident,
    IncidentEvent,
    StorageUnit,
)
from ..schemas import IncidentDetail, IncidentOut, IncidentUpdate

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

ERROR_INCIDENT_NOT_FOUND = "incident_not_found"


def _ingress_user(request: Request) -> str | None:
    return request.headers.get("X-Remote-User-Name") or request.headers.get(
        "X-Remote-User-Id"
    )


@router.get("", response_model=list[IncidentOut])
async def list_incidents(
    state: str = Query(default="all"),  # all | open | closed
    storage_unit_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.opened_at.desc()).limit(limit)
    if state == "open":
        stmt = stmt.where(Incident.state.in_([s.value for s in OPEN_INCIDENT_STATES]))
    elif state == "closed":
        stmt = stmt.where(Incident.state == "closed")
    if storage_unit_id is not None:
        stmt = stmt.where(Incident.storage_unit_id == storage_unit_id)
    return list((await db.scalars(stmt)).all())


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(incident_id: int, db: AsyncSession = Depends(get_db)) -> IncidentDetail:
    incident = await db.scalar(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(selectinload(Incident.events))
    )
    if incident is None:
        raise AppError(ERROR_INCIDENT_NOT_FOUND, status_code=404)
    name = None
    if incident.storage_unit_id is not None:
        name = await db.scalar(
            select(StorageUnit.name).where(StorageUnit.id == incident.storage_unit_id)
        )
    detail = IncidentDetail.model_validate(incident)
    detail.storage_unit_name = name
    detail.events = [e for e in incident.events]  # type: ignore[assignment]
    return detail


@router.patch("/{incident_id}", response_model=IncidentDetail)
async def update_incident(
    incident_id: int,
    payload: IncidentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> IncidentDetail:
    incident = await db.scalar(
        select(Incident)
        .where(Incident.id == incident_id)
        .options(selectinload(Incident.events))
    )
    if incident is None:
        raise AppError(ERROR_INCIDENT_NOT_FOUND, status_code=404)

    user = _ingress_user(request)
    now = datetime.now(UTC)
    changed: list[str] = []

    if payload.cause is not None:
        incident.cause = payload.cause
        changed.append("cause")
    if payload.corrective_action is not None:
        incident.corrective_action = payload.corrective_action
        changed.append("corrective_action")
    if payload.note is not None:
        incident.note = payload.note
        changed.append("note")
    if payload.acknowledge and incident.acknowledged_at is None:
        incident.acknowledged_at = now
        incident.acknowledged_by = user
        changed.append("acknowledged")

    if changed:
        incident.events.append(
            IncidentEvent(
                timestamp=now,
                kind="doc",
                user=user,
                detail=", ".join(changed),
            )
        )
        db.add(
            AuditEvent(
                component="incident_engine",
                action="incident_documented",
                user=user,
                object_type="incident",
                object_id=str(incident.id),
                detail=", ".join(changed),
            )
        )
        await db.commit()
        await db.refresh(incident, attribute_names=["events"])

    name = None
    if incident.storage_unit_id is not None:
        name = await db.scalar(
            select(StorageUnit.name).where(StorageUnit.id == incident.storage_unit_id)
        )
    detail = IncidentDetail.model_validate(incident)
    detail.storage_unit_name = name
    detail.events = [e for e in incident.events]  # type: ignore[assignment]
    return detail
