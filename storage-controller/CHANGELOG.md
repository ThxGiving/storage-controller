# Changelog

All notable changes to the Refrigeration Logbook App are documented here.

## 0.4.22 — 2026-06-26

### Added — Render-time diagnostics logging

`render_html` now emits an INFO log entry on every PDF render:

```
render: uuid=<report-uuid> dl=<compact|standard|detailed> app=<version> tpl_mtime=<unix-ts> css_mtime=<unix-ts> locale=<de|en>
```

`tpl_mtime` and `css_mtime` are the filesystem modification timestamps of
`report.html` and `print.css` at render time. This makes it possible to
confirm which exact template and stylesheet revision produced a given PDF,
and to verify that the running instance uses the expected artifact.

## 0.4.21 — 2026-06-26

### Fixed — Stage 1 residual defects

**Compact single-page fit (3-unit installation)**
- Overview charts rendered at `plot_h=80` when detail level is compact
  (down from 132). For a 3-unit installation this saves ~50mm of vertical
  space, allowing DQ statement and approval panels to fit on page 1 below
  the incident summary rather than being pushed to an almost-empty page 2.
- Added `dl-compact` class to body; CSS `.dl-compact .box` tightens box
  margins and body padding moderately to further reduce vertical footprint
  without affecting typography readability.

**Detailed incident table flow (starts on page 2)**
- Root cause: `.box { break-inside: avoid }` made the entire incident table
  box indivisible. For a 3-unit installation with 20+ incidents the box
  exceeded the remaining space on page 2 and WeasyPrint moved it wholesale
  to page 3, leaving page 2 half-empty after the unit cards.
- Fix: `<section class="box frag">` on the detailed incident table and
  per-unit DQ table. The new `.box.frag { break-inside: auto }` CSS rule
  allows these large tables to span pages while keeping all other boxes
  (summary metrics, comparison table, unit cards, panels) non-fragmented.
  Table rows still carry `break-inside: avoid` (from v0.4.20) and `<thead>`
  still repeats via `display: table-header-group`.

**Empty-value consistency ("Keine" → "—")**
- The `val` Jinja2 filter now normalises a set of common empty-marker
  strings — "keine", "none", "n/a", "-" — to em dash in addition to
  Python None and empty string. Handles HA integrations that write "Keine"
  as a default text value for cause/action/note fields.

## 0.4.20 — 2026-06-26

### Fixed — Stage 1 layout and pagination defects

**Detailed incident table**
- `break-inside: avoid` on every `<tbody tr>` in `.inc` — rows no longer split
  across page boundaries; orphaned timestamp cells eliminated
- `display: table-header-group` on `<thead>` — column headers repeat on every
  continuation page
- Table renamed from "INCIDENTS (SUMMARY)" to "INCIDENT DETAILS" / "VORFÄLLE —
  DETAILS" to reflect that all rows are shown

**Compact single-page composition**
- Compact now uses a single `<section class="page">` instead of two sections;
  content flows naturally with WeasyPrint pagination instead of a forced
  page break after the charts — for typical installations the report fits on
  one page; overflow carries naturally to page 2
- Comment field restored in approval area (all three levels now have the same
  four approval fields: Reviewed by / Date / Signature / Comment)

**Consistent empty-value rendering**
- Added `val` Jinja2 filter: renders `None` and empty strings as em dash (`—`)
  rather than blank cells; applied to cause, corrective action and notes columns

**Architecture**
- Page-1 content extracted to a Jinja2 macro (`page_one_body`) shared by all
  three detail levels; avoids structural duplication in the template

## 0.4.19 — 2026-06-26

### Added — Stage 1: Genuine detail-level compositions

Detail level now controls actual report content, not just a label.

**Compact** — reduced composition (excludes unit detail cards):
- Overall summary, comparison table, overview charts (unchanged from standard)
- Concise incident summary: 4 metrics (total, open, confirmed deviations, longest)
- Single-line data quality statement
- 3-field approval area (Reviewed by, Date, Signature)
- No per-unit detail cards, no incident table, no extended notes

**Standard** — current two-page layout, no visual change (baseline preserved):
- Page 1: header, overall summary, comparison table, overview charts
- Page 2: unit detail cards, first-6-incident table with truncation note,
  data quality statement, 4-field approval area

