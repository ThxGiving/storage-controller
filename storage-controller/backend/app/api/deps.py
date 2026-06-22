"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from ..ha.manager import HAConnectionManager


def get_manager(request: Request) -> HAConnectionManager:
    return request.app.state.ha_manager
