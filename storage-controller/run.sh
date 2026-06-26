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
# 3. Verify the DB schema is not from a newer, incompatible app version
# 4. Start the FastAPI/uvicorn web server on 0.0.0.0:8099
# ---------------------------------------------------------------------------
set -euo pipefail

DATA_DIR="${SC_DATA_DIR:-/data}"
mkdir -p "${DATA_DIR}/reports" "${DATA_DIR}/backups" "${DATA_DIR}/uploads" "${DATA_DIR}/logs"

echo "[run.sh] Applying database migrations..."
cd /app
# alembic upgrade head migrates older schemas forward.
# If the DB is at an unknown future revision (e.g. restored from a newer app
# version), Alembic itself will exit non-zero; the explicit check below adds
# a clear error message for that case.
if ! alembic upgrade head 2>&1; then
    echo "[run.sh] ERROR: Database migration failed. If the database was restored"
    echo "         from a newer version of Refrigeration Logbook, downgrading is"
    echo "         not supported. Restore from a compatible backup or update the app."
    exit 1
fi

# After a successful upgrade, confirm the DB is at the expected head revision.
# A mismatch indicates the DB is ahead of this app version (future schema).
DB_REV=$(alembic current 2>/dev/null | grep -Eo '\(head\)' || true)
if [ -z "$DB_REV" ]; then
    # DB revision is not at head — could be future revision or branch conflict.
    CURRENT=$(alembic current 2>/dev/null | head -1 || echo "unknown")
    echo "[run.sh] ERROR: Database schema is not at the expected revision after"
    echo "         migration. Current: ${CURRENT}"
    echo "         The database may have been created by a newer version of this"
    echo "         app. Downgrading is not supported. Update the app to match."
    exit 1
fi

echo "[run.sh] Starting Storage Controller web server on 0.0.0.0:8099"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --app-dir /app/backend \
    --proxy-headers \
    --forwarded-allow-ips "*" \
    --no-server-header