**Detailed** — standard plus additional sections where data exists:
- All unit detail cards (unchanged from standard)
- Complete incident table with no row limit, plus additional columns:
  end timestamp, notes
- Expanded data quality section with per-unit coverage, unavailable time,
  gap count, and per-unit status
- 4-field approval area

**Architecture**: `detail_level` is now read in `render_html()` and passed as
`dl` to the template. Jinja2 conditionals control section inclusion explicitly.
`FlatIncident` extended with `closed_at` and `note` fields (populated from
`IncidentSummary`); backward-compatible defaults.

## 0.4.18 — 2026-06-26

### Fixed

- **SMTP hostname no longer auto-linked**: wrapped in `<a href="#">` styled as
  plain text (`color:inherit; text-decoration:none; cursor:default`). Email
  clients will not auto-link content already inside an explicit anchor, so
  `mail.example.com` renders as inert text regardless of client settings.
- **Test email locale**: the frontend now sends `locale: i18n.language` with
  every test-email request, so a German UI generates a fully German test email
  and an English UI generates a fully English one.

## 0.4.17 — 2026-06-26

### Fixed

- **Page number wrapping**: "Seite 2 von 2" was wrapping onto two lines in the
  bottom-right margin. Added `white-space: nowrap` to the `@bottom-right`
  page-margin box.

## 0.4.16 — 2026-06-26

### Changed

