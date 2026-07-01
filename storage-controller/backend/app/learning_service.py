"""Defrost-learning persistence service (Phase 4.6).

Bridges persisted :class:`DefrostCycle` rows and the pure statistics in
:mod:`app.defrost_learning`. Maintains, per storage unit, at most one
``suggested`` model and at most one ``approved`` (active) model. Approval is an
explicit human action and is audited; nothing here ever changes a unit's safety
temperature limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .defrost_learning import (
    DEFAULT_SAFETY_MARGIN_C,
    LearnedSuggestion,
    ObservedCycle,
    build_suggestion,
    detect_drift,
)
from .models import (
    LEARNABLE_DEFROST_CLASSIFICATIONS,
    AuditEvent,
    DefrostConfidence,
    DefrostCycle,
    DefrostLearnedModel,
    DefrostModelStatus,
    DefrostStatus,
    StorageUnit,
)
from .timeutil import ensure_utc

log = logging.getLogger("learning")

# Bound the learning window so old, no-longer-representative cycles age out.
MAX_LEARNING_CYCLES = 200


async def collect_observed_cycles(
    session: AsyncSession, storage_unit_id: int, *, limit: int = MAX_LEARNING_CYCLES
) -> list[ObservedCycle]:
    """Most-recent complete, valid cycles reduced to learnable scalars."""
    learnable = [c.value for c in LEARNABLE_DEFROST_CLASSIFICATIONS]
    rows = (
        await session.scalars(
            select(DefrostCycle)
            .where(
                DefrostCycle.storage_unit_id == storage_unit_id,
                DefrostCycle.status == DefrostStatus.completed.value,
                DefrostCycle.classification.in_(learnable),
                DefrostCycle.ended_at.is_not(None),
            )
            .order_by(DefrostCycle.started_at.desc())
            .limit(limit)
        )
    ).all()

    observed: list[ObservedCycle] = []
    for c in rows:
        started = ensure_utc(c.started_at)
        ended = ensure_utc(c.ended_at)
        if started is None or ended is None:
            continue
        defrost_seconds = (ended - started).total_seconds()
        if defrost_seconds <= 0:
            continue
        recovery_seconds: float | None = None
        rec_started = ensure_utc(c.recovery_started_at)
        recovered = ensure_utc(c.recovered_at)
        if rec_started is not None and recovered is not None:
            rs = (recovered - rec_started).total_seconds()
            recovery_seconds = rs if rs >= 0 else None
        observed.append(
            ObservedCycle(
                started_at=started,
                defrost_seconds=defrost_seconds,
                recovery_seconds=recovery_seconds,
                room_peak_c=c.peak_room_temperature_c,
                evaporator_peak_c=c.peak_evaporator_temperature_c,
            )
        )
    return observed


async def get_active_model(
    session: AsyncSession, storage_unit_id: int
) -> DefrostLearnedModel | None:
    return await session.scalar(
        select(DefrostLearnedModel)
        .where(
            DefrostLearnedModel.storage_unit_id == storage_unit_id,
            DefrostLearnedModel.status == DefrostModelStatus.approved.value,
        )
        .order_by(DefrostLearnedModel.version.desc())
        .limit(1)
    )


async def get_suggestion(
    session: AsyncSession, storage_unit_id: int
) -> DefrostLearnedModel | None:
    return await session.scalar(
        select(DefrostLearnedModel)
        .where(
            DefrostLearnedModel.storage_unit_id == storage_unit_id,
            DefrostLearnedModel.status == DefrostModelStatus.suggested.value,
        )
        .order_by(DefrostLearnedModel.generated_at.desc())
        .limit(1)
    )


def _apply_suggestion(model: DefrostLearnedModel, s: LearnedSuggestion) -> None:
    model.confidence = s.confidence
    model.confidence_score = s.confidence_score
    model.valid_cycle_count = s.valid_cycle_count
    model.window_start = s.window_start
    model.window_end = s.window_end
    model.typical_defrost_seconds = s.typical_defrost_seconds
    model.max_defrost_seconds = s.max_defrost_seconds
    model.typical_recovery_seconds = s.typical_recovery_seconds
    model.max_recovery_seconds = s.max_recovery_seconds
    model.typical_room_peak_c = s.typical_room_peak_c
    model.max_room_peak_c = s.max_room_peak_c
    model.typical_evaporator_peak_c = s.typical_evaporator_peak_c
    model.max_evaporator_peak_c = s.max_evaporator_peak_c
    model.typical_interval_seconds = s.typical_interval_seconds
    model.room_peak_variation_c = s.room_peak_variation_c
    model.duration_variation_seconds = s.duration_variation_seconds
    model.safety_margin_c = s.safety_margin_c
    model.generated_at = datetime.now(UTC)


async def recompute_learning(
    session: AsyncSession, unit: StorageUnit, now: datetime | None = None
) -> LearnedSuggestion:
    """Recompute the suggestion for ``unit`` and refresh drift on its active model.

    Returns the freshly computed suggestion. Does not commit; the caller owns the
    transaction. A no-op when defrost evaluation is disabled.
    """
    now = now or datetime.now(UTC)
    cycles = await collect_observed_cycles(session, unit.id)
    suggestion = build_suggestion(
        cycles,
        min_cycles=unit.defrost_learning_min_cycles,
        safety_margin_c=DEFAULT_SAFETY_MARGIN_C,
    )

    active = await get_active_model(session, unit.id)

    # Only surface a suggestion once there is enough evidence and it would add
    # information beyond the active model.
    if suggestion.confidence != DefrostConfidence.insufficient.value:
        existing = await get_suggestion(session, unit.id)
        if existing is None:
            existing = DefrostLearnedModel(
                storage_unit_id=unit.id,
                version=0,
                status=DefrostModelStatus.suggested.value,
                created_at=now,
            )
            session.add(existing)
        _apply_suggestion(existing, suggestion)

    # Drift: compare a fresh suggestion to the approved typicals (advisory only).
    if active is not None and suggestion.valid_cycle_count > 0:
        drift = detect_drift(
            approved_typical_room_c=active.typical_room_peak_c,
            approved_room_variation_c=active.room_peak_variation_c,
            approved_typical_defrost_s=active.typical_defrost_seconds,
            approved_duration_variation_s=active.duration_variation_seconds,
            recent=suggestion,
        )
        if drift.drifted and not active.drift_warning:
            session.add(
                AuditEvent(
                    component="learning",
                    action="defrost_model_drift",
                    object_type="storage_unit",
                    object_id=str(unit.id),
                    detail=drift.detail,
                )
            )
            log.info("learning: drift detected for unit %s: %s", unit.id, drift.detail)
        active.drift_warning = drift.drifted
        active.drift_detail = drift.detail

    return suggestion


@dataclass
class ApprovalOverrides:
    max_room_peak_c: float | None = None
    max_evaporator_peak_c: float | None = None
    max_defrost_seconds: int | None = None
    max_recovery_seconds: int | None = None
    safety_margin_c: float | None = None


async def approve_suggestion(
    session: AsyncSession,
    unit: StorageUnit,
    *,
    overrides: ApprovalOverrides | None = None,
    user: str | None = None,
    now: datetime | None = None,
) -> DefrostLearnedModel:
    """Promote the current suggestion to the active approved model (audited)."""
    now = now or datetime.now(UTC)
    suggestion = await get_suggestion(session, unit.id)
    if suggestion is None or suggestion.confidence == DefrostConfidence.insufficient.value:
        raise ValueError("no_suggestion")

    prev = await get_active_model(session, unit.id)
    next_version = (prev.version + 1) if prev is not None else 1
    if prev is not None:
        prev.status = DefrostModelStatus.superseded.value

    ov = overrides or ApprovalOverrides()
    if ov.max_room_peak_c is not None:
        suggestion.max_room_peak_c = ov.max_room_peak_c
    if ov.max_evaporator_peak_c is not None:
        suggestion.max_evaporator_peak_c = ov.max_evaporator_peak_c
    if ov.max_defrost_seconds is not None:
        suggestion.max_defrost_seconds = ov.max_defrost_seconds
    if ov.max_recovery_seconds is not None:
        suggestion.max_recovery_seconds = ov.max_recovery_seconds
    if ov.safety_margin_c is not None:
        suggestion.safety_margin_c = ov.safety_margin_c

    suggestion.status = DefrostModelStatus.approved.value
    suggestion.version = next_version
    suggestion.approved_at = now
    suggestion.approved_by = user
    suggestion.drift_warning = False
    suggestion.drift_detail = None

    session.add(
        AuditEvent(
            component="learning",
            action="defrost_model_approved",
            object_type="storage_unit",
            object_id=str(unit.id),
            user=user,
            detail=(
                f"v{next_version} cycles={suggestion.valid_cycle_count} "
                f"room_max={suggestion.max_room_peak_c} "
                f"defrost_max_s={suggestion.max_defrost_seconds}"
            ),
        )
    )
    log.info("learning: approved defrost model v%s for unit %s", next_version, unit.id)
    return suggestion


async def reset_learning(
    session: AsyncSession,
    unit: StorageUnit,
    *,
    user: str | None = None,
    now: datetime | None = None,
) -> None:
    """Discard the active model and any suggestion; re-enter observation (audited)."""
    now = now or datetime.now(UTC)
    rows = (
        await session.scalars(
            select(DefrostLearnedModel).where(
                DefrostLearnedModel.storage_unit_id == unit.id,
                DefrostLearnedModel.status.in_(
                    [
                        DefrostModelStatus.suggested.value,
                        DefrostModelStatus.approved.value,
                    ]
                ),
            )
        )
    ).all()
    for row in rows:
        row.status = DefrostModelStatus.superseded.value
    session.add(
        AuditEvent(
            component="learning",
            action="defrost_learning_reset",
            object_type="storage_unit",
            object_id=str(unit.id),
            user=user,
            detail=f"discarded={len(rows)}",
        )
    )
    log.info("learning: reset for unit %s (%s rows)", unit.id, len(rows))
