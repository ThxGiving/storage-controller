# Changelog

All notable changes to the Storage Controller App are documented here.

## 0.1.5 — Unreleased

### Added

- **Prebuilt images.** `config.yaml` now declares an `image:`, so Home Assistant
  pulls a prebuilt per-architecture image from GHCR
  (`ghcr.io/thxgiving/storage-controller-{arch}`) instead of building on the
  device. A `build-images` workflow builds and pushes amd64/aarch64 images with
  the required `io.hass.*` labels on every `v*` tag. The frontend build stage is
  pinned to `$BUILDPLATFORM` so cross-arch builds don't emulate the npm build.

### Fixed

- Numeric entity states are rounded and locale-formatted for display (e.g. a raw
  sensor float `5.90000009536743 °C` now shows as `5,9 °C`). Non-numeric states
  (on/off, unavailable, text) are shown unchanged.

## 0.1.4 — Unreleased

### Fixed

- **Entities missing from the browser and role selectors on larger installs.**
  The frontend fetched entities with the backend's default cap of 500 (sorted by
  entity id), so on instances with many entities (e.g. 800+) later sensors such
  as `sensor.kuhlhaus_1_temperatur` were cut off and could not be assigned. The
  frontend now requests the full entity set, so client-side search and the
  storage-unit role selectors see every entity.

## 0.1.3 — Unreleased

### Added

- A visible startup error overlay: if the SPA throws during boot (e.g. inside
  the Ingress iframe), the error and stack are rendered in `#root` instead of a
  blank white page, and reported via `window.onerror` / `unhandledrejection`.

### Fixed / Hardened

- All `localStorage` access (i18n language preference) is wrapped in try/catch so
  a restricted iframe/privacy context can no longer crash startup.
- Removed the `crossorigin` attribute from built asset tags (unnecessary for
  same-origin assets behind Ingress; avoids a potential iframe loading issue).
- Asset filename hashes changed, which sidesteps a stale Home Assistant
  service-worker cache that could otherwise keep serving the previous build's
  broken responses after an update.

## 0.1.2 — Unreleased

### Fixed

- **Assets 404 behind Ingress (blank page, continued).** Setting the ASGI
  `root_path` from `X-Ingress-Path` interfered with static-mount routing in
  current Starlette, so `/assets/*` returned 404 behind real Ingress. The app
  uses only relative paths and never needs `root_path`, so it is no longer set
  (leading-slash normalization is kept). Verified in-container with an
  `X-Ingress-Path` header: `//assets/*.js` now returns `text/javascript`.
- `index.html` is now served with `Cache-Control: no-cache, no-store,
  must-revalidate` so a stale cached page can never point at removed,
  content-hashed assets after an update.

### Changed

- Dockerfile uses `npm ci` against the committed lockfile for reproducible
  frontend builds (stable asset hashes across hosts).

## 0.1.1 — Unreleased

### Fixed

- **Blank UI under Home Assistant Ingress.** Ingress can forward requests with a
  duplicated leading slash (`//`, `//assets/...`). Those bypassed the static
  mount and the SPA fallback served `index.html` for JS/CSS (wrong content type),
  producing a white page. The request path is now normalized (duplicate leading
  slashes collapsed) and the SPA fallback strips leading slashes and guards
  against path traversal. Verified in-container: `//assets/*.js` now returns
  `text/javascript`. Regression test added.

## 0.1.0 — Unreleased

### Added (Phase 1 + 2)

- Valid Home Assistant App repository structure (`repository.yaml`, `config.yaml`,
  `build.yaml`, `Dockerfile`, `run.sh`, AppArmor profile, translations).
- FastAPI backend served through Home Assistant Ingress on port 8099.
- Ingress-safe React + TypeScript + Vite frontend (TailwindCSS, shadcn-style UI).
- SQLite database (WAL, foreign keys) with Alembic migrations.
- Home Assistant REST client and long-lived WebSocket client with automatic,
  exponential-backoff reconnect.
- Connection-status reporting (`connected` / `reconnecting` / `disconnected` /
  `authentication_error`).
- Entity browser: search Home Assistant entities by ID and friendly name with
  domain, state, unit, device and last-changed information.
- Health endpoint (`/health`) that reports healthy only when the web server,
  database and migrations are ready.
- Storage-unit CRUD with free, role-based entity assignment, searchable entity
  selectors, live mapped values, threshold configuration and validation.
- Storage-unit **types** and editable **monitoring profiles** (built-in,
  read-only templates plus user copies); applying a profile snapshots its values
  into the unit. Supports lower-only, upper-only and both-limit profiles.
- Opt-in, idempotent demo seed (`STORAGE_CONTROLLER_LOAD_DEMO_DATA` /
  `storage-controller seed-demo`). Production starts with no storage units.
- Full **internationalization** (English source/fallback + first-class German)
  via i18next: namespaced bundles, language detection (preference → Home
  Assistant → browser → English), in-app language switch, locale-aware number
  and date formatting, German decimal input, and a translation-completeness test.
- Machine-readable API error codes (`{ "code", "details" }`) translated by the
  frontend.
- Audit events for configuration changes.
- German and English App translations.
- Backend (pytest) and frontend (vitest) test suites.

### Notes

- The startup script uses the `with-contenv bashio` shebang so the s6 overlay
  exports the Home Assistant container environment (incl. `SUPERVISOR_TOKEN`).

### Security

- `SUPERVISOR_TOKEN` is never stored, logged or exposed to the frontend.
- Structured logging with secret redaction.
- No privileged, host-network or unnecessary host permissions.
