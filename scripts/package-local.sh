#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build a sanitized local Home Assistant App installation package.
#
# Produces  storage-controller-<version>.tar.gz  containing only the add-on
# source needed to drop into the Home Assistant /addons share. Excludes build
# artifacts, virtualenvs, node_modules, databases and any local/runtime data.
#
# Usage:  ./scripts/package-local.sh
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(grep -E '^version:' storage-controller/config.yaml | awk '{print $2}')"
OUT="storage-controller-${VERSION}.tar.gz"

echo "Packaging Storage Controller ${VERSION} -> ${OUT}"

tar czf "${OUT}" \
  --exclude='__pycache__' \
  --exclude='*.py[cod]' \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='frontend/dist' \
  --exclude='backend/app/static' \
  --exclude='*.db' \
  --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  --exclude='.devdata' \
  --exclude='.devcli' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='.mypy_cache' \
  storage-controller

echo "Done. Extract this into the Home Assistant /addons share:"
echo "  tar xzf ${OUT} -C /addons"
