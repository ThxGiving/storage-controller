"""Defrost learning API (Phase 4.6).

Diagnostic/advanced endpoints for a unit's learned defrost profile: observe the
learning status and suggestion, approve a suggestion (explicit human action),
and reset learning. Approving never changes safety temperature limits; suppression
in the incident engine is gated on an *approved* model existing here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..errors import ERROR_STORAGE_UNIT_NOT_FOUND, AppError
from ..learning_service import (
    ApprovalOverrides,
    approve_suggestion,
    get_active_model,
    get_suggestion,
    recompute_learning,
    reset_learning,
)
from ..models import DefrostCycle, EntityRole, StorageUnit
from ..schemas import (
    DefrostCycleOut,
    DefrostLearningApprove,
    DefrostLearningStatus,
    LearnedModelOut,
)

log = logging.getLogger("api")

router = APIRouter(prefix="/api/storage-units", tags=["defrost-learning"])


def _ingress_user(request: Request) -> str | None:
    return request.headers.get("X-Remote-User-Name") or request.headers.get(
        "X-Remote-User-Id"
    )


async def _unit(db: AsyncSession, unit_id: int) -> StorageUnit:
    unit = await db.scalar(
        select(StorageUnit)
        .where(StorageUnit.id == unit_id)
        .options(selectinload(StorageUnit.assignments))
    )
    if unit is None:
        raise AppError(ERROR_STORAGE_UNIT_NOT_FOUND, status_code=404)
    return unit


def _has_defrost_entity(unit: StorageUnit) -> bool:
    return any(a.role == EntityRole.defrost.value for a in unit.assignments)


async def _recent_cycles(db: AsyncSession, unit_id: int, limit: int = 20) -> list[DefrostCycle]:
    return list(
        (
            await db.scalars(
                select(DefrostCycle)
                .where(DefrostCycle.storage_unit_id == unit_id)
                .order_by(DefrostCycle.started_at.desc())
                .limit(limit)
            )
        ).all()
    )


async def _build_status(db: AsyncSession, unit: StorageUnit) -> DefrostLearningStatus:
    has_entity = _has_defrost_entity(unit)
    enabled = unit.defrost_evaluation_enabled and has_entity

    base = DefrostLearningStatus(
        storage_unit_id=unit.id,
        enabled=enabled,
        has_defrost_entity=has_entity,
        state="disabled" if not enabled else "observing",
        min_cycles=unit.defrost_learning_min_cycles,
    )
    if not enabled:
        if not has_entity:
            base.state = "no_entity"
        return base

    # Refresh suggestion + drift from current evidence (idempotent), then read back.
    suggestion = await recompute_learning(db, unit)
    await db.commit()

    approved = await get_active_model(db, unit.id)
    stored_suggestion = await get_suggestion(db, unit.id)
    cycles = await _recent_cycles(db, unit.id)

    base.valid_cycle_count = suggestion.valid_cycle_count
    base.confidence = suggestion.confidence
    base.confidence_score = suggestion.confidence_score
    base.outlier_count = suggestion.outlier_count
    base.outliers = suggestion.outliers
    base.recent_cycles = [DefrostCycleOut.model_validate(c) for c in cycles]

    if approved is not None:
        base.approved = LearnedModelOut.model_validate(approved)
        base.drift_warning = approved.drift_warning
        base.drift_detail = approved.drift_detail
        base.state = "approved"
    if stored_suggestion is not None:
        base.suggestion = LearnedModelOut.model_validate(stored_suggestion)
        if approved is None:
            base.state = "suggestion_ready"
    return base


@router.get("/{unit_id}/defrost/learning", response_model=DefrostLearningStatus)
async def learning_status(
    unit_id: int, db: AsyncSession = Depends(get_db)
) -> DefrostLearningStatus:
    unit = await _unit(db, unit_id)
    return await _build_status(db, unit)


@router.post("/{unit_id}/defrost/learning/recompute", response_model=DefrostLearningStatus)
async def learning_recompute(
    unit_id: int, db: AsyncSession = Depends(get_db)
) -> DefrostLearningStatus:
    unit = await _unit(db, unit_id)
    return await _build_status(db, unit)


@router.post("/{unit_id}/defrost/learning/approve", response_model=DefrostLearningStatus)
async def learning_approve(
    unit_id: int,
    payload: DefrostLearningApprove,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DefrostLearningStatus:
    unit = await _unit(db, unit_id)
    # Ensure the stored suggestion reflects current evidence before approving.
    await recompute_learning(db, unit)
    try:
        await approve_suggestion(
            db,
            unit,
            overrides=ApprovalOverrides(
                max_room_peak_c=payload.max_room_peak_c,
                max_evaporator_peak_c=payload.max_evaporator_peak_c,
                max_defrost_seconds=payload.max_defrost_seconds,
                max_recovery_seconds=payload.max_recovery_seconds,
                safety_margin_c=payload.safety_margin_c,
            ),
            user=_ingress_user(request),
        )
    except ValueError as exc:
        raise AppError("defrost_no_suggestion", status_code=409) from exc
    await db.commit()
    unit = await _unit(db, unit_id)
    return await _build_status(db, unit)


@router.post("/{unit_id}/defrost/learning/reset", response_model=DefrostLearningStatus)
async def learning_reset(
    unit_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> DefrostLearningStatus:
    unit = await _unit(db, unit_id)
    await reset_learning(db, unit, user=_ingress_user(request))
    await db.commit()
    unit = await _unit(db, unit_id)
    return await _build_status(db, unit)
