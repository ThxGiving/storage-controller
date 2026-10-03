"""Operational display status for a storage unit (Phase 3B).

These are non-persistent display states (NOT HACCP incidents — those arrive in
Phase 4). The logic is a pure function so it can be unit-tested and kept as the
single source of truth for both the dashboard and the unit cards.
"""

from __future__ import annotations

from datetime import datetime

from .models import Quality
from .timeutil import ensure_utc

STATUS_NORMAL = "normal"
STATUS_NEAR_LIMIT = "near_limit"
STATUS_OUTSIDE_RANGE = "outside_range"
STATUS_UNAVAILABLE = "unavailable"
STATUS_STALE = "stale"
STATUS_DISCONNECTED = "disconnected"
STATUS_CONFIG_ERROR = "configuration_error"

# A sensor counts as stale ("no current data") only after this long without a
# new reading. Integrations such as ESPHome drop unchanged values, so Home
# Assistant's timestamps do not move while a cold room holds a steady
# temperature; in practice that lasted up to ~25 min. The unit's offline delay
# still applies when it is longer.
STALE_MIN_SECONDS = 45 * 60


def stale_after_seconds(offline_delay_seconds: int) -> int:
    return max(offline_delay_seconds, STALE_MIN_SECONDS)


def entity_last_seen(entity: object) -> datetime | None:
    """Newest of last_reported / last_updated / last_changed (UTC)."""
    stamps = [
        ensure_utc(getattr(entity, attr, None))
        for attr in ("last_reported", "last_updated", "last_changed")
    ]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


_BAD_QUALITY = {Quality.unavailable.value, Quality.unknown.value, Quality.invalid.value}


def compute_status(
    *,
    connected: bool,
    has_room_assignment: bool,
    room_exists: bool,
    quality: str | None,
    normalized_c: float | None,
    lower_limit_c: float | None,
    upper_limit_c: float | None,
    warning_margin_c: float,
    is_stale: bool,
) -> str:
    if not has_room_assignment:
        return STATUS_CONFIG_ERROR
    if not room_exists:
        # Assigned to an entity that does not exist in Home Assistant.
        return STATUS_CONFIG_ERROR
    if not connected:
        return STATUS_DISCONNECTED
    if quality in _BAD_QUALITY or normalized_c is None:
        return STATUS_UNAVAILABLE
    if is_stale:
        return STATUS_STALE

    margin = warning_margin_c or 0.0
    if upper_limit_c is not None and normalized_c > upper_limit_c:
        return STATUS_OUTSIDE_RANGE
    if lower_limit_c is not None and normalized_c < lower_limit_c:
        return STATUS_OUTSIDE_RANGE
    if upper_limit_c is not None and normalized_c >= upper_limit_c - margin:
        return STATUS_NEAR_LIMIT
    if lower_limit_c is not None and normalized_c <= lower_limit_c + margin:
        return STATUS_NEAR_LIMIT
    return STATUS_NORMAL
