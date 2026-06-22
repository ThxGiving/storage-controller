"""Application configuration loaded from environment variables.

Secrets (the Supervisor token) are read from the environment and are never
persisted to the database or returned to the frontend.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # Persistent data directory (all state lives below here, see /data).
    data_dir: Path = Field(default=Path("/data"), alias="SC_DATA_DIR")

    log_level: str = Field(default="INFO", alias="SC_LOG_LEVEL")

    # Home Assistant connection. In the Supervisor environment these defaults
    # are correct; the overrides exist purely for local development.
    ha_base_url: str = Field(default="http://supervisor/core/api", alias="HA_BASE_URL")
    ha_ws_url: str = Field(default="ws://supervisor/core/websocket", alias="HA_WS_URL")

    # Reconnect tuning for the Home Assistant WebSocket client.
    ha_reconnect_initial_seconds: float = Field(default=1.0, alias="HA_RECONNECT_INITIAL")
    ha_reconnect_max_seconds: float = Field(default=60.0, alias="HA_RECONNECT_MAX")

    @property
    def ha_token(self) -> str | None:
        """The Home Assistant API token.

        Prefers an explicit HA_TOKEN (dev) and falls back to SUPERVISOR_TOKEN.
        Read on demand so it is never accidentally serialised with the settings.
        """
        return os.environ.get("HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "storage-controller.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL used by Alembic migrations."""
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
