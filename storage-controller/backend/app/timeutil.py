"""Canonical time handling for the whole backend.

**The rule:** every ``datetime`` in business logic, the database and the API is
tz-aware **UTC**. Local time exists only at two named edges: the browser (which
converts UTC → the viewer's zone at render time) and schedule *input* (a
wall-clock string plus an explicit ``timezone`` field). A naive datetime is
never a value we keep — if one shows up from a foreign source it is *assumed to
already be UTC* and stamped as such.

Three primitives implement this, and code should need nothing else:

* :func:`utcnow` — the single source of "now".
* :func:`ensure_utc` — stamp/convert a datetime from a **non-ORM** edge
  (Home Assistant state, the in-memory diagnostics recorder) to UTC-aware.
* ``UtcDateTime`` (in :mod:`app.models`) — the column type that guarantees
  every value read from the database is already UTC-aware, so DB-sourced times
  need not go through :func:`ensure_utc` (doing so is a harmless no-op; new code
  should simply trust that DB datetimes are UTC).
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current instant as a UTC-aware datetime. The one source of "now"."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Return ``dt`` as a UTC-aware datetime (``None`` passes through).

    A naive value is assumed to already be UTC (the system invariant); an aware
    value in any zone is converted to UTC. Use this ONLY for datetimes from
    non-ORM sources — values read from the database are already UTC-aware via
    the ``UtcDateTime`` column type and need no further stamping.
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
