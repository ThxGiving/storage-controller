"""Phase 5 reports: period boundaries, metrics, immutable snapshots, API, exports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import db as db_module
from app.models import SensorSample
from app.reporting.metrics import month_range_utc

HDR = {"X-Remote-User-Name": "admin"}


# --------------------------------------------------------------------------- #
# Period boundaries (timezone-aware, CET/CEST)
# --------------------------------------------------------------------------- #


def test_month_range_utc_summer_and_winter():
    # June (CEST, UTC+2): local midnight 01.06 -> 31.05 22:00 UTC
    s, e = month_range_utc(2026, 6, "Europe/Berlin")
    assert s == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)
    assert e == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)
    # January (CET, UTC+1): local midnight 01.01 -> 31.12 23:00 UTC
    s, e = month_range_utc(2026, 1, "Europe/Berlin")
    assert s == datetime(2025, 12, 31, 23, 0, tzinfo=UTC)
    assert e == datetime(2026, 1, 31, 23, 0, tzinfo=UTC)
    # December wraps the year
    s, e = month_range_utc(2026, 12, "Europe/Berlin")
    assert e == datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
    # UTC zone
    s, e = month_range_utc(2026, 6, "UTC")
    assert s == datetime(2026, 6, 1, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Fixtures + metrics
# --------------------------------------------------------------------------- #


async def _make_unit(client, name, lower, upper, *, group=None):
    body = {
        "name": name,
        "lower_limit_c": lower,
        "upper_limit_c": upper,
        "assignments": [{"role": "room_temperature", "entity_id": f"sensor.{name}"}],
    }
    if group:
        body["chart_group"] = group
    r = await client.post("/api/storage-units", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_samples(uid, aid_entity, start, *, n, value, quality="valid", step_min=5):
    factory = db_module.get_session_factory()
    async with factory() as s:
        # resolve assignment id
        from sqlalchemy import select

        from app.models import EntityAssignment

        aid = await s.scalar(
            select(EntityAssignment.id).where(EntityAssignment.storage_unit_id == uid)
        )
        for i in range(n):
            ts = start + timedelta(minutes=i * step_min)
            s.add(
                SensorSample(
                    storage_unit_id=uid, entity_assignment_id=aid,
                    entity_id=aid_entity, role="room_temperature",
                    event_timestamp=ts, received_timestamp=ts,
                    raw_value=str(value), numeric_value=value, normalized_value_c=value,
                    original_unit="°C",
                    quality=quality, source="live_websocket", source_context_id=None,
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_sample_metrics_above_limit_and_gap(app_client):
    uid = await _make_unit(app_client, "kh1", 0.0, 8.0)
    # June 2026 period
    start = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    # 10 valid samples at 10°C (above upper 8) at 5-min spacing => ~45 min above
    await _seed_samples(uid, "sensor.kh1", start, n=10, value=10.0)

    from app.reporting.metrics import sample_metrics

    factory = db_module.get_session_factory()
    async with factory() as s:
        m = await sample_metrics(
            s, storage_unit_id=uid,
            start_utc=datetime(2026, 5, 31, 22, tzinfo=UTC),
            end_utc=datetime(2026, 6, 30, 22, tzinfo=UTC),
            lower=0.0, upper=8.0, heartbeat_seconds=300,
        )
    assert m.max_c == 10.0 and m.min_c == 10.0
    assert m.time_above_seconds > 0  # crossing the upper limit recorded
    assert m.data_quality.valid_count == 10


# --------------------------------------------------------------------------- #
# API: generate, immutability, exports, auth, delete
# --------------------------------------------------------------------------- #


async def _four_units(client):
    ids = []
    start = datetime(2026, 6, 5, 0, 0, tzinfo=UTC)
    specs = [("kh1", -25.0, -18.0), ("kh2", -25.0, -18.0), ("kh3", 0.0, 8.0), ("veg", 2.0, 10.0)]
    for name, lo, up in specs:
        uid = await _make_unit(client, name, lo, up)
        await _seed_samples(uid, f"sensor.{name}", start, n=12, value=(lo + up) / 2)
        ids.append(uid)
    return ids


@pytest.mark.asyncio
async def test_report_lifecycle_and_immutability(app_client):
    ids = await _four_units(app_client)

    # Admin required
    assert (await app_client.post("/api/reports", json={"year": 2026, "month": 6, "storage_unit_ids": ids})).status_code == 403

    # Preview does not persist
    pv = await app_client.post(
        "/api/reports/preview",
        json={"year": 2026, "month": 6, "storage_unit_ids": ids, "locale": "de"},
        headers=HDR,
    )
    assert pv.status_code == 200
    assert "<html" in pv.json()["html"].lower()
    assert (await app_client.get("/api/reports")).json() == []

    # Create -> completed, checksum + files
    r = await app_client.post(
        "/api/reports",
        json={"year": 2026, "month": 6, "storage_unit_ids": ids, "locale": "de"},
        headers=HDR,
    )
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["status"] == "completed"
    assert rep["checksum_sha256"] and len(rep["checksum_sha256"]) == 64
    assert rep["has_pdf"] and rep["has_csv"] and rep["has_json"]
    rid = rep["id"]

    # PDF really renders
    pdf = await app_client.get(f"/api/reports/{rid}/pdf")
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"
    # CSV + JSON
    assert (await app_client.get(f"/api/reports/{rid}/csv")).status_code == 200
    js = await app_client.get(f"/api/reports/{rid}/json")
    assert js.status_code == 200 and "Kühlhaus" not in js.text  # uses kh1.. names
    assert '"kh1"' in js.text

    # Immutability: rename a unit -> existing report JSON unchanged
    await app_client.patch(f"/api/storage-units/{ids[0]}", json={"name": "RENAMED"})
    js2 = await app_client.get(f"/api/reports/{rid}/json")
    assert "RENAMED" not in js2.text  # frozen snapshot

    # Duplicate prevented
    dup = await app_client.post(
        "/api/reports",
        json={"year": 2026, "month": 6, "storage_unit_ids": ids, "locale": "de"},
        headers=HDR,
    )
    assert dup.status_code == 409
    # allow_duplicate overrides
    dup2 = await app_client.post(
        "/api/reports",
        json={"year": 2026, "month": 6, "storage_unit_ids": ids, "locale": "de", "allow_duplicate": True},
        headers=HDR,
    )
    assert dup2.status_code == 201

    # Delete (admin) removes record + files
    from app.reporting.service import report_dir

    uuid = rep["uuid"]
    assert report_dir(uuid).exists()
    assert (await app_client.request("DELETE", f"/api/reports/{rid}")).status_code == 403
    d = await app_client.request("DELETE", f"/api/reports/{rid}", headers=HDR)
    assert d.status_code == 204
    assert not report_dir(uuid).exists()
    assert (await app_client.get(f"/api/reports/{rid}")).status_code == 404


@pytest.mark.asyncio
async def test_invalid_units_rejected(app_client):
    r = await app_client.post(
        "/api/reports", json={"year": 2026, "month": 6, "storage_unit_ids": [9999]}, headers=HDR
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_branding_snapshot_and_logo_validation(app_client):
    # Branding update (admin)
    assert (await app_client.patch("/api/report-branding", json={"organization_name": "X"})).status_code == 403
    up = await app_client.patch(
        "/api/report-branding",
        json={"organization_name": "Connie's", "signature_labels": ["Prep", "Review"]},
        headers=HDR,
    )
    assert up.status_code == 200 and up.json()["organization_name"] == "Connie's"
    assert up.json()["signature_labels"] == ["Prep", "Review"]

    # Logo: reject non-image
    bad = await app_client.post(
        "/api/report-branding/logo",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=HDR,
    )
    assert bad.status_code == 422

    # Accept a small PNG
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415408d76360000000020001e221bc330000000049454e44ae426082"
    )
    ok = await app_client.post(
        "/api/report-branding/logo",
        files={"file": ("logo.png", png, "image/png")},
        headers=HDR,
    )
    assert ok.status_code == 200 and ok.json()["logo_filename"].endswith(".png")
