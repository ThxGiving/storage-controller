"""FastAPI application entry point.

Serves the internal App API and the built frontend through Home Assistant
Ingress. The application must work under a dynamic path prefix, so it honours
``X-Ingress-Path`` and never issues absolute redirects to ``/``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .api import health, home_assistant, profiles, status, storage_units
from .config import get_settings
from .db import dispose_engine, get_engine
from .errors import AppError, app_error_handler
from .ha.client import HomeAssistantRestClient
from .ha.manager import HAConnectionManager
from .logging_config import configure_logging
from .seed import run_startup_seed

log = logging.getLogger("api")

STATIC_DIR = Path(__file__).parent / "static"


class IngressRootPathMiddleware:
    """Set the ASGI ``root_path`` from the ``X-Ingress-Path`` header.

    This makes any backend-generated URLs ingress-aware without hard-coding the
    dynamic session prefix. Frontend assets and API calls themselves use
    relative paths, so this primarily prevents incorrect absolute URLs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            ingress_path = headers.get(b"x-ingress-path")
            if ingress_path:
                scope = dict(scope)
                scope["root_path"] = ingress_path.decode("latin-1").rstrip("/")
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("Storage Controller %s starting", __version__)

    # Initialise the database engine (tables are created by Alembic migrations).
    get_engine()

    # Seed built-in monitoring profiles (always) and demo data (opt-in only).
    try:
        await run_startup_seed()
    except Exception as exc:  # noqa: BLE001 — seeding must never block startup
        log.warning("database: startup seed skipped: %s", type(exc).__name__)

    rest = HomeAssistantRestClient(settings.ha_base_url, settings.ha_token)
    manager = HAConnectionManager(
        settings.ha_ws_url,
        rest,
        settings.ha_token,
        reconnect_initial=settings.ha_reconnect_initial_seconds,
        reconnect_max=settings.ha_reconnect_max_seconds,
    )
    app.state.ha_manager = manager
    await manager.start()

    try:
        yield
    finally:
        await manager.stop()
        await dispose_engine()
        log.info("Storage Controller stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Storage Controller",
        version=__version__,
        lifespan=lifespan,
        # Relative docs URLs so they work behind Ingress.
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(IngressRootPathMiddleware)
    app.add_exception_handler(AppError, app_error_handler)

    # Health is intentionally registered at the root (watchdog target).
    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(home_assistant.router)
    app.include_router(storage_units.router)
    app.include_router(profiles.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    index_file = STATIC_DIR / "index.html"

    if STATIC_DIR.is_dir() and index_file.exists():
        # Serve hashed assets (Vite emits them under /assets) and index.html.
        app.mount(
            "/assets",
            StaticFiles(directory=STATIC_DIR / "assets"),
            name="assets",
        )

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(index_file)

        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(path: str, request: Request):
            # API routes are matched first; anything else falls back to the SPA.
            candidate = STATIC_DIR / path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)
    else:

        @app.get("/", include_in_schema=False)
        async def placeholder() -> JSONResponse:
            return JSONResponse(
                {
                    "name": "Storage Controller",
                    "version": __version__,
                    "message": "Frontend build not present. Run 'npm run build'.",
                }
            )


app = create_app()
