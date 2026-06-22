"""Built-in monitoring profiles.

These are editable suggestions only — NOT legally binding HACCP requirements for
any specific product, process or business. The user must review and confirm the
effective values before monitoring starts.

Built-in profiles are seeded into the database (idempotently, keyed by ``key``)
as read-only templates. Users may duplicate and edit a copy. Some profiles use a
single limit (upper-only or lower-only); the model supports all combinations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltInProfile:
    key: str
    name: str
    description: str
    lower_limit_c: float | None
    upper_limit_c: float | None
    warning_margin_c: float
    violation_delay_seconds: int
    recovery_delay_seconds: int
    offline_delay_seconds: int
    plausible_min_c: float | None
    plausible_max_c: float | None
    defrost_grace_enabled: bool
    defrost_grace_seconds: int
    chart_group: str


# Demonstration values only — review before use.
BUILT_IN_PROFILES: list[BuiltInProfile] = [
    BuiltInProfile(
        key="positive_cold_storage",
        name="Normalkühlung",
        description="Positive Kühlung (Demonstrationswerte, bitte prüfen).",
        lower_limit_c=0.0,
        upper_limit_c=8.0,
        warning_margin_c=0.5,
        violation_delay_seconds=900,
        recovery_delay_seconds=300,
        offline_delay_seconds=600,
        plausible_min_c=-5.0,
        plausible_max_c=30.0,
        defrost_grace_enabled=True,
        defrost_grace_seconds=1800,
        chart_group="positive_cooling",
    ),
    BuiltInProfile(
        key="deep_freeze_storage",
        name="Tiefkühlung",
        description="Tiefkühllagerung (Demonstrationswerte, bitte prüfen).",
        lower_limit_c=None,
        upper_limit_c=-18.0,
        warning_margin_c=1.0,
        violation_delay_seconds=1800,
        recovery_delay_seconds=600,
        offline_delay_seconds=600,
        plausible_min_c=-40.0,
        plausible_max_c=10.0,
        defrost_grace_enabled=True,
        defrost_grace_seconds=2400,
        chart_group="deep_freezing",
    ),
    BuiltInProfile(
        key="vegetable_storage",
        name="Gemüsekühlung",
        description="Gemüsekühlung (Demonstrationswerte, bitte prüfen).",
        lower_limit_c=4.0,
        upper_limit_c=12.0,
        warning_margin_c=0.5,
        violation_delay_seconds=1800,
        recovery_delay_seconds=600,
        offline_delay_seconds=600,
        plausible_min_c=-2.0,
        plausible_max_c=30.0,
        defrost_grace_enabled=False,
        defrost_grace_seconds=0,
        chart_group="positive_cooling",
    ),
    BuiltInProfile(
        key="beverage_storage",
        name="Getränkekühlung",
        description="Getränke-/Bierkühlung (Demonstrationswerte, bitte prüfen).",
        lower_limit_c=2.0,
        upper_limit_c=10.0,
        warning_margin_c=0.5,
        violation_delay_seconds=1800,
        recovery_delay_seconds=600,
        offline_delay_seconds=600,
        plausible_min_c=-2.0,
        plausible_max_c=30.0,
        defrost_grace_enabled=False,
        defrost_grace_seconds=0,
        chart_group="positive_cooling",
    ),
]

BUILT_IN_BY_KEY = {p.key: p for p in BUILT_IN_PROFILES}
