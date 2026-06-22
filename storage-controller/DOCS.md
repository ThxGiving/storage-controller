# Storage Controller — Documentation

## Architecture

Storage Controller is a self-contained containerized **Home Assistant App**
(not a custom integration). It talks to Home Assistant Core through the internal
Supervisor proxy and exposes its own web UI through Ingress.

```
Home Assistant Core ──REST/WebSocket──> Storage Controller (backend)
                                              │
                                         FastAPI + SQLite
                                              │
                                          Ingress ──> Sidebar UI
```

- **Backend:** Python, FastAPI, SQLAlchemy 2 (async, aiosqlite), Alembic, httpx,
  websockets.
- **Frontend:** React + TypeScript + Vite + TailwindCSS (shadcn-style UI),
  Apache ECharts.
- **Database:** SQLite with WAL mode and foreign keys, stored at
  `/data/storage-controller.db`.

The backend is the only Home Assistant API client. The browser never connects
directly to Home Assistant.

## Home Assistant communication

- REST base URL: `http://supervisor/core/api/`
- WebSocket URL: `ws://supervisor/core/websocket`
- Authentication: `SUPERVISOR_TOKEN` environment variable (Bearer token).

The token is never stored in the database, exposed to the frontend, or logged.

The WebSocket client maintains one long-lived connection, authenticates,
retrieves current states, subscribes to `state_changed`, and reconnects
automatically with exponential backoff. Connection health is exposed as an
application status (`connected` / `reconnecting` / `disconnected` /
`authentication_error`) and does **not** make the container unhealthy.

## Ingress

The web application works under a dynamic path prefix
(`/api/hassio_ingress/<session-id>/`):

- All frontend assets use relative paths (`vite base: "./"`).
- API and WebSocket calls are constructed relative to the current page URL.
- The backend honours `X-Ingress-Path` and forwarded headers and never issues
  absolute redirects.

## Data & backups

All persistent state lives below `/data`:

```
/data/storage-controller.db
/data/reports/
/data/backups/
/data/uploads/
/data/logs/
```

Preferred backup mode is **cold** so Supervisor stops the App during backup and
avoids inconsistent SQLite snapshots.

## Local development

Requirements: Python 3.12+ and Node 22+.

### Backend

```bash
cd storage-controller
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run migrations against a local dev database
SC_DATA_DIR=./.devdata alembic upgrade head

# Run the API (dev fallback works without a Supervisor connection)
SC_DATA_DIR=./.devdata uvicorn app.main:app --app-dir backend --reload --port 8099
```

Set `HA_BASE_URL` and `HA_TOKEN` to test against a real Home Assistant instance
outside of the Supervisor environment.

### Frontend

```bash
cd storage-controller/frontend
npm install
npm run dev      # dev server (proxies /api to the backend)
npm run build    # production build into dist/
npm run test     # vitest
```

### Tests

```bash
cd storage-controller
pytest                       # backend
cd frontend && npm run test  # frontend
```

## Container build

```bash
docker build \
  --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12 \
  -t storage-controller storage-controller/
```

## Environment variables

| Variable           | Default                       | Description                                  |
| ------------------ | ----------------------------- | -------------------------------------------- |
| `SC_DATA_DIR`      | `/data`                       | Persistent data directory                    |
| `SUPERVISOR_TOKEN` | _(set by Supervisor)_         | Home Assistant API token                     |
| `HA_BASE_URL`      | `http://supervisor/core/api`  | Override HA REST base (dev only)             |
| `HA_WS_URL`        | `ws://supervisor/core/websocket` | Override HA WebSocket URL (dev only)      |
| `HA_TOKEN`         | _(falls back to SUPERVISOR_TOKEN)_ | Override HA token (dev only)            |
| `SC_LOG_LEVEL`     | `INFO`                        | Log level                                    |
