#!/usr/bin/with-contenv bashio
# ---------------------------------------------------------------------------
# Storage Controller startup script
#
# The `with-contenv` shebang loads the Home Assistant container environment
# (including SUPERVISOR_TOKEN) provided by the s6 overlay, so the backend can
# authenticate against the Supervisor proxy.
#
# 1. Ensure the persistent data directory exists below /data
# 2. Run database migrations (Alembic) before serving any traffic
# 3. Start the FastAPI/uvicorn web server on 0.0.0.0:8099
# ---------------------------------------------------------------------------
set -euo pipefail

DATA_DIR="${SC_DATA_DIR:-/data}"
mkdir -p "${DATA_DIR}/reports" "${DATA_DIR}/backups" "${DATA_DIR}/uploads" "${DATA_DIR}/logs"

echo "[run.sh] Applying database migrations..."
cd /app
alembic upgrade head

echo "[run.sh] Starting Storage Controller web server on 0.0.0.0:8099"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir /app/backend \
    --proxy-headers \
    --forwarded-allow-ips "*" \
    --no-server-header
