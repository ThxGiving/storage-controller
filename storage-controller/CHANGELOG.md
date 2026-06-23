# Changelog

All notable changes to the Storage Controller App are documented here.

## 0.3.0 — Unreleased

### Added — Home Assistant history import (embedded in the unit flow)

- Import recorded temperature history directly from the storage-unit detail view
  (no separate menu). When a primary sensor is set, availability is checked and a
  compact "Import available Home Assistant history" control offers all / current
  month / last 30 / last 90 days (sensible default). Import runs **asynchronously**
  (never blocks unit creation) with progress, result and retry shown inline.
- Uses recorder **raw history** where available and **long-term hourly statistics**
  (min/max/mean, into `sensor_aggregates` marked `ha_statistics`) for older periods
  — hourly precision is labelled as such, never minute-level. Imported samples are
  marked `home_assistant_history_import`; repeated imports are de-duplicated.
- States surfaced: history available / only long-term hourly statistics / no older
  history / importing / imported from…to… / failed. Imports **never** create live
  incidents or notifications (historical threshold crossings are reportable only).
  Migration 0009 (`history_imports`, `sensor_aggregates.source`).

### Fixed — report chart timeline, gaps and German locale

- Charts now always span the **full reporting period** on the x-axis (e.g.
  01.06.–30.06.); sparse data appears only at its real position and is never
  stretched across the width.
- Genuine gaps are honest: buckets are positioned at their actual timestamps and
  rendered only when they contain valid data; the line and min–max envelope break
  at gaps (leading, internal and trailing) with no interpolation and no extension
  of the first/last value. Missing/unavailable periods are shaded as data gaps,
  never as violations.
- **German locale formatting**: `7,7 %`, `3,9 °C`, `0,0 – 8,0 °C`, `16 min`,
  `23.06.2026, 01:05`. English reports keep English formatting.

### Fixed — theme follows Home Assistant

- The app theme now follows Home Assistant / OS light-dark (`prefers-color-scheme`)
  by default and live, instead of forcing dark; a manual toggle still overrides and
  persists.

## 0.2.2 — Unreleased

### Fixed — report visual/semantic correction pass

Focused corrections on top of the 0.2.1 redesign (template/CSS/chart only; the
report model gained additive presentation fields, no architecture change).

- **Chart interval semantics (highest priority).** Red shading now marks **only
  measured threshold violations** derived from raw samples — never extended
  across a gap or to the period end. Missing **and** unavailable/invalid data is
  shaded yellow and aligned to where the line actually breaks (so coarse-but-
  present sampling is no longer painted yellow); the line is never connected
  across a gap. Defrost stays blue, aligned at absolute timestamps.
- **Adaptive chart aggregation** for hysteresis-heavy data: deterministic hourly
  buckets for monthly reports (bucket width grows past `max_points=800` to keep
  PDFs bounded), rendering one calm average line plus a subtle **min–max
  envelope** that preserves short excursions. Metrics and incidents continue to
  use raw samples — aggregation never changes counts, durations, extrema or
  metrics (proven by tests).
- **Status semantics** separated and documented: `open` (red) → `incomplete`
  (gray, `coverage < 90 %` / missing sensor — no conformity statement) →
  `reviewed` (blue) → `ok` (green). A reviewed incident no longer makes a unit OK.
- **Stable per-unit identity colours** (blue/cyan/green/violet…) reused across
  series, legend, table dot, card accent line and title — no longer derived from
  status (fixes the all-orange accents).
- **Header fallback** when no branding is configured: the title block is centred,
  with no empty left column; the two-column branded header returns automatically
  once branding is set. No placeholder company data is inserted.
- **Summary icons** are now embedded coloured SVGs (thermometer / check-circle /
  alert-triangle / x-circle) with explicit colours — no font/Unicode/`currentColor`
  reliance, reliable in WeasyPrint.
- **Negative values no longer wrap** (`-25.0 – -18.0 °C`, `-21.0 °C`).
- Verified DE+EN at 3/4/5 units and a sparse low-coverage real-style report — all
  two pages, no clipping; new deterministic tests in `tests/test_report_charts.py`
  (envelope preserves spikes, in-range average can't hide an out-of-range
  extremum, gaps stay breaks, last state not extended, metrics invariant to bucket
  size). Rules documented in `docs/design/report-layout-spec.md`.

