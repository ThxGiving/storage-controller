"""Machine-readable application errors.

Per the i18n requirements, the API contract uses stable error *codes* (not
rendered English sentences). The frontend translates the code; the optional
``message`` is an English fallback for logs/diagnostics only.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """An application error carrying a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        self.message = message or code


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "details": exc.details, "message": exc.message},
    )


# Known error codes (kept in one place so the frontend can translate them).
ERROR_ROOM_TEMPERATURE_REQUIRED = "room_temperature_required"
ERROR_DUPLICATE_ROLE = "duplicate_role"
ERROR_INVALID_LIMITS = "invalid_limits"
ERROR_STORAGE_UNIT_NOT_FOUND = "storage_unit_not_found"
ERROR_PROFILE_NOT_FOUND = "profile_not_found"
ERROR_PROFILE_READ_ONLY = "profile_read_only"
