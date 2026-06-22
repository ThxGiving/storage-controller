"""Database seeding.

Two independent concerns:

* ``seed_built_in_profiles`` always runs at startup and keeps the read-only
  built-in monitoring profiles in sync (idempotent, keyed by ``key``).
* ``seed_demo_data`` is OPT-IN only (env ``STORAGE_CONTROLLER_LOAD_DEMO_DATA`` or
  the ``storage-controller seed-demo`` command). Production starts with no
  storage units. The demo set is illustrative and must never be referenced from
  application logic.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session_factory
from .models import EntityAssignment, MonitoringProfile, StorageUnit, StorageUnitType
from .profiles import BUILT_IN_PROFILES

log = logging.getLogger("database")


async def seed_built_in_profiles(session: AsyncSession) -> int:
    """Insert/update built-in profiles. Returns the number created."""
    created = 0
    for spec in BUILT_IN_PROFILES:
        existing = await session.scalar(
            select(MonitoringProfile).where(MonitoringProfile.key == spec.key)
        )
        if existing is None:
            session.add(
                MonitoringProfile(
                    key=spec.key,
                    name=spec.name,
                    description=spec.description,
                    built_in=True,
                    archived=False,
                    lower_limit_c=spec.lower_limit_c,
                    upper_limit_c=spec.upper_limit_c,
                    warning_margin_c=spec.warning_margin_c,
                    violation_delay_seconds=spec.violation_delay_seconds,
                    recovery_delay_seconds=spec.recovery_delay_seconds,
                    offline_delay_seconds=spec.offline_delay_seconds,
                    plausible_min_c=spec.plausible_min_c,
                    plausible_max_c=spec.plausible_max_c,
                    defrost_grace_enabled=spec.defrost_grace_enabled,
                    defrost_grace_seconds=spec.defrost_grace_seconds,
                    chart_group=spec.chart_group,
                    report_enabled_by_default=True,
                )
            )
            created += 1
        else:
            # Keep the built-in template values current without touching user copies.
            existing.name = spec.name
            existing.description = spec.description
            existing.lower_limit_c = spec.lower_limit_c
            existing.upper_limit_c = spec.upper_limit_c
            existing.warning_margin_c = spec.warning_margin_c
            existing.violation_delay_seconds = spec.violation_delay_seconds
            existing.recovery_delay_seconds = spec.recovery_delay_seconds
            existing.offline_delay_seconds = spec.offline_delay_seconds
            existing.plausible_min_c = spec.plausible_min_c
            existing.plausible_max_c = spec.plausible_max_c
            existing.defrost_grace_enabled = spec.defrost_grace_enabled
            existing.defrost_grace_seconds = spec.defrost_grace_seconds
            existing.chart_group = spec.chart_group
    await session.commit()
    return created


# Demo units — illustrative seed/development data only (never used by logic).
_DEMO_UNITS = [
    {
        "name": "Kühlhaus 1",
        "short_report_name": "KH1",
        "unit_type": StorageUnitType.day_cold_room.value,
        "profile_key": "positive_cold_storage",
        "room_entity": "sensor.kuhlhaus_1_temperatur",
    },
    {
        "name": "Kühlhaus 2",
        "short_report_name": "KH2",
        "unit_type": StorageUnitType.freezer_room.value,
        "profile_key": "deep_freeze_storage",
        "room_entity": "sensor.kuhlhaus_2_temperatur",
    },
    {
        "name": "Kühlhaus 3",
        "short_report_name": "KH3",
        "unit_type": StorageUnitType.vegetable_cold_room.value,
        "profile_key": "vegetable_storage",
        "room_entity": "sensor.kuhlhaus_3_temperatur",
    },
    {
        # Beverage cold room: configured without a primary sensor yet.
        "name": "Bierkühlhaus",
        "short_report_name": "Bier",
        "unit_type": StorageUnitType.beverage_cold_room.value,
        "profile_key": "beverage_storage",
        "room_entity": None,
    },
]


async def seed_demo_data(session: AsyncSession) -> int:
    """Idempotently create the demo storage units. Returns the number created."""
    from .profiles import BUILT_IN_BY_KEY

    created = 0
    for idx, spec in enumerate(_DEMO_UNITS):
        existing = await session.scalar(
            select(StorageUnit).where(StorageUnit.name == spec["name"])
        )
        if existing is not None:
            continue
        profile = BUILT_IN_BY_KEY[spec["profile_key"]]
        unit = StorageUnit(
            name=spec["name"],
            short_report_name=spec["short_report_name"],
            unit_type=spec["unit_type"],
            sort_order=idx,
            lower_limit_c=profile.lower_limit_c,
            upper_limit_c=profile.upper_limit_c,
            warning_margin_c=profile.warning_margin_c,
            violation_delay_seconds=profile.violation_delay_seconds,
            recovery_delay_seconds=profile.recovery_delay_seconds,
            offline_delay_seconds=profile.offline_delay_seconds,
            plausible_min_c=profile.plausible_min_c,
            plausible_max_c=profile.plausible_max_c,
            defrost_grace_enabled=profile.defrost_grace_enabled,
            defrost_grace_seconds=profile.defrost_grace_seconds,
            chart_group=profile.chart_group,
            applied_profile_key=profile.key,
            applied_profile_name=profile.name,
        )
        if spec["room_entity"]:
            unit.assignments.append(
                EntityAssignment(role="room_temperature", entity_id=spec["room_entity"])
            )
        session.add(unit)
        created += 1
    await session.commit()
    return created


def demo_requested() -> bool:
    return os.environ.get("STORAGE_CONTROLLER_LOAD_DEMO_DATA", "").lower() in {
        "1",
        "true",
        "yes",
    }


async def run_startup_seed() -> None:
    """Seed built-in profiles always; demo units only when explicitly requested."""
    factory = get_session_factory()
    async with factory() as session:
        n = await seed_built_in_profiles(session)
        if n:
            log.info("database: seeded %d built-in monitoring profiles", n)
        if demo_requested():
            d = await seed_demo_data(session)
            log.info("database: demo data requested, created %d storage units", d)
