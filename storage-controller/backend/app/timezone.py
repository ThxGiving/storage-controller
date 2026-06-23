"""IANA timezone display helper (Phase 4.5).

Timestamps are stored in UTC; this only formats the configured IANA zone for
presentation, including the currently effective abbreviation and UTC offset
(e.g. ``Europe/Berlin · CEST · UTC+02:00`` in summer, ``CET · UTC+01:00`` in
winter).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Berlin"


@dataclass
class TimezoneInfo:
    iana: str
    abbreviation: str
    offset: str  # e.g. "UTC+02:00"
    label: str  # e.g. "Europe/Berlin · CEST · UTC+02:00"


def _format_offset(td) -> str:
    total = int(td.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"UTC{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def resolve_timezone(iana: str | None, at: datetime | None = None) -> TimezoneInfo:
    """Return display info for the configured zone at ``at`` (default now)."""
    name = iana or DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        # Fall back to UTC if tzdata is unavailable or the name is invalid.
        return TimezoneInfo("UTC", "UTC", "UTC+00:00", "UTC · UTC+00:00")

    moment = (at or datetime.now(UTC)).astimezone(tz)
    abbr = moment.tzname() or name
    offset = _format_offset(moment.utcoffset())
    return TimezoneInfo(iana=name, abbreviation=abbr, offset=offset, label=f"{abbr} · {offset}")
