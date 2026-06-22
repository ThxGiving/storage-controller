"""Home Assistant REST client.

Talks to Home Assistant Core through the internal Supervisor proxy using the
``SUPERVISOR_TOKEN``. The token is only ever placed in the Authorization header;
it is never logged or returned to callers.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("ha_client")


class HomeAssistantRestClient:
    def __init__(self, base_url: str, token: str | None, *, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _get(self, path: str) -> Any:
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_config(self) -> dict[str, Any]:
        return await self._get("config")

    async def get_states(self) -> list[dict[str, Any]]:
        data = await self._get("states")
        return data if isinstance(data, list) else []

    async def call_service(
        self, domain: str, service: str, data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        url = f"{self._base_url}/services/{domain}/{service}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=data)
            resp.raise_for_status()
            result = resp.json()
            return result if isinstance(result, list) else []