- **Report summary — count semantics**: small italic sub-labels added under
  *confirmed deviations* and *open incidents* metrics (e.g. "auto-detected,
  documented" / "pending review or action") to clarify the difference.
- **Contact field now labelled**: "Contact: \<name\>" instead of plain name,
  omitted entirely when no contact is configured.
- **Comparison table column widths**: *Incidents* column widened from 6 % to
  8 %, *Status* reduced by 2 %; a thin left border added between *Data
  coverage* and *Incidents* so the two column headers are always separated.
- **Chart band opacity** slightly reduced (deviation 0.28 → 0.22, defrost
  0.25 → 0.20) to reduce visual noise from dense event markers.
- **SMTP test email — polished verification card**: replaced the grey-italic
  action placeholder with a *Connection verification* checklist (SMTP
  connected, TLS successful, authentication successful, message accepted for
  delivery) using green checkmarks.
- **SMTP test email — no HACCP disclaimer**: footer now shows a test-specific
  notice; production HACCP language removed from test email entirely.
- **SMTP test email — hostname/port split** into separate table rows to prevent
  email clients from auto-linking "host:port" as a hyperlink.
- **SMTP test email — full address in header**: the complete site address
  (not just the site name) is now shown in the email header when configured.

## 0.4.15 — 2026-06-26

### Fixed

- **Version numbers in config.yaml / __init__.py were not advancing correctly**
  between releases 0.4.12–0.4.14; HA Supervisor therefore saw no update.
  Corrected; all 0.4.12–0.4.14 changes are now included in this build.

## 0.4.14 — 2026-06-26

### Changed

- **SVG logos are converted to PNG on upload** using cairosvg (same Cairo
  library as WeasyPrint). This eliminates a whole class of SVG rendering
  quirks in the PDF: forward-referenced gradients, unsupported filters, and
  renderer differences between browsers and WeasyPrint. The original SVG file
  is unchanged on the user's device; only the server-side copy is rasterised.
  `cairosvg>=2.7` added as a dependency.

## 0.4.13 — 2026-06-26

### Fixed

- **SVG logo gradients rendering white/transparent in PDF.** WeasyPrint does
  not resolve forward references in SVG: a `<path fill="url(#gradient)">` that
  appears before the `<linearGradient>` in `<defs>` causes the fill to be
  silently dropped. Many design tools (Affinity Designer, Illustrator) place
  `<defs>` at the end of the document. The upload endpoint now moves `<defs>`
  to immediately after the opening `<svg>` tag, making the reference resolvable.
  (Superseded by the full SVG→PNG conversion in 0.4.14.)

## 0.4.12 — 2026-06-26

### Fixed

- **Dark mode not following Home Assistant theme.** The app was reading
  `prefers-color-scheme` (OS setting) but HA has its own dark-mode switch
  independent of the OS. The initial theme script and `ThemeToggle` now read
  `ha.hass.themes.darkMode` from the parent window (same-origin ingress),
  fall back to the `color-scheme` CSS property, and finally fall back to the
  OS media query. A `MutationObserver` on the parent `<html>` element reacts
  to HA theme changes at runtime without a page reload.

## 0.4.11 — 2026-06-26

### Added

- **Logo upload UI redesign.** The branding form now shows a thumbnail preview
  of the current logo, a styled "Logo hochladen" button (hidden native file
  input), and a delete button (trash icon) to remove the logo without replacing
  it. Upload errors are shown inline.
- **DELETE /api/report-branding/logo** endpoint to remove a stored logo and
  its audit record.

## 0.4.10 — 2026-06-26

### Fixed

- **Report header layout.** Changed from `display:flex` with `space-between`
  to `display:grid` with fixed 44 %/56 % columns. The flex layout let the title
  column grow to an unpredictable width because font metrics differ between
  browser preview and WeasyPrint (DejaVu Sans), making the preview an
  inaccurate representation of the PDF. Grid ensures both sides always claim
  the same proportion.
- **Title font size reduced** (h1 14 pt → 12 pt, month 10 pt → 9.5 pt) so the
  header hierarchy matches the A4 content.
- **Logo max-width capped at 56 pt**; org-block uses `flex:1` so the company
  name always gets the remaining space. `word-break:break-word` allows
  multi-line wrapping for long names without per-character splitting.

## 0.4.9 — 2026-06-26

### Added

- **Address field** added to the branding form. The field was present in the
  backend model and rendered in reports but was never exposed in the UI.
  Multi-line textarea; rendered one address line per `\n` in the report header.

### Fixed

- **Company name truncated to single character in PDF header.** `overflow-wrap:
  anywhere` was set on `.org` which caused per-character line breaks when the
  logo consumed most of the brand-block width. Changed to `word-break:
  break-word` with proper `flex:1` on the text column so the name wraps cleanly
  at word boundaries.

## 0.4.8 — 2026-06-26

### Fixed

- **Timestamp inconsistency in reports.** `generated_at`, the interim-report
  data-cutoff note, and incident `opened_at` were displayed in UTC even though
  the period range label used the configured IANA timezone. Added
  `_fmt_dt_local()` with a `dtlocal` Jinja filter that converts timezone-aware
  UTC ISO strings to the report's timezone before formatting.
- **Interim-report badge** moved from inside `<h1>` (crowded the title) to
  alongside the month label.
- **Section headers** changed from solid accent background to neutral `#f8f9fa`
  with a 2 pt accent top border; keeps branding without overwhelming content.
- **Comparison table headers** now wrap (`white-space:nowrap` removed) with
  `vertical-align:bottom` so two-word headers ("Outside range", "Data
  coverage") render fully instead of being clipped.
- **Three-unit card layout** — the lone third card is now centred at 50 % width
  instead of left-aligned across the full grid row.

## 0.4.7 — 2026-06-26

### Fixed

- **Logo color fidelity in PDF.** PNG logos with embedded ICC profiles
  (Display-P3, Adobe-RGB) appeared washed out because WeasyPrint's Cairo
  backend ignores ICC metadata and treats all pixel values as plain sRGB.
  The upload endpoint now uses Pillow `ImageCms.profileToProfile` to convert
  the pixel values to sRGB and saves the file without an embedded profile, so
  Cairo renders the correct colors.

## 0.4.6 — 2026-06-26

### Fixed

- **Report header: logo color fidelity.** Removed `object-fit: contain` from
  the logo CSS rule. WeasyPrint versions before 60 do not support `object-fit`
  on `<img>` elements and silently fall back to a resampling path that degrades
  color fidelity. Natural proportional scaling via `max-height` / `max-width`
  with `width: auto; height: auto` is now used instead, which is reliable across
  all WeasyPrint versions. Logo constraints are also expressed in `pt` rather
  than `px` so they are dimensionally correct in the PDF print context.
- **Report header: company name no longer wraps mid-word.** The branding block
  now receives 54 % of the content width (was 44 %) and the organization name
  uses `white-space: nowrap` with `text-overflow: ellipsis` as a graceful
  fallback for very long names.
- **Report header: full organization details now shown.** The address field is
  rendered one line at a time (was collapsed to a single `·`-separated string).
  The contact field is rendered when configured. Display order: organization
  name → site/branch → address lines → contact.
- **Report header: accent bar.** The thin horizontal rule below the header now
  uses the configured brand accent color instead of a hardcoded dark gray.

## 0.4.5 — 2026-06-26

### Fixed

- Version bump to trigger a new container build carrying all 0.4.4 changes
  (rebrand, accent color, SVG logo support) that landed after the 0.4.4 tag.

## 0.4.4 — 2026-06-26

### Added

- **Configurable organization accent color.** A single `#RRGGBB` hex value stored
  in branding settings is used to derive a full set of design tokens (foreground,
  secondary foreground, subtle background, border, dark, light variants). The
  accent is applied to PDF section-title bars, the header rule, email headers,
  and the "Next Steps" action card in report emails. A color picker with live
  preview, hex input, reset button, and low-contrast accessibility warning is
  available in the branding settings card.
- **SVG logo support.** The logo upload endpoint now accepts `image/svg+xml` in
  addition to PNG and JPEG. Logos are scaled with CSS-only `max-*` constraints
  so aspect ratio is preserved for all three formats.

### Changed

- **Product renamed to Refrigeration Logbook.** All user-facing occurrences of
  "Storage Controller" are replaced with "Refrigeration Logbook". German subtitle:
  "Temperaturüberwachung und HACCP-Dokumentation"; English subtitle: "Temperature
  Monitoring & HACCP Reporting". The sidebar now shows the subtitle below the
  brand name. Internal technical identifiers (HA slug, container image names,
  package names, API paths, database paths) are unchanged — existing installations
  upgrade in place without any re-configuration.

## 0.4.3 — 2026-06-25

### Added

- **Polished branded HTML email for scheduled report delivery.** Emails now use
  a table-based HTML layout (Gmail / Outlook / Apple Mail compatible, no external
  fonts, no JavaScript) with a branded header (logo, organization, site, report
  title, period, optional interim badge), a compliance summary card with
  color-coded verdict, a numbered "Next Steps" action block, an attachment list,
  and a HACCP footer. A matching branded HTML test email is sent when verifying
  SMTP configuration. Both emails are available in German and English. Plain-text
  fallback is always included; HTML render failures fall back to plain text
  without sending a malformed message.
- **Email locale selection.** The test-email API now accepts a `locale` field so
  the test message can be sent in German or English independently of other settings.

### Fixed

- **Comparison table no longer overflows A4 page width.** Added `table-layout:
  fixed` with explicit `<colgroup>` column widths. Padding and font sizes tightened.
  Temperature ranges use non-breaking spaces around the en-dash.
- **Web preview constrained to A4 width.** A `@media screen` block now wraps
  each page in a centered, shadow-boxed A4-wide container so the print preview
  matches printed output rather than stretching to the browser viewport.
- **Wide-card span removed.** The last storage-unit card (when the unit count is
  odd) no longer spans two grid columns. All unit cards render at equal width.

### Changed

- **Navigation restructure.** The top-level "Schedules & Email" sidebar entry is
  removed. Report scheduling is now a sub-tab within the Reports page. SMTP and
  email settings are moved under the Settings page where infrastructure
  configuration belongs.
- **Interim report handling.** Reports generated before the month ends are
  detected and marked as interim. Coverage, incident, defrost, and chart metrics
  all use the effective data window (up to generation time) rather than the full
  calendar month. The report header shows an "Interim Report" / "Zwischenbericht"
  badge with an explanatory note. Period range label shows the actual data window.
- **Incident consolidation.** Adjacent same-type incidents separated by ≤ 30 min
  are merged, preventing hysteresis crossings from inflating incident counts. The
  incident table shows "Showing N of M incidents" when truncated.
- **Chart refinements.** Outlier labels use locale-correct decimal separators and
  include the °C unit. Multiple outlier markers stagger to avoid overlap. Band
  merge thresholds increased (defrost 4 h, gap 2 h, deviation 1 h). Band opacity
  reduced (deviation 0.28, defrost 0.25).

## 0.4.2 — 2026-06-25

### Fixed

- **Report charts: P1/P99 y-axis domain.** A single sensor outlier (e.g. a 45 °C
  spike in a 0–8 °C fridge) no longer compresses the normal operating range to
  the bottom of the chart. The domain is now derived from the 1st–99th percentile
  of the average line; truly isolated spikes are clamped and shown as small ▲
  outlier markers with their value at the chart boundary.
- **Report charts: interim (current-month) reports no longer show future time as
  a missing-data gap.** The chart x-axis is now clipped to the report generation
  timestamp, so the right edge always ends at "now" rather than at month end.
- **Report charts: band simplification to prevent barcode effect.** Adjacent
  defrost, gap, or deviation bands that are closer together than their kind-specific
  merge threshold are combined into a single wider band. Monthly freezer charts
  with many short defrost cycles no longer render as a dense stripe pattern.
- **Report charts: restrained visual style.** The missing-data hatch is now a
  subtle warm-gray diagonal (`#c8c4a0` at 35 % opacity on a near-white base)
  rather than the bright yellow used in earlier releases. The min–max envelope
  opacity is reduced to 0.13. Gap boundary lines match the hatch colour.

## 0.4.1 — 2026-06-25

### Fixed

- **Report detail charts: equal visual weight across all unit cards.** The last
  unit card (when the unit count is odd) spans the full grid width. Its mini SVG
  was previously generated at the same intrinsic width as the narrow cards, so
  CSS `width:100%/height:auto` scaled it ~2×, making strokes appear twice as
  thick, the min–max envelope twice as wide, and the chart itself twice as tall
  as the other units. The wide-card SVG is now generated at 2× the intrinsic
  width, keeping the CSS scale factor — and therefore all visual properties —
  identical across all three cards.
- **Report y-axis domain: minimum range raised from 2 °C to 4 °C (centered).**
  Units with tight safety-limit bands (e.g. a freezer with a 3 °C window) were
  shown on a very compressed y-axis, making normal hysteresis oscillations look
  dramatic. The minimum span is now 4 °C, centered around the data midpoint.
- **ESPHome gateway (Dixell Waveshare):** reduce CPU to 80 MHz; disable WiFi
  power-save mode (sporadic disconnects); tighten setpoint number ranges to
  0.1–10 °C; trigger a heartbeat tick immediately after HA reconnect to avoid
  up to ~6 min data gaps for stable temperatures.

## 0.4.0 — Unreleased

### Added — Phase 6: report scheduling + email delivery

- **Report schedules** (monthly first): name, enabled, selected units, locale,
  timezone, detail level, recipients (To/CC/BCC), attachment formats, run day/time,
  catch-up mode, next/last run + last result. The reporting period is the **previous
  complete calendar month** computed from **timezone-aware calendar boundaries**
  (DST-correct), never by subtracting days.
- **Persistent, restart-safe scheduler**: one execution per (schedule, period)
  guaranteed by a DB unique constraint; execution lock with stale-lock recovery;
  idempotent generation reusing the immutable report artifacts; bounded catch-up of
  one missed period after downtime; visible `next_run`. Explicit run states:
  pending / generating / generated / sending / completed / partially_failed /
  failed / skipped / cancelled. Generation and delivery success are tracked
  separately — **a generated report is preserved even when delivery fails**.
- **SMTP configuration**: host, port, security mode (STARTTLS / implicit TLS /
  plain-insecure-opt-in), auth, sender/reply-to, timeout, certificate verification,
  default recipients, max attachment size, site name. The mode is never inferred
  from the port; certificate verification is on by default. **Test connection** and
  **send test email** are separate actions returning sanitized results.
- **SMTP password handling**: stored app-private in `/data`; never returned through
  the API, logged, or placed in diagnostics. A blank password on edit preserves the
  stored secret; clearing it is an explicit action.
- **Multipart email** (plain + HTML, UTF-8, localized DE/EN subject + body) with
  PDF (default) and optional CSV/JSON attachments taken from the exact finalized
  report; attachment existence + a configurable total size limit are validated
  (oversize → delivery failed with a clear reason, report kept downloadable).
- **Recipients**: syntax validation, whitespace normalization, header-injection
  prevention, de-duplication across To/CC/BCC, masked in history/diagnostics.
- **Bounded delivery retries** (immediate / +5 min / +30 min / +2 h, then failed),
  classified failures (connection / TLS / auth / recipient rejected / too large /
  temporary / permanent / attachment missing / generation / internal); permanent
  errors don't retry. **Idempotent** on a delivery key (schedule + report + period +
  recipient set + attachment set); a retry continues the same record; manual resend
  is an explicit, audited action.
- **Audit + history** for schedule/SMTP changes, runs, deliveries, tests, resend,
  cancel — never storing passwords or raw auth responses.
- **UI**: a new **Schedules & Email** page (SMTP settings with hidden-password
  behaviour + test actions, schedule list, schedule editor, execution history with
  masked recipients and per-run send/resend/cancel). Full English + German.
- Migration **0011** (`smtp_settings`, `report_schedules`, `schedule_runs`,
  `email_deliveries`). 231 backend tests (incl. a local fake SMTP server) + 52
  frontend tests.

> Real-SMTP delivery and a forced-failure run still require verification on the
> live instance — see the Phase 6 checklist in `docs/current-status.md`.

## 0.3.3 — Unreleased

### Fixed — state-change semantics (no more false gaps / dashed bridges)

- Home Assistant's Recorder is **state-change based**: a steady sensor emits no
  new row until its value changes. The app no longer treats every larger interval
  between rows as missing data. A new shared module reconstructs **state-validity
  intervals**: a valid value persists until the next state, an explicit
  `unavailable`/`unknown`, or a bounded **maximum trust interval** (2 h) — then it
  becomes a genuine gap.
- The **live temperature chart** no longer renders dashed diagonal bridges across
  steady periods. Empty aggregation buckets inside a valid interval now carry the
  last known value (continuous line); the line breaks only on genuine gaps. The
  redundant `lttb` sampling (which bridged nulls) was removed.
- **Coverage** is now the share of the period in which a valid state was known
  (duration-based), so a normal state-change sensor is no longer reported as
  mostly-missing. This also resolves units that showed **0.0 % coverage next to
  real min/avg/max** — such a unit now reports its true (small) coverage, and the
  report shows `< 0,1 %` rather than `0,0 %` when data exists but rounds below 0.1%.

### Changed — report chart visual redesign

- Missing data is now a **subtle pale-yellow diagonal hatch** with thin boundary
  markers instead of a saturated yellow fill, on a white plot background — so the
  temperature data dominates, not the shading. Measured violations (soft red) and
  defrost (soft blue) stay as restrained solids; the mean line is a touch stronger
  with a soft min–max envelope.
- Sparse reports show a concise annotation (e.g. *"Incomplete data — measurements
  available only from 23.06.2026"*) while keeping the full monthly x-axis. No data
  is drawn across gaps; envelopes stop at gaps.

### Added

- **Import progress**: the history-import row shows a live progress bar and
  `done/total` windows (e.g. `60% (3/5)`) while importing.

## 0.3.2 — Unreleased

### Fixed — resilient, resumable history import (was `ReadTimeout`)

- Home Assistant history is now fetched in **bounded date chunks** (5 days)
  instead of one large request, so a long range no longer hits a read timeout.
  Each window has a **generous timeout** and **bounded exponential-backoff
  retries**.
- **Progress is persisted after every chunk**, so a failed or interrupted import
  (including an App restart mid-import) can **resume** without restarting
  completed windows. The import is idempotent and never creates duplicate
  samples, and never overwrites newer native samples (existing timestamps of any
  source are skipped).
- Import results now distinguish **completed / partially completed / failed /
  cancelled**, and the UI shows **exactly which date range failed** (e.g.
  "01.05.–21.05. imported · 22.05.–28.05. failed · Resume") rather than a generic
  error. A running import can be **cancelled**. Migration 0010 adds per-chunk
  progress; new status `cancelled`.

### Changed — history-import placement & creation flow

- The history-import controls moved out of the unit **detail** view onto the
  **storage-units management page**, as a **compact row per unit** (never one
  ambiguous global box). Each row shows whether a temperature sensor is assigned,
  whether history is available (with earliest/latest where known), the current
  status, the already-imported period, any failed range, and buttons to
  **import / resume / retry / extend / cancel**.
- After creating a unit with a primary temperature sensor, the management page
  shows an inline prompt — *"Existing Home Assistant history is available. Import
  it now?"* — so the feature is discoverable as one continuous setup flow.
- The unit **detail** view keeps only a small **read-only** import status with a
  pointer to the management page.
- Hourly long-term statistics remain clearly labelled as hourly (no implied
  minute-level incident precision); imports still never create live incidents,
  active incidents, or alter approved defrost models.

## 0.3.1 — Unreleased

### Changed

- The defrost **state mapping** in the unit editor is now a collapsed, clearly
  **optional/advanced** disclosure. A normal `switch` (on/off — plus
  unavailable/unknown) is recognized automatically, so the field can stay empty;
  it's only needed for controllers that report other values (e.g. a Dixell output
  reporting `defrosting`/`cooling`).

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
