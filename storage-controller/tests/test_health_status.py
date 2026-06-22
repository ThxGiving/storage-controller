from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_ok(app_client):
    resp = await app_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["migrations"] is True


@pytest.mark.asyncio
async def test_status_reports_disconnected_without_token(app_client):
    resp = await app_client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Storage Controller"
    assert body["home_assistant"]["status"] == "disconnected"
    assert body["storage_unit_count"] == 0
    assert body["database_ok"] is True


@pytest.mark.asyncio
async def test_connection_endpoint(app_client):
    resp = await app_client.get("/api/home-assistant/connection")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"
