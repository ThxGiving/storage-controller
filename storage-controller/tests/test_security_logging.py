from __future__ import annotations

import logging

import pytest

from app.logging_config import SecretRedactionFilter


def test_secret_value_redacted(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "super-secret-123")
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "token is super-secret-123 here", (), None
    )
    f.filter(record)
    assert "super-secret-123" not in record.getMessage()
    assert "REDACTED" in record.getMessage()


def test_bearer_token_pattern_redacted():
    f = SecretRedactionFilter()
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "Authorization: Bearer abc.def-123", (), None
    )
    f.filter(record)
    msg = record.getMessage()
    assert "abc.def-123" not in msg
    assert "Bearer ***REDACTED***" in msg


@pytest.mark.asyncio
async def test_token_never_in_status_response(app_client, monkeypatch):
    # Even when a token exists, it must not be serialised anywhere in /api/status.
    resp = await app_client.get("/api/status")
    assert "SUPERVISOR_TOKEN" not in resp.text
    assert "Bearer" not in resp.text
