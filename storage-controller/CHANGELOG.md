# Changelog

All notable changes to the Storage Controller App are documented here.

## 0.1.8 — Unreleased

### Added — Phase 4: incident engine

- Incident detection with a `pending → active → recovering → closed` state
  machine and configurable violation/recovery/offline delays: `temperature_high`,
  `temperature_low`, `sensor_unavailable`, `sensor_stale`, `sensor_invalid`,
  `home_assistant_disconnected`. Extreme values tracked; a single threshold
  crossing never repeats; restarts continue an incident rather than duplicate it.
- Incidents API (list / detail with timeline / acknowledge + document cause,
  corrective action, note) and audit events. New **Incidents** page with a
  documentation form and lifecycle timeline; active incidents shown on dashboard
  cards and aggregated in the header.

### Added — Phase 4: defrost-aware evaluation

- Defrost cycles persisted as operational events (`defrost_cycles`, migration
  0004) with start/end, room/evaporator snapshots & peaks, recovery phase, status
  and classification (`expected_defrost`, `expected_defrost_excursion`,
  `abnormal_defrost`, `recovery_timeout`). Per-unit defrost settings (editable in
  the unit editor).
- Temperature peaks inside a *validated* defrost envelope are classified as
  expected excursions and do not raise critical temperature incidents — but
  measurements are never deleted or suppressed, `defrost = on` is never a blanket
  exemption, and a genuine incident (pre-existing, beyond envelope, or failed
  recovery) still fires and can coexist with `abnormal_defrost`. `recovery_timeout`
  incident when recovery exceeds the configured maximum. Without a defrost entity,
  normal temperature logic applies (clearly stated in the UI).
- Dashboard defrost status pill with recovery progress; detail chart shows defrost
  and recovery as distinct shaded bands plus visible data gaps.

### Fixed

- Editing a storage unit reconciles assignments in place (no UNIQUE violation;
  recorded samples preserved). Negative lower limits save correctly.

## 0.1.7 — Unreleased

### Fixed

- **Editing a storage unit failed with a 500** (`UNIQUE constraint failed:
  entity_assignments.storage_unit_id, role`). Updating a unit cleared and
  recreated its assignments, and SQLite flushed the INSERT before the DELETE,
  colliding with the existing role. Assignments are now reconciled **in place**
  (existing role updated, new roles added, dropped roles removed). This also
  **preserves recorded samples** across an edit, because the assignment id is
  kept (sensor_samples reference it). Negative lower limits (e.g. -25 °C for a
  deep-freeze room) now save correctly, so the permitted-range band appears in
  the gauge.

## 0.1.6 — Unreleased

### Added — Phase 3A: independent data collection

- A backend **sample collector** records assigned-entity samples from the single
  Home Assistant WebSocket connection into SQLite, independently of the Recorder.
  Only entities assigned to a storage unit are recorded.
- `sensor_samples` and `state_samples` tables (migration 0002) with
  `UNIQUE(entity_assignment_id, event_timestamp)` deduplication.
- Celsius/Fahrenheit normalization with quality flags (`valid`, `unknown`,
  `unavailable`, `invalid`, `implausible`); unknown/unavailable/NaN/missing
  values are **never** coerced to zero — they become visible chart gaps.
- Reconnect reconciliation (idempotent), out-of-order protection, and a
  configurable **heartbeat** sample interval for stable temperatures.
- High-water marks are seeded from the DB so collection survives App restarts
  without duplicates.
- History API `GET /api/storage-units/{id}/samples` with time-bucket
  downsampling and visible gaps; `GET/PATCH /api/settings` for heartbeat and
  retention. Retention values are stored but destructive cleanup is intentionally
  not yet implemented (will land with tests).

### Added — Phase 3B: operational dashboard

- New `GET /api/dashboard` aggregation with server-computed operational status
  (`normal`, `near_limit`, `outside_range`, `unavailable`, `stale`,
  `disconnected`, `configuration_error`).
- A purpose-built, responsive dashboard (shadcn/ui foundation) with one rich card
  per unit: dominant temperature hero, 24h mini-chart with gaps, horizontal
  temperature range gauge (with numeric values, not color-only), data-quality and
  status indicators, and an operational-state strip for assigned compressor / fan
  / defrost / setpoint / evaporator. Dashboard header with connection state and
  unit counts; loading skeletons, empty and error states.
- Storage-unit detail view with a large ECharts time-series chart, threshold and
  setpoint lines, visible gaps, a segmented 24h/7d/30d time-range control, and
  range statistics. Full English/German translations, dark/light mode.

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
