from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import db as db_module
from app.models import Quality, SampleSource, SensorSample


async def _make_unit(client):
    resp = await client.post(
        "/api/storage-units",
        json={
            "name": "Kühlhaus 1",
            "lower_limit_c": 0.0,
            "upper_limit_c": 8.0,
            "assignments": [
                {"role": "room_temperature", "entity_id": "sensor.kuhlhaus_1_temperatur"}
            ],
        },
    )
    assert resp.status_code == 201
    return resp.json()


async def _insert(unit, samples):
    """samples: list of (minutes_ago, value_or_None, quality)."""
    factory = db_module.get_session_factory()
    aid = unit["assignments"][0]["id"]
    now = datetime.now(timezone.utc)
    async with factory() as session:
        for minutes, value, quality in samples:
            ts = now - timedelta(minutes=minutes)
            session.add(
                SensorSample(
                    storage_unit_id=unit["id"],
                    entity_assignment_id=aid,
                    entity_id="sensor.kuhlhaus_1_temperatur",
                    role="room_temperature",
                    event_timestamp=ts,
                    received_timestamp=ts,
                    raw_value=str(value) if value is not None else "unavailable",
                    numeric_value=value,
                    normalized_value_c=value,
                    original_unit="°C",
                    quality=quality,
                    source=SampleSource.live_websocket.value,
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_history_returns_points_and_stats(app_client):
    unit = await _make_unit(app_client)
    await _insert(
        unit,
        [(30, 5.0, "valid"), (20, 6.0, "valid"), (10, 7.0, "valid")],
    )
    resp = await app_client.get(f"/api/storage-units/{unit['id']}/samples?range=24h")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_count"] == 3
    assert body["min_c"] == 5.0
    assert body["max_c"] == 7.0
    assert abs(body["avg_c"] - 6.0) < 1e-9
    assert body["lower_limit_c"] == 0.0
    assert body["upper_limit_c"] == 8.0
    assert len(body["points"]) == 3


@pytest.mark.asyncio
async def test_unavailable_sample_is_a_gap_not_zero(app_client):
    unit = await _make_unit(app_client)
    await _insert(
        unit,
        [(30, 5.0, "valid"), (20, None, "unavailable"), (10, 6.0, "valid")],
    )
    resp = await app_client.get(f"/api/storage-units/{unit['id']}/samples?range=24h")
    body = resp.json()
    gap_points = [p for p in body["points"] if p["v"] is None]
    assert len(gap_points) == 1  # the unavailable sample is a gap
    # Stats ignore the gap; never treated as zero.
    assert body["min_c"] == 5.0


@pytest.mark.asyncio
async def test_downsampling_for_long_ranges(app_client):
    unit = await _make_unit(app_client)
    # 600 samples over ~10 hours, request a small max_points to force buckets.
    await _insert(unit, [(i, 5.0 + (i % 5) * 0.1, "valid") for i in range(1, 601)])
    resp = await app_client.get(
        f"/api/storage-units/{unit['id']}/samples?range=24h&max_points=50"
    )
    body = resp.json()
    assert body["downsampled"] is True
    assert body["bucket_seconds"] is not None
    assert len(body["points"]) <= 24 * 3600 // body["bucket_seconds"] + 2


@pytest.mark.asyncio
async def test_history_unknown_unit_404(app_client):
    resp = await app_client.get("/api/storage-units/999/samples")
    assert resp.status_code == 404
    assert resp.json()["code"] == "storage_unit_not_found"


@pytest.mark.asyncio
async def test_settings_get_and_patch(app_client):
    resp = await app_client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["heartbeat_interval_seconds"] == 300  # default 5 min

    patch = await app_client.patch(
        "/api/settings", json={"heartbeat_interval_seconds": 120}
    )
    assert patch.status_code == 200
    assert patch.json()["heartbeat_interval_seconds"] == 120

    # Persisted.
    again = await app_client.get("/api/settings")
    assert again.json()["heartbeat_interval_seconds"] == 120
