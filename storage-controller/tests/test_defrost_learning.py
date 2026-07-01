"""Defrost learning: robust statistics, persistence service, and API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import db as db_module
from app.defrost_learning import (
    ObservedCycle,
    build_suggestion,
    confidence_for,
    detect_drift,
    median,
    percentile,
)
from app.learning_service import (
    approve_suggestion,
    collect_observed_cycles,
    get_active_model,
    recompute_learning,
    reset_learning,
)
from app.models import DefrostCycle, DefrostLearnedModel, StorageUnit

T0 = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Pure statistics
# --------------------------------------------------------------------------- #


def test_robust_stats():
    assert median([3, 1, 2]) == 2
    assert median([1, 2, 3, 4]) == 2.5
    assert percentile([0, 10], 95) == 9.5
    assert median([]) is None


def test_confidence_thresholds():
    assert confidence_for(5)[0] == "insufficient"
    assert confidence_for(10)[0] == "preliminary"
    assert confidence_for(19)[0] == "preliminary"
    assert confidence_for(20)[0] == "high"


def _obs(n: int, *, room: float = 7.0, dur_s: float = 360.0) -> list[ObservedCycle]:
    return [
        ObservedCycle(
            started_at=T0 + timedelta(hours=i),
            defrost_seconds=dur_s,
            recovery_seconds=180.0,
            room_peak_c=room,
            evaporator_peak_c=-12.0,
        )
        for i in range(n)
    ]


def test_build_suggestion_insufficient_has_no_bounds():
    s = build_suggestion(_obs(5))
    assert s.confidence == "insufficient"
    assert s.max_room_peak_c is None  # never acts on premature data
    assert s.valid_cycle_count == 5


def test_build_suggestion_applies_safety_margin_and_robust_max():
    s = build_suggestion(_obs(12, room=7.0), safety_margin_c=2.0)
    assert s.confidence == "preliminary"
    assert s.typical_room_peak_c == 7.0
    assert s.max_room_peak_c == 9.0  # p95(7) + margin 2
    # duration max = p95 * (1 + 0.25)
    assert s.max_defrost_seconds == int(round(360 * 1.25))


def test_single_outlier_never_becomes_the_bound():
    cycles = _obs(15, room=7.0)
    # inject one extreme outlier
    cycles[0] = ObservedCycle(
        started_at=T0, defrost_seconds=360.0, recovery_seconds=180.0,
        room_peak_c=30.0, evaporator_peak_c=-12.0,
    )
    s = build_suggestion(cycles, safety_margin_c=2.0)
    assert s.outlier_count >= 1
    assert any("raum" in o for o in s.outliers)
    assert s.max_room_peak_c is not None and s.max_room_peak_c < 20.0  # robust, not 30


def test_detect_drift():
    recent = build_suggestion(_obs(12, room=12.0))
    drift = detect_drift(
        approved_typical_room_c=7.0,
        approved_room_variation_c=0.2,
        approved_typical_defrost_s=360,
        approved_duration_variation_s=10,
        recent=recent,
    )
    assert drift.drifted is True
    assert "Raumspitze" in (drift.detail or "")


# --------------------------------------------------------------------------- #
# Persistence service + API
# --------------------------------------------------------------------------- #


async def _make_unit(client, *, defrost_enabled: bool) -> dict:
    resp = await client.post(
        "/api/storage-units",
        json={
            "name": "TK Lernen",
            "lower_limit_c": -25.0,
            "upper_limit_c": 8.0,
            "defrost_evaluation_enabled": defrost_enabled,
            "assignments": [
                {"role": "room_temperature", "entity_id": "sensor.kh_temp"},
                {"role": "defrost", "entity_id": "switch.kh_defrost"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _insert_cycles(uid: int, n: int, *, room: float = 7.0) -> None:
    factory = db_module.get_session_factory()
    async with factory() as s:
        for i in range(n):
            start = T0 + timedelta(hours=i)
            s.add(
                DefrostCycle(
                    storage_unit_id=uid,
                    source_entity_id="switch.kh_defrost",
                    started_at=start,
                    ended_at=start + timedelta(minutes=6),
                    recovery_started_at=start + timedelta(minutes=6),
                    recovered_at=start + timedelta(minutes=9),
                    initial_room_temperature_c=5.0,
                    peak_room_temperature_c=room + (0.2 if i % 2 else -0.2),
                    peak_evaporator_temperature_c=-12.0,
                    status="completed",
                    classification="expected_defrost",
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_service_recompute_approve_reset(app_client):
    unit = await _make_unit(app_client, defrost_enabled=True)
    uid = unit["id"]
    await _insert_cycles(uid, 12)

    factory = db_module.get_session_factory()
    async with factory() as s:
        u = await s.get(StorageUnit, uid)
        suggestion = await recompute_learning(s, u)
        await s.commit()
        assert suggestion.confidence == "preliminary"
        assert suggestion.valid_cycle_count == 12
        # No approved model yet -> engine would not suppress.
        assert await get_active_model(s, uid) is None

    # Approve -> active model exists.
    async with factory() as s:
        u = await s.get(StorageUnit, uid)
        await recompute_learning(s, u)
        model = await approve_suggestion(s, u, user="fenn")
        await s.commit()
        assert model.status == "approved"
        assert model.approved_by == "fenn"
        active = await get_active_model(s, uid)
        assert active is not None and active.max_room_peak_c is not None

    # Reset -> no active model (re-enter observation).
    async with factory() as s:
        u = await s.get(StorageUnit, uid)
        await reset_learning(s, u, user="fenn")
        await s.commit()
        assert await get_active_model(s, uid) is None


async def _insert_recovery_cycles(uid: int, n: int, *, recovery_minutes: float) -> None:
    """Insert completed, learnable cycles with a fixed recovery duration."""
    factory = db_module.get_session_factory()
    async with factory() as s:
        base = T0 + timedelta(days=1)  # keep clear of _insert_cycles timestamps
        for i in range(n):
            start = base + timedelta(hours=i)
            end = start + timedelta(minutes=6)
            s.add(
                DefrostCycle(
                    storage_unit_id=uid,
                    source_entity_id="switch.kh_defrost",
                    started_at=start,
                    ended_at=end,
                    recovery_started_at=end,
                    recovered_at=end + timedelta(minutes=recovery_minutes),
                    initial_room_temperature_c=5.0,
                    peak_room_temperature_c=7.0,
                    peak_evaporator_temperature_c=-12.0,
                    status="completed",
                    classification="expected_defrost",
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_instant_recoveries_excluded_from_learning(app_client):
    """Regression: a same-tick (0s) 'recovery' means the room never left the safe
    band. Learning it as a ~0s duration would collapse the recovery envelope and
    strangle the recovery timeout (real recoveries would instantly time out ->
    abnormal -> never re-learned). Such sub-minute recoveries must be ignored."""
    unit = await _make_unit(app_client, defrost_enabled=True)
    uid = unit["id"]
    # 12 real recoveries (3 min) mixed with 12 instant (0 min) ones.
    await _insert_recovery_cycles(uid, 12, recovery_minutes=3.0)
    await _insert_recovery_cycles(uid, 12, recovery_minutes=0.0)

    factory = db_module.get_session_factory()
    async with factory() as s:
        observed = await collect_observed_cycles(s, uid)
        counted = [o.recovery_seconds for o in observed if o.recovery_seconds is not None]
        # Only the 12 real recoveries count; the instant ones are dropped.
        assert len(counted) == 12
        assert all(v >= 60 for v in counted)

        u = await s.get(StorageUnit, uid)
        suggestion = await recompute_learning(s, u)
        # Learned recovery reflects the real 3-min recoveries, not a poisoned ~0.
        assert suggestion.max_recovery_seconds is not None
        assert suggestion.max_recovery_seconds >= 180
        assert suggestion.typical_recovery_seconds == 180


@pytest.mark.asyncio
async def test_only_instant_recoveries_learn_nothing(app_client):
    """When every completed cycle recovered instantly, no recovery duration is
    learned (-> None), so the engine keeps its generous fallback timeout instead
    of a near-zero learned cap."""
    unit = await _make_unit(app_client, defrost_enabled=True)
    uid = unit["id"]
    await _insert_recovery_cycles(uid, 12, recovery_minutes=0.0)

    factory = db_module.get_session_factory()
    async with factory() as s:
        u = await s.get(StorageUnit, uid)
        suggestion = await recompute_learning(s, u)
        assert suggestion.max_recovery_seconds is None
        assert suggestion.typical_recovery_seconds is None


@pytest.mark.asyncio
async def test_learning_api_lifecycle(app_client):
    unit = await _make_unit(app_client, defrost_enabled=True)
    uid = unit["id"]
    await _insert_cycles(uid, 12)

    # Status: enough cycles -> suggestion ready.
    resp = await app_client.get(f"/api/storage-units/{uid}/defrost/learning")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["enabled"] is True
    assert data["state"] == "suggestion_ready"
    assert data["valid_cycle_count"] == 12
    assert data["suggestion"]["max_room_peak_c"] is not None

    # Approve.
    resp = await app_client.post(f"/api/storage-units/{uid}/defrost/learning/approve", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "approved"

    # Reset.
    resp = await app_client.post(f"/api/storage-units/{uid}/defrost/learning/reset")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] in ("observing", "suggestion_ready")
    assert resp.json()["approved"] is None


@pytest.mark.asyncio
async def test_learning_disabled_without_entity_or_toggle(app_client):
    # Toggle off -> disabled, no recompute, no suggestion.
    unit = await _make_unit(app_client, defrost_enabled=False)
    uid = unit["id"]
    await _insert_cycles(uid, 12)
    resp = await app_client.get(f"/api/storage-units/{uid}/defrost/learning")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["state"] == "disabled"
    assert data["suggestion"] is None

    factory = db_module.get_session_factory()
    async with factory() as s:
        rows = (
            await s.scalars(
                select(DefrostLearnedModel).where(
                    DefrostLearnedModel.storage_unit_id == uid
                )
            )
        ).all()
    assert rows == []  # nothing learned while disabled


@pytest.mark.asyncio
async def test_approve_without_suggestion_conflicts(app_client):
    unit = await _make_unit(app_client, defrost_enabled=True)
    uid = unit["id"]
    await _insert_cycles(uid, 3)  # below threshold
    resp = await app_client.post(f"/api/storage-units/{uid}/defrost/learning/approve", json={})
    assert resp.status_code == 409
