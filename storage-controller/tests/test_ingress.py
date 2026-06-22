from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_under_ingress_prefix(app_client):
    """Requests carrying X-Ingress-Path must still resolve and not redirect."""
    resp = await app_client.get(
        "/health",
        headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_works_with_ingress_header(app_client):
    resp = await app_client.get(
        "/api/status",
        headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Storage Controller"


@pytest.mark.asyncio
async def test_no_redirect_to_root(app_client):
    """The app must not bounce ingress users to an absolute /login or /."""
    resp = await app_client.get("/api/status", follow_redirects=False)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_leading_slash_is_normalized(app_client):
    """Home Assistant Ingress may forward "//..."; routing must still match.

    Without normalization the duplicated slash bypasses normal routing (which is
    what served index.html for JS/CSS and produced a blank page).
    """
    # Use a full URL so the double slash stays in the path (httpx would treat a
    # leading "//" as a scheme-relative authority otherwise).
    resp = await app_client.get("http://test//api/status")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Storage Controller"

    health = await app_client.get("http://test//health")
    assert health.status_code == 200