## 0.2.1 — Unreleased

### Changed — report PDF redesigned to match `report_mockup.png`

Focused redesign of the report HTML template, print CSS and chart rendering (the
report model, snapshot logic, exports and generation pipeline are unchanged; the
immutable model gained additive presentation fields → model version 2).

- **Branded header**: logo + organization + address (left), title + month +
  full reporting period + creation timestamp + report ID + IANA timezone/offset
  (right).
- **Overall summary** (`GESAMTÜBERSICHT`): four metric tiles with icons
  (monitored units, overall coverage, confirmed deviations, open incidents) plus
  an overall-assessment verdict.
- **Comparison table** in a section container with type subtitle, permitted
  range, min/ø/max, time outside range, coverage, incidents and a status badge.
- **Monthly charts**: two compact stacked groups (chilled / deep-freeze) with
  colored per-unit lines, configured limit lines, deviation / data-gap / defrost
  shading, a compact legend and month date labels — no interpolation across gaps.
  Localized limit-line legend (Upper/Lower limit · Oberer/Unterer Grenzwert).
- **2×2 detail cards** with a colored accent line, accent-colored title, status
  badge, permitted-range + coverage row, a horizontal metric row and a compact
  mini-chart. **Adaptive layout**: 3 units render as two cards + one wide card;
  4 units as 2×2; 5+ flow into balanced rows. No fake fillers.
- **Incident summary table** (`VORFÄLLE`) and separate **data-quality** and
  **approval/signature** panels; complete footer (app version + page numbers +
  disclaimer) via running margin boxes.
- Verified by rendering the deterministic fixture in German and English at 3, 4
  and 5 units — all two pages, no clipping/overflow, balanced page usage.
  `docs/design/report-layout-spec.md` documents the measured target.

## 0.2.0 — Unreleased

### Added — Phase 5: HACCP reporting & PDF export

- **Immutable report model.** PDF, CSV and JSON are all derived from one
  versioned report model (never from DB rows or the dashboard). Pipeline:
  SQLite → report model → Jinja2 HTML + print CSS → server-side SVG charts →
  WeasyPrint PDF.
- **Monthly reports** with a compact **two-page** target for ~4 units: page 1 =
  header/branding, status strip, comparison table, up to two overview charts
  (grouped data-/config-driven into chilled vs frozen, not by hardcoded names);
  page 2 = a 2×2 detail grid (mini-chart, min/max/avg, coverage, unavailable,
  time above/below limit, incidents, defrost summary, data-quality) + a
  review/signature area. Detail levels: compact / **standard** (default) /
  detailed (adds an incident timeline).
- **Metrics**: min/max/avg, valid/expected counts, coverage %, unavailable/
  invalid/gap durations, time above/below the **configured** limits, incident
  count/total/longest/extreme, defrost cycle/duration/recovery/abnormal counts.
  Configured safety limits, learned operational defrost values and measured data
  are clearly distinguished; learned values are never presented as HACCP limits.
- **Server-side SVG charts**: print-readable, grayscale-distinct series, explicit
  °C units, configured limit lines, timezone-aware day axis, and visible gaps
  (missing periods are breaks, never interpolated).
- **Immutable snapshots**: each report freezes the model JSON, a branding
  snapshot, unit names + threshold snapshot, locale, timezone and detail level,
  with a SHA-256 checksum. Later edits to units, profiles, branding or incidents
  never change an already-generated report. Files are finalized atomically under
  `/data/reports/<uuid>/` (PDF/CSV/JSON); a failed generation is never marked
  completed and temp files are cleaned up.
- **Branding**: organization/site/contact, report title/subtitle, footer,
  disclaimer, signature labels, default locale/timezone/detail, plus a validated
  PNG/JPEG **logo upload** (≤ 2 MB, UUID filename under `/data/uploads`).
- **Report localization** (per report, en/de) of headings, labels, status and
  disclaimers; user-entered free text (incident notes/corrective actions) is
  never auto-translated. Default report timezone is the configured IANA zone with
  CET/CEST shown; timestamps stored in UTC.
