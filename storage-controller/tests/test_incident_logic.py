from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.incident_logic import EvalResult, decide
from app.models import IncidentState

T0 = datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc)


def _decide(state, result, *, opened=T0, confirmed=None, recovering=None, now=T0, vd=900, rd=300):
    return decide(
        state=state,
        now=now,
        opened_at=opened,
        confirmed_at=confirmed,
        recovering_at=recovering,
        result=result,
        violation_delay=vd,
        recovery_delay=rd,
    )


def test_pending_holds_before_violation_delay():
    d = _decide(IncidentState.pending_violation, EvalResult.ACTIVE, now=T0 + timedelta(minutes=10))
    assert d.changed is False
    assert d.state == IncidentState.pending_violation


def test_pending_confirms_after_violation_delay():
    d = _decide(IncidentState.pending_violation, EvalResult.ACTIVE, now=T0 + timedelta(minutes=15))
    assert d.state == IncidentState.active_violation
    assert d.confirmed_at == T0 + timedelta(minutes=15)


def test_pending_recovers_before_confirmation():
    d = _decide(IncidentState.pending_violation, EvalResult.CLEAR, now=T0 + timedelta(minutes=5))
    assert d.state == IncidentState.recovering


def test_active_to_recovering_on_clear():
    d = _decide(IncidentState.active_violation, EvalResult.CLEAR, now=T0 + timedelta(minutes=20))
    assert d.state == IncidentState.recovering
    assert d.recovering_at == T0 + timedelta(minutes=20)


def test_recovering_closes_after_recovery_delay():
    rec = T0 + timedelta(minutes=20)
    d = _decide(
        IncidentState.recovering,
        EvalResult.CLEAR,
        recovering=rec,
        now=rec + timedelta(minutes=5),
        rd=300,
    )
    assert d.state == IncidentState.closed
    assert d.closed_at == rec + timedelta(minutes=5)


def test_recovering_holds_before_recovery_delay():
    rec = T0 + timedelta(minutes=20)
    d = _decide(IncidentState.recovering, EvalResult.CLEAR, recovering=rec, now=rec + timedelta(minutes=2))
    assert d.changed is False


def test_recovering_reviolation():
    rec = T0 + timedelta(minutes=20)
    d = _decide(IncidentState.recovering, EvalResult.ACTIVE, recovering=rec, now=rec + timedelta(minutes=1))
    assert d.state == IncidentState.active_violation


def test_unknown_holds_in_every_state():
    for state in (
        IncidentState.pending_violation,
        IncidentState.active_violation,
        IncidentState.recovering,
    ):
        d = _decide(state, EvalResult.UNKNOWN, now=T0 + timedelta(hours=1))
        assert d.changed is False
