"""Phase 6 API: SMTP settings (secret handling) + schedule CRUD + manual run."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


async def _unit(client):
    r = await client.post(
        "/api/storage-units",
        json={"name": "U", "lower_limit_c": 2.0, "upper_limit_c": 8.0,
              "assignments": [{"role": "room_temperature", "entity_id": "sensor.u"}]},
    )
    return r.json()["id"]


# -- SMTP settings + secret handling --------------------------------------- #


@pytest.mark.asyncio
async def test_smtp_password_is_write_only(app_client):
    r = await app_client.put(
        "/api/settings/email",
        json={"host": "smtp.x", "port": 587, "security_mode": "starttls",
              "username": "u", "password": "secret123", "sender_email": "a@b.com"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "password" not in body  # never returned
    assert body["password_configured"] is True

    got = (await app_client.get("/api/settings/email")).json()
    assert got["password_configured"] is True
    assert "password" not in got and "password_secret" not in got


@pytest.mark.asyncio
async def test_empty_password_preserves_existing(app_client):
    await app_client.put(
        "/api/settings/email",
        json={"host": "smtp.x", "security_mode": "starttls", "username": "u",
              "password": "keepme", "sender_email": "a@b.com"},
    )
    # Update without a password field — secret must be preserved.
    await app_client.put(
        "/api/settings/email",
        json={"host": "smtp.y", "security_mode": "starttls", "username": "u",
              "sender_email": "a@b.com"},
    )
    got = (await app_client.get("/api/settings/email")).json()
    assert got["host"] == "smtp.y"
    assert got["password_configured"] is True  # still configured


@pytest.mark.asyncio
async def test_clear_password_removes_secret(app_client):
    await app_client.put(
        "/api/settings/email",
        json={"host": "smtp.x", "security_mode": "starttls", "password": "x",
              "sender_email": "a@b.com"},
    )
    await app_client.put(
        "/api/settings/email",
        json={"host": "smtp.x", "security_mode": "starttls", "clear_password": True,
              "sender_email": "a@b.com"},
    )
    got = (await app_client.get("/api/settings/email")).json()
    assert got["password_configured"] is False


@pytest.mark.asyncio
async def test_invalid_security_mode_and_recipient_rejected(app_client):
    r = await app_client.put(
        "/api/settings/email", json={"host": "x", "security_mode": "bogus"}
    )
    assert r.status_code == 422
    r = await app_client.put(
        "/api/settings/email",
        json={"host": "x", "security_mode": "starttls", "default_to": ["not-an-email"]},
    )
    assert r.status_code == 422


# -- schedules -------------------------------------------------------------- #


async def _create_schedule(client, uid, **over):
    payload = {
        "name": "Monthly HACCP", "enabled": True, "storage_unit_ids": [uid],
        "locale": "de", "timezone": "Europe/Berlin", "detail_level": "standard",
        "recipients_to": ["ops@example.com"], "attachment_formats": ["pdf"],
        "run_day": 1, "run_time": "06:00",
    }
    payload.update(over)
    return await client.post("/api/schedules", json=payload)


@pytest.mark.asyncio
async def test_schedule_crud_and_toggle(app_client):
    uid = await _unit(app_client)
    r = await _create_schedule(app_client, uid)
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["recipient_count"] == 1
    assert r.json()["next_run_utc"] is not None
    # run_now_period is a previous complete month (YYYY-MM)
    assert len(r.json()["run_now_period"]) == 7

    lst = (await app_client.get("/api/schedules")).json()
    assert any(s["id"] == sid for s in lst)

    upd = await app_client.put(
        f"/api/schedules/{sid}",
        json={"name": "Renamed", "enabled": True, "storage_unit_ids": [uid], "locale": "en",
              "recipients_to": ["a@b.com", "a@b.com"], "attachment_formats": ["pdf", "csv"],
              "run_day": 1, "run_time": "07:30"},
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Renamed" and upd.json()["locale"] == "en"
    assert upd.json()["recipient_count"] == 1  # deduped

    dis = await app_client.post(f"/api/schedules/{sid}/disable")
    assert dis.json()["enabled"] is False
    en = await app_client.post(f"/api/schedules/{sid}/enable")
    assert en.json()["enabled"] is True

    d = await app_client.delete(f"/api/schedules/{sid}")
    assert d.status_code == 204
    assert (await app_client.get(f"/api/schedules/{sid}")).status_code == 404


@pytest.mark.asyncio
async def test_schedule_rejects_invalid_recipient(app_client):
    uid = await _unit(app_client)
    r = await _create_schedule(app_client, uid, recipients_to=["bad"])
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_run_now_uses_previous_complete_month(app_client):
    uid = await _unit(app_client)
    sid = (await _create_schedule(app_client, uid)).json()["id"]
    # No SMTP host configured -> generates without sending; run completes.
    r = await app_client.post(f"/api/schedules/{sid}/run-now?send=true")
    assert r.status_code == 200
    body = r.json()
    now = datetime.now(UTC)
    exp_year, exp_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    assert body["period_year"] == exp_year and body["period_month"] == exp_month
    assert body["report_status"] == "completed"
