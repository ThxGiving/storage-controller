"""Operational display status for a storage unit (Phase 3B).

These are non-persistent display states (NOT HACCP incidents — those arrive in
Phase 4). The logic is a pure function so it can be unit-tested and kept as the
single source of truth for both the dashboard and the unit cards.
"""

from __future__ import annotations

import re
from datetime import datetime

from .models import Quality
from .normalization import normalize_bool, parse_bool_mapping
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
# temperature; in practice that lasted up to ~25 min (later ~55 min). The
# unit's offline delay still applies when it is longer. Units with a
# connectivity entity do not use this rule (see :func:`room_is_stale`).
STALE_MIN_SECONDS = 45 * 60


# A "last successful read" timestamp of a connectivity entity changes on every
# poll (~30 s), so it uses the offline delay itself; the floor keeps a unit with
# a very short offline delay from flapping between two polls.
LINK_MIN_AGE_SECONDS = 120


def stale_after_seconds(offline_delay_seconds: int) -> int:
    return max(offline_delay_seconds, STALE_MIN_SECONDS)


def link_max_age_seconds(offline_delay_seconds: int) -> int:
    return max(offline_delay_seconds, LINK_MIN_AGE_SECONDS)


def entity_last_seen(entity: object) -> datetime | None:
    """Newest of last_reported / last_updated / last_changed (UTC)."""
    stamps = [
        ensure_utc(getattr(entity, attr, None))
        for attr in ("last_reported", "last_updated", "last_changed")
    ]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


_TZ_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_link_timestamp(raw: object) -> datetime | None:
    """Parse an ISO 8601 "last successful read" state ("Z", "+02:00", "+0200").

    A value without an offset is taken as UTC. Anything else returns None.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) < 10 or not text[:4].isdigit():
        return None
    text = _TZ_NO_COLON.sub(r"\1:\2", text.replace("Z", "+00:00"))
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def link_connected(
    entity: object | None, assignment: object, *, now: datetime, max_age_seconds: int
) -> bool:
    """True only while the assigned connectivity entity reports a live link.

    Two kinds of entity are accepted:

    * binary (binary_sensor, switch, ...): connected while it is on
      (honouring the assignment's invert / value mapping);
    * a sensor whose state is the timestamp of the last successful read (e.g.
      an ESPHome text sensor): connected while that timestamp is at most
      ``max_age_seconds`` old.

    A missing entity or an unavailable/unknown/unrecognised state counts as
    not connected.
    """
    if entity is None:
        return False
    raw = getattr(entity, "state", None)
    res = normalize_bool(
        raw,
        invert=getattr(assignment, "invert_state", False),
        mapping=parse_bool_mapping(getattr(assignment, "value_mapping_json", None)),
    )
    if res.normalized_bool is not None:
        return res.normalized_bool
    last_read = parse_link_timestamp(raw)
    if last_read is None:
        return False
    return (now - last_read).total_seconds() <= max_age_seconds


def room_is_stale(
    *,
    connected: bool,
    quality: str | None,
    last_seen: datetime | None,
    now: datetime,
    offline_delay_seconds: int,
    link_up: bool | None,
) -> bool:
    """Valid room value without a new reading for too long.

    ``link_up`` is None when no connectivity entity is assigned. With one, the
    link decides: connected means the gateway is still polling, so an
    unchanged (and therefore not re-reported) value is current; a lost link is
    reported as unavailable instead, never additionally as stale.
    """
    if link_up is not None:
        return False
    if not connected or quality != Quality.valid.value or last_seen is None:
        return False
    return (now - last_seen).total_seconds() > stale_after_seconds(offline_delay_seconds)


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