- **API** (`/api/reports` preview/create/list/get/pdf/csv/json/delete +
  `/api/report-branding` get/patch/logo): Ingress-authenticated, admin-gated
  create/delete (audited), bounded month range, validated unit selection, safe
  UUID filenames, streamed downloads, duplicate-generation guard, and a clear
  status (queued/generating/completed/failed) with sanitized error messages (no
  stack traces). PDF rendering runs in a worker thread so the event loop isn't
  blocked.
- **Reports UI**: a new Reports section — month/unit/locale/detail config, a
  print-approximating preview, generation + failed states, PDF/CSV/JSON downloads,
  checksum display, delete confirmation, and branding settings. Full en/de.
- **Migration 0008** (`reports`, `report_branding_settings`). Dockerfile gains
  Pango/fonts + Pillow build deps for WeasyPrint; report templates ship as
  package data.

## 0.1.12 — Unreleased

### Phase 4.7 — Defrost diagnostics & stabilization

Root cause of the original "TK defrost not detected" (confirmed on the real
instance): the freezer was configured with only a lower limit, so recovery — gated
on the upper limit — never completed and cycles weren't counted. Fixed in 0.1.11
(baseline-recovery fallback); the real-instance trace now shows the TK cycle
**completed and counting toward learning**. This release adds the diagnostics and
stabilization to make such issues self-evident.

### Added

- **Admin-only diagnostics mode** (`POST /api/diagnostics/logging/enable|disable`,
  `GET /api/diagnostics/logging/status`): disabled by default, default 30 minutes,
  auto-expiring, manual disable, visible countdown. Ingress-authenticated only.
- **Structured, bounded log buffer** (`GET /api/diagnostics/logs`): in-memory ring
  buffer (≤1000 buffered, ≤200 returned, oldest discarded), filterable by
  component / storage_unit_id / entity_id / severity / since. Populated only while
  the mode is active.
- **Redaction** of every message/field: SUPERVISOR_TOKEN, Authorization headers,
  cookies, session ids, SMTP passwords, API keys, private keys and full
  environment values are never disclosed.
- **Expanded event result codes**: `reconciled_on_reconnect`, `out_of_order_event`,
  `cycle_started`, `cycle_ended`, plus the existing `stored`, `duplicate_ignored`,
  `ignored_unchanged`, `normalization_failed`, `unavailable`.
- **Reconnect reconciliation**: when the App starts/reconnects while defrost is
  already active, the cycle start is **reconstructed** from the last persisted
  "on" sample (migration 0007 `defrost_cycles.reconstructed`) instead of
  fabricating a precise "now" timestamp; the cycle is flagged accordingly.
- Diagnostics now expose `last_completed_cycle_id` and `last_cycle_reconstructed`.
- **Diagnostics UI** (Settings): mode toggle with live countdown, copy and
  download of sanitized diagnostics JSON, plus the per-mapping chain and recent
  events. `docs/current-status.md` added.

### Notes

- No raw SQL, no arbitrary filesystem access, no environment-variable dumping.
- All Phase 4.6 safety rules preserved (no learned HACCP limits, no blanket
  defrost exemption, no auto-approval, no suppression before approval).

## 0.1.11 — Unreleased

### Fixed — defrost detection for non-standard controllers

- **Configurable defrost state mapping.** A defrost entity that reports values
  other than on/off (e.g. a Dixell coil reporting `defrosting`/`cooling`) was
  normalized to *invalid* → the engine never saw a defrost signal and no cycle
  was detected. Binary roles now accept an optional per-entity active/inactive
  value mapping (set in the unit editor, applied by both the collector and the
  defrost engine). Normalization now reports a precise reason
  (`unrecognized_state`, `unavailable`, …).
- **Freezers without an upper limit** could never complete a defrost cycle
  (recovery target was the upper safety limit). Recovery now falls back to the
  pre-defrost baseline temperature when no upper limit is configured.

### Added — targeted diagnostics

- `GET /api/diagnostics/defrost` — per defrost mapping: raw state, normalized
  value + reason, value mapping, engine state, active/last cycle, last event
  received/persisted, last engine evaluation, connection status, and a
  human-actionable `problem` when detection is blocked.
