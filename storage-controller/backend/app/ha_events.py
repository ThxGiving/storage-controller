"""Home Assistant incident events (0.9.12).

Delivers incident lifecycle transitions to Home Assistant as
``storage_controller_incident`` events so Home Assistant automations can alert
(push notification, email, ...). The App stays the single source of truth for
*whether* something is an incident: only **confirmed** incidents are announced
(``active``), i.e. after the violation delay and the defrost grace logic of the
incident engine, followed by a ``closed`` event once the incident is closed.
Unconfirmed (``pending_violation``) excursions that clear again are never sent.

Delivery uses the ``incidents`` table as an outbox (``ha_notified_active_at`` /
``ha_notified_closed_at``): a transition is marked only after Home Assistant
accepted the event, so an event that could not be delivered (Home Assistant
restarting, network hiccup) is retried on the next evaluation tick instead of
being lost.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Incident, IncidentState, StorageUnit
from .timeutil import ensure_utc, utcnow

log = logging.getLogger("ha_events")

EVENT_TYPE = "storage_controller_incident"

# Upper bound of incidents handled per tick (keeps a backlog after a long
# Home Assistant outage from blocking the evaluation loop).
MAX_PER_RUN = 50


class EventClient(Protocol):
    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None: ...


def _iso(value: datetime | None) -> str | None:
    value = ensure_utc(value)
    return value.isoformat() if value is not None else None


def build_payload(incident: Incident, unit_name: str | None, event: str) -> dict[str, Any]:
    """Event data for one transition (``event`` is ``"active"`` or ``"closed"``)."""
    opened = ensure_utc(incident.opened_at)
    end = ensure_utc(incident.closed_at) if event == "closed" else utcnow()
    duration = int((end - opened).total_seconds()) if opened and end else None
    return {
        "event": event,
        "incident_id": incident.id,
        "type": incident.type,
        "state": incident.state,
        "storage_unit_id": incident.storage_unit_id,
        "storage_unit": unit_name,
        "opened_at": _iso(incident.opened_at),
        "confirmed_at": _iso(incident.confirmed_at),
        "closed_at": _iso(incident.closed_at),
        "limit_c": incident.limit_value_c,
        "extreme_c": incident.extreme_value_c,
        "extreme_at": _iso(incident.extreme_at),
        "defrost_overlap": bool(incident.defrost_overlap),
        "duration_seconds": duration,
    }


class IncidentEventPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: EventClient,
        *,
        max_per_run: int = MAX_PER_RUN,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._max_per_run = max_per_run

    async def publish_pending(self) -> int:
        """Deliver all undelivered transitions; returns the number of events sent.

        Stops at the first delivery failure (Home Assistant is most likely
        unreachable) and leaves the remaining transitions for the next run.
        Transitions delivered before the failure stay marked.
        """
        closed = IncidentState.closed.value
        stmt = (
            select(Incident, StorageUnit.name)
            .outerjoin(StorageUnit, StorageUnit.id == Incident.storage_unit_id)
            .where(
                or_(
                    and_(
                        Incident.confirmed_at.is_not(None),
                        Incident.ha_notified_active_at.is_(None),
                    ),
                    and_(
                        Incident.state == closed,
                        Incident.ha_notified_active_at.is_not(None),
                        Incident.ha_notified_closed_at.is_(None),
                    ),
                )
            )
            .order_by(Incident.id)
            .limit(self._max_per_run)
        )
        sent = 0
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()
            for incident, unit_name in rows:
                try:
                    if incident.ha_notified_active_at is None:
                        await self._client.fire_event(
                            EVENT_TYPE, build_payload(incident, unit_name, "active")
                        )
                        incident.ha_notified_active_at = utcnow()
                        sent += 1
                    if incident.state == closed and incident.ha_notified_closed_at is None:
                        await self._client.fire_event(
                            EVENT_TYPE, build_payload(incident, unit_name, "closed")
                        )
                        incident.ha_notified_closed_at = utcnow()
                        sent += 1
                except Exception as exc:  # noqa: BLE001 — retried on the next tick
                    log.warning(
                        "ha_events: delivery of incident %s failed (%s); will retry",
                        incident.id,
                        type(exc).__name__,
                    )
                    break
            await session.commit()
        if sent:
            log.info("ha_events: delivered %d incident event(s)", sent)
        return sent
