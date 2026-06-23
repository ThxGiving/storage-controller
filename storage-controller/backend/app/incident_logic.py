"""Pure incident state-machine logic (Phase 4).

Kept free of persistence so the timing behaviour can be unit-tested directly.

States: pending_violation → active_violation → recovering → closed, with
re-violation (recovering → active_violation) and early recovery
(pending_violation → recovering → closed without ever confirming).

Evaluation result per tick:
* ACTIVE  — the condition currently holds
* CLEAR   — the condition does not hold (and we can tell)
* UNKNOWN — we cannot evaluate right now (e.g. temperature while the sensor is
            unavailable or Home Assistant is disconnected) → freeze the incident
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import IncidentState


class EvalResult(str, enum.Enum):
    ACTIVE = "active"
    CLEAR = "clear"
    UNKNOWN = "unknown"


@dataclass
class Decision:
    state: IncidentState
    confirmed_at: datetime | None
    recovering_at: datetime | None
    closed_at: datetime | None
    changed: bool


def start_state() -> IncidentState:
    return IncidentState.pending_violation


def decide(
    *,
    state: IncidentState,
    now: datetime,
    opened_at: datetime,
    confirmed_at: datetime | None,
    recovering_at: datetime | None,
    result: EvalResult,
    violation_delay: int,
    recovery_delay: int,
) -> Decision:
    """Advance one open incident by one tick. Returns the resulting state and
    the timestamps to persist (closed_at set => the incident is now closed)."""

    keep = Decision(state, confirmed_at, recovering_at, None, changed=False)

    if state == IncidentState.pending_violation:
        if result == EvalResult.ACTIVE:
            if now - opened_at >= timedelta(seconds=violation_delay):
                return Decision(IncidentState.active_violation, now, None, None, True)
            return keep
        if result == EvalResult.CLEAR:
            # Recovered before it was ever confirmed.
            return Decision(IncidentState.recovering, confirmed_at, now, None, True)
        return keep  # UNKNOWN → hold

    if state == IncidentState.active_violation:
        if result == EvalResult.CLEAR:
            return Decision(IncidentState.recovering, confirmed_at, now, None, True)
        return keep  # ACTIVE or UNKNOWN → hold (extreme handled by caller)

    if state == IncidentState.recovering:
        if result == EvalResult.ACTIVE:
            # Re-violation: back to active.
            return Decision(IncidentState.active_violation, confirmed_at or now, None, None, True)
        if result == EvalResult.CLEAR:
            if recovering_at is not None and now - recovering_at >= timedelta(
                seconds=recovery_delay
            ):
                return Decision(IncidentState.closed, confirmed_at, recovering_at, now, True)
            return keep
        return keep  # UNKNOWN → hold (do not close while unverifiable)

    return keep
