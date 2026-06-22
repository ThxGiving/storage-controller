# Global build argument (declared before the first FROM so it is usable in the
# runtime stage's FROM instruction).
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20

# ---------------------------------------------------------------------------
# Stage 1: build the frontend
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime image (Home Assistant base-python)
# ---------------------------------------------------------------------------
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SC_DATA_DIR=/data

WORKDIR /app

# System libraries (kept minimal for Phase 1+2; WeasyPrint deps added in P5).
RUN apk add --no-cache tzdata

# Python dependencies
COPY pyproject.toml ./
COPY backend ./backend
RUN pip install --no-cache-dir .

# Database migrations
COPY alembic.ini ./
COPY migrations ./migrations

# Built frontend assets
COPY --from=frontend /build/frontend/dist ./backend/app/static

# Startup script
COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
