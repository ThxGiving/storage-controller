from __future__ import annotations

import pytest

from app.db import get_session_factory
from app.profiles import BUILT_IN_PROFILES
from app.seed import seed_built_in_profiles, seed_demo_data


@pytest.mark.asyncio
async def test_built_in_profiles_seeded_on_startup(app_client):
    resp = await app_client.get("/api/monitoring-profiles")
    assert resp.status_code == 200
    profiles = resp.json()
    keys = {p["key"] for p in profiles}
    for spec in BUILT_IN_PROFILES:
        assert spec.key in keys
    # All built-in profiles are read-only templates.
    assert all(p["built_in"] for p in profiles)


@pytest.mark.asyncio
async def test_built_in_profile_is_read_only(app_client):
    resp = await app_client.get("/api/monitoring-profiles")
    profile_id = resp.json()[0]["id"]
    patch = await app_client.patch(
        f"/api/monitoring-profiles/{profile_id}", json={"name": "Hacked"}
    )
    assert patch.status_code == 409
    assert patch.json()["code"] == "profile_read_only"


@pytest.mark.asyncio
async def test_duplicate_and_edit_custom_profile(app_client):
    builtins = (await app_client.get("/api/monitoring-profiles")).json()
    src = next(p for p in builtins if p["key"] == "positive_cold_storage")

    created = await app_client.post(
        "/api/monitoring-profiles",
        json={**{k: src[k] for k in ("lower_limit_c", "upper_limit_c")}, "name": "Meine Kühlung"},
    )
    assert created.status_code == 201
    custom = created.json()
    assert custom["built_in"] is False

    edited = await app_client.patch(
        f"/api/monitoring-profiles/{custom['id']}", json={"upper_limit_c": 6.0}
    )
    assert edited.status_code == 200
    assert edited.json()["upper_limit_c"] == 6.0


@pytest.mark.asyncio
async def test_upper_limit_only_profile_supported(app_client):
    """Deep-freeze built-in uses an upper limit only (no lower limit)."""
    profiles = (await app_client.get("/api/monitoring-profiles")).json()
    deep = next(p for p in profiles if p["key"] == "deep_freeze_storage")
    assert deep["lower_limit_c"] is None
    assert deep["upper_limit_c"] == -18.0


@pytest.mark.asyncio
async def test_applying_profile_snapshots_values_into_unit(app_client):
    """A unit created from profile values keeps them even if the profile changes."""
    profiles = (await app_client.get("/api/monitoring-profiles")).json()
    prof = next(p for p in profiles if p["key"] == "positive_cold_storage")

    unit = await app_client.post(
        "/api/storage-units",
        json={
            "name": "Kühlhaus 1",
            "unit_type": "day_cold_room",
            "lower_limit_c": prof["lower_limit_c"],
            "upper_limit_c": prof["upper_limit_c"],
            "applied_profile_key": prof["key"],
            "applied_profile_name": prof["name"],
            "assignments": [
                {"role": "room_temperature", "entity_id": "sensor.kuhlhaus_1_temperatur"}
            ],
        },
    )
    assert unit.status_code == 201
    body = unit.json()
    assert body["applied_profile_key"] == "positive_cold_storage"
    assert body["upper_limit_c"] == prof["upper_limit_c"]
    assert body["unit_type"] == "day_cold_room"


@pytest.mark.asyncio
async def test_demo_seed_is_idempotent(app_client):
    factory = get_session_factory()
    async with factory() as session:
        first = await seed_demo_data(session)
    async with factory() as session:
        second = await seed_demo_data(session)
    assert first == 4
    assert second == 0  # running again creates no duplicates

    units = (await app_client.get("/api/storage-units")).json()
    names = {u["name"] for u in units}
    assert {"Kühlhaus 1", "Kühlhaus 2", "Kühlhaus 3", "Bierkühlhaus"} <= names


@pytest.mark.asyncio
async def test_production_starts_without_demo_units(app_client):
    """Without the opt-in flag, no demo storage units are present."""
    units = (await app_client.get("/api/storage-units")).json()
    assert units == []


@pytest.mark.asyncio
async def test_seed_built_in_profiles_idempotent(app_client):
    factory = get_session_factory()
    async with factory() as session:
        again = await seed_built_in_profiles(session)
    # Profiles were already seeded at startup, so re-seeding creates none.
    assert again == 0
