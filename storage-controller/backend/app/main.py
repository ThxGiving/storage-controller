"""FastAPI application entry point.

Serves the internal App API and the built frontend through Home Assistant
Ingress. The application must work under a dynamic path prefix, so it honours
``X-Ingress-Path`` and never issues absolute redirects to ``/``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .api import (
    dashboard,
    defrost,
    health,
    history,
    home_assistant,
    incidents,
    profiles,
    status,
    storage_units,
)
from .api import (
    diagnostics as diagnostics_api,
)
from .api import backup as backup_api
from .api import email_settings as email_settings_api
from .api import history_import as history_import_api
from .api import (
    maintenance as maintenance_api,
)
from .api import report_branding as report_branding_api
from .api import reports as reports_api
from .api import schedules as schedules_api
from .api import settings as settings_api
from .backup import complete_pending_restore
from .collector import Collector
from .config import get_settings
from .db import dispose_engine, get_engine, get_session_factory
from .diagnostics import DiagnosticsRecorder
from .errors import AppError, app_error_handler
from .ha.client import HomeAssistantRestClient
from .ha.manager import HAConnectionManager
from .incident_engine import IncidentEngine
from .logging_config import configure_logging
from .maintenance import MaintenanceRunner
from .scheduler import SchedulerRunner
from .seed import run_startup_seed

log = logging.getLogger("api")

STATIC_DIR = Path(__file__).parent / "static"


class IngressPathMiddleware:
    """Normalise duplicated leading slashes in the request path.

    Home Assistant Ingress can forward requests with a duplicated leading slash
    (e.g. ``//`` and ``//assets/...``). Left untouched, those bypass the static
    mount and the SPA route would serve ``index.html`` for JS/CSS, breaking the
    page. We collapse duplicate leading slashes so routing works normally.

    We deliberately do NOT set ``root_path`` from ``X-Ingress-Path``: the whole
    frontend uses relative asset/API paths, so no absolute URLs are generated,
    and setting ``root_path`` interferes with sub-app (static mount) routing in
    current Starlette versions (it made ``/assets/*`` 404 behind Ingress).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("//"):
                scope = dict(scope)
                scope["path"] = "/" + path.lstrip("/")
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    log.info("Refrigeration Logbook %s starting", __version__)

    # Complete any pending restore BEFORE opening the database engine.
    # This replaces the live DB and file directories with the staged backup.
    complete_pending_restore(settings.data_dir, settings.database_path)

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

    # Sample collector (Phase 3): records assigned-entity samples independently.
    collector = Collector(get_session_factory())
    # Diagnostics recorder (Phase 4.6.1): in-memory event/sample trace.
    diagnostics = DiagnosticsRecorder()
    collector.diagnostics = diagnostics
    try:
        await collector.refresh_index()
    except Exception as exc:  # noqa: BLE001
        log.warning("collector: initial index build skipped: %s", type(exc).__name__)
    manager.set_collector(collector)

    # Incident engine (Phase 4): evaluates limit/availability conditions.
    incident_engine = IncidentEngine(get_session_factory())
    incident_engine.diagnostics = diagnostics
    manager.set_incident_engine(incident_engine)

    # Maintenance runner (Phase 4.5): aggregation, retention, storage, WAL.
    maintenance = MaintenanceRunner(get_session_factory())
    try:
        await maintenance.refresh_storage()
        collector.suspend_heartbeat = maintenance.emergency
    except Exception as exc:  # noqa: BLE001
        log.warning("maintenance: initial storage calc skipped: %s", type(exc).__name__)

    app.state.ha_manager = manager
    app.state.rest = rest
    app.state.collector = collector
    app.state.incident_engine = incident_engine
    app.state.maintenance = maintenance
    app.state.diagnostics = diagnostics
    await manager.start()

    maint_stop = asyncio.Event()
    maint_task = asyncio.create_task(
        _maintenance_loop(maintenance, collector, maint_stop), name="maintenance"
    )

    # Report scheduler (Phase 6): persistent, restart-safe; catches up one missed
    # run on startup and ticks every minute.
    scheduler = SchedulerRunner(get_session_factory())
    app.state.scheduler = scheduler
    sched_stop = asyncio.Event()
    sched_task = asyncio.create_task(_scheduler_loop(scheduler, sched_stop), name="scheduler")

    try:
        yield
    finally:
        maint_stop.set()
        sched_stop.set()
        for task in (maint_task, sched_task):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await manager.stop()
        await dispose_engine()
        log.info("Refrigeration Logbook stopped")


async def _scheduler_loop(scheduler: SchedulerRunner, stop: asyncio.Event) -> None:
    """Tick the report scheduler every minute (and once at startup for catch-up)."""
    try:
        await scheduler.tick()
    except Exception as exc:  # noqa: BLE001
        log.warning("scheduler: startup tick error: %s", type(exc).__name__)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
            break
        except TimeoutError:
            pass
        try:
            await scheduler.tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler: loop error: %s", type(exc).__name__)


async def _maintenance_loop(
    maintenance: MaintenanceRunner, collector: Collector, stop: asyncio.Event
) -> None:
    """Run bounded maintenance once daily (and refresh storage hourly)."""
    seconds_since_run = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=3600)
            break  # stop requested
        except TimeoutError:
            pass
        seconds_since_run += 3600
        try:
            if seconds_since_run >= 86400:
                await maintenance.run_once()
                seconds_since_run = 0
            else:
                await maintenance.refresh_storage()
            collector.suspend_heartbeat = maintenance.emergency
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("maintenance: loop error: %s", type(exc).__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Storage Controller",
        version=__version__,
        lifespan=lifespan,
        # Relative docs URLs so they work behind Ingress.
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(IngressPathMiddleware)
    app.add_exception_handler(AppError, app_error_handler)

    # Health is intentionally registered at the root (watchdog target).
    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(home_assistant.router)
    app.include_router(storage_units.router)
    app.include_router(profiles.router)
    app.include_router(history.router)
    app.include_router(settings_api.router)
    app.include_router(dashboard.router)
    app.include_router(incidents.router)
    app.include_router(defrost.router)
    app.include_router(diagnostics_api.router)
    app.include_router(reports_api.router)
    app.include_router(report_branding_api.router)
    app.include_router(history_import_api.router)
    app.include_router(maintenance_api.router)
    app.include_router(email_settings_api.router)
    app.include_router(schedules_api.router)
    app.include_router(backup_api.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    index_file = STATIC_DIR / "index.html"

    # index.html must never be cached: it references content-hashed assets that
    # change on every build. A stale cached index.html would point at assets that
    # no longer exist (404) and leave a blank page after an update.
    _html_headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    if STATIC_DIR.is_dir() and index_file.exists():
        # Serve hashed assets (Vite emits them under /assets) and index.html.
        app.mount(
            "/assets",
            StaticFiles(directory=STATIC_DIR / "assets"),
            name="assets",
        )

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(index_file, headers=_html_headers)

        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(path: str, request: Request):
            # API routes are matched first; anything else falls back to the SPA.
            # Strip leading slashes so a forwarded "/assets/x" does not become an
            # absolute path on join, and reject path traversal outside STATIC_DIR.
            rel = path.lstrip("/")
            static_root = STATIC_DIR.resolve()
            candidate = (static_root / rel).resolve()
            if (
                rel
                and (candidate == static_root or static_root in candidate.parents)
                and candidate.is_file()
            ):
                return FileResponse(candidate)
            return FileResponse(index_file, headers=_html_headers)
    else:

        @app.get("/", include_in_schema=False)
        async def placeholder() -> JSONResponse:
            return JSONResponse(
                {
                    "name": "Refrigeration Logbook",
                    "version": __version__,
                    "message": "Frontend build not present. Run 'npm run build'.",
                }
            )


app = create_app()
