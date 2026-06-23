# Global build argument (declared before the first FROM so it is usable in the
# runtime stage's FROM instruction).
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20

# ---------------------------------------------------------------------------
# Stage 1: build the frontend
#
# Pinned to the build platform ($BUILDPLATFORM) so cross-arch image builds do
# not run the heavy npm/vite build under QEMU emulation.
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

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

# System libraries. WeasyPrint (Phase 5 PDF) renders text via Pango and rasters
# logos via Pillow; these need Pango/Fontconfig/fonts + JPEG/zlib at runtime.
RUN apk add --no-cache \
        tzdata \
        pango \
        fontconfig \
        ttf-dejavu \
        font-noto \
        libjpeg-turbo \
        zlib \
    && fc-cache -f

# Python dependencies. cffi (Pango bindings) and Pillow have no musl wheels, so
# they compile from source — install build deps in a virtual group and drop them.
COPY pyproject.toml ./
COPY backend ./backend
RUN apk add --no-cache --virtual .build-deps \
        gcc \
        musl-dev \
        python3-dev \
        libffi-dev \
        jpeg-dev \
        zlib-dev \
    && pip install --no-cache-dir . \
    && apk del .build-deps

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