- `GET /api/diagnostics/entities/{entity_id}` and
  `GET /api/diagnostics/events/recent` — a bounded in-memory event trace
  (old/new raw + normalized values, mapping found, persisted, result such as
  `stored`, `ignored_duplicate`, `ignored_unchanged`, `normalization_failed`).
- Admin-only, auto-expiring (15 min) per-entity **trace mode**. No tokens,
  credentials or unrelated entity data are ever logged. No raw SQL / DB access.
- A **Defrost diagnostics** card in Settings surfaces all of the above and
  highlights the exact blocker (e.g. an unrecognized raw state).

### Changed — defrost learning UX

- The "valid cycles" indicator now reads `1 / 10` with a clear "N more cycles
  until the first suggestion" hint (the previous "1 of 10 needed" was
  ambiguous).
- The learning panel lists recent cycles and whether each counts toward learning.

## 0.1.10 — Unreleased

### Added — Phase 4.6: defrost learning + single-toggle UX

- **Optional defrost learning.** The app observes complete, valid defrost cycles
  and learns operational characteristics — typical/maximum duration, room and
  evaporator peaks, recovery time, frequency and normal variation — using robust
  statistics (median, p95, MAD, IQR outlier exclusion + a conservative safety
  margin). A single outlier can never become a learned bound. Safety temperature
  limits are **never** learned or changed (migration 0006, `defrost_learned_models`).
- **Explicit approval required.** A suggestion is advisory until a human approves
  it (optionally editing the bounds). Only an **approved** model lets the engine
  reclassify in-envelope defrost excursions as expected. Approving, resetting and
  drift are audited. Confidence: insufficient `<10`, preliminary `10–19`, high `≥20`.
- **Safer gating.** With defrost-aware evaluation on but no approved model,
  excursions during defrost stay real incidents flagged *potentially
  defrost-related* — never auto-suppressed, closed or downgraded. `defrost = on`
  is never a blanket exemption. Recovery now completes against the unit's normal
  upper safety limit (not a hand-entered target); gross stuck-defrost / failed-
  recovery still raise incidents via conservative built-in bounds before learning.
- **Drift detection.** Once a model is approved, new cycles are compared against
  it; material drift raises a warning and suggests retraining, but never changes
  behaviour silently.
- **Single-toggle UX.** The unit editor now exposes only one control —
  *Defrost-aware evaluation* — available only when a defrost entity is assigned.
  The five manual defrost fields are gone. The learned profile, confidence, valid
  cycles, typical/max metrics, drift warnings and approve/reset live in an
  advanced panel in the unit detail view. New `defrost` translation namespace
  (en/de). Learned values are clearly marked operational-only, never legal/HACCP.

## 0.1.9 — Unreleased

### Added — Phase 4.5: bounded retention, aggregation, storage & timezone

- **IANA timezone display**: configurable zone (default `Europe/Berlin`) shown
  with the current abbreviation and offset (`Europe/Berlin · CEST · UTC+02:00`,
  auto `CET · UTC+01:00` in winter). Timestamps remain stored in UTC.
- **Bounded recording**: configurable minimum temperature delta (default 0.1 °C)
  and heartbeat; binary roles store state changes only; quality/availability
  transitions are always recorded; reconnect deduplication unchanged.
- **Data tiers + aggregation**: raw samples are aggregated into 15-minute and
  hourly tiers (migration 0005). Configurable retention per tier (raw 24 months,
  15-min 5 years, hourly 10 years).
- **Bounded daily maintenance**: aggregate → delete expired raw **only after the
  covering aggregates exist** → delete expired aggregates → WAL checkpoint →
  integrity check → storage calculation. Batched deletes, no blanket `VACUUM`.
  Reports, incidents, manual checks and audit records are never deleted.
- **Storage monitoring**: database/WAL/reports/uploads/logs sizes, app total,
  free filesystem space; configurable budget (default 2 GB) with warning/
  critical/emergency thresholds. Emergency suspends non-essential heartbeat
  samples (critical events still recorded). `GET/POST /api/maintenance`.
- **Settings UI** for timezone, recording limits, retention, storage budget and
  thresholds, plus a live storage-usage breakdown and a maintenance run action;
  a persistent storage-warning banner. Full en/de.

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
