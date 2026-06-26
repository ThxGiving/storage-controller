# Report layout spec — measured from `report_mockup.png`

Authoritative visual target (German sample, 2 pages, A4 portrait). Values are
approximate (mockup is ~768 px/page); the goal is **structural** match.

## Global
- A4, margins ≈ 10 mm. Sans-serif, body ≈ 8 pt, section titles ≈ 8 pt bold UPPERCASE.
- Section container: white, 0.5 pt `#e5e7eb` border, radius ≈ 4 px, with a header
  strip (`#f3f4f6` bg, bold uppercase title, ~5 pt vertical padding).
- Palette: petrol `#0f766e` (brand), series blue `#2563eb`, green `#16a34a`,
  cyan `#0891b2`, purple `#7c3aed`; limits: upper red `#dc2626` dashed, lower blue
  `#2563eb` dashed; warn orange `#ea580c`; ok green `#16a34a`.
- Band fills: deviation red `#fecaca`, data gap amber `#fde68a`, defrost blue `#dbeafe`.

## Page 1
1. **Header** (3 cols, rule under): left logo ≈ 18 %; middle org name (bold ~10 pt)
   + address (gray ~7.5 pt) ≈ 30 %; right ≈ 52 %: `HACCP-TEMPERATURBERICHT`
   (bold ~16 pt, right) + month (~11 pt) + 3 right-aligned gray lines
   (Berichtszeitraum / Erstellt am / Berichts-ID).
2. **GESAMTÜBERSICHT** container: 5 cells — 4 metric tiles (colored line icon,
   big number ~16 pt, gray label) [monitored / coverage % / confirmed deviations /
   open incidents] + a **BEWERTUNG GESAMT** verdict cell (label + icon + text).
3. **ZUSAMMENFASSUNG ALLER KÜHLBEREICHE** container: dense table — Kühlbereich
   (bold name + gray type subtitle) | Sollbereich | Min. | ø | Max. | Außerhalb
   des Bereichs (orange if >0, else green "0 min") | Daten­abdeckung | Vorfälle |
   Status (check + Geprüft/OK).
4. **TEMPERATURVERLAUF – MONATSÜBERSICHT** container: two **short** charts
   (positive group, then TK group), each: `°C` axis label, colored multi-series,
   red/blue dashed limit lines, shaded deviation/gap/defrost bands, per-chart
   legend row (series + Oberer/Unterer Grenzwert). Shared band legend strip below.
5. **Footer**: left `Refrigeration Logbook v…`, right `Seite 1 von 2`, top rule.

## Page 2
1. **DETAILS JE KÜHLBEREICH** title.
2. **2 × 2 card grid** (always fill 4 cells for ≤4 units). Card: colored header
   `Name – Typ` (blue=attention / green=ok) + status pill (Geprüft/OK) right;
   colored accent line; row `Sollbereich: a – b °C` | `Datenabdeckung: z %`;
   metric row Min. | ø | Max. | Außerhalb | Vorfälle (values, Außerhalb colored);
   compact mini-chart (°C, colored series, limits, bands).
3. **VORFÄLLE (ZUSAMMENFASSUNG)** container: table Nr | Kühlbereich | Beginn |
   Dauer | Extremwert | Ursache | Maßnahme | Status (user text, not translated).
4. Two panels side by side: **DATENQUALITÄT** (icon + availability text) |
   **FREIGABE** (Geprüft durch / Datum / Unterschrift / Bemerkung underlines).
5. **Footer**: disclaimer (left, small gray), `Seite 2 von 2` (right).

## Deviation checklist (current 0.2.0 → target)
- [ ] P1 header: no logo/org/address block → add 3-col branded header.
- [ ] P1: no 4-metric + verdict GESAMTÜBERSICHT → add 5-cell summary with icons.
- [ ] P1 table: missing "Außerhalb" + "Status" columns + type subtitle → add.
- [ ] P1 charts: grayscale, oversized, no legend/bands → colored, shorter, legend
      below, deviation/gap/defrost shaded bands, °C label.
- [ ] P1: no shared band legend; footer lacks version/page rule.
- [ ] P2: 4 oversized cards stacked → **2×2** grid, compact.
- [ ] P2 cards: no colored header/accent line/status pill/Sollbereich row/metric row.
- [ ] P2: missing VORFÄLLE incident table.
- [ ] P2: missing DATENQUALITÄT + FREIGABE panels.
- [ ] P2 footer: disclaimer + page number layout.
- [ ] Whole: large empty areas → denser, balanced page usage.

## Status derivation (per unit) — v2

Priority order (first match wins):

1. **open** — an incident is still open (`pending_violation` / `active_violation`
   / `recovering`). Badge: red "Open incident". A reviewed/closed incident does
   **not** make a unit OK.
2. **incomplete** — data is incomplete (`coverage < 90 %`) or the sensor is
   missing. Badge: gray "Incomplete". No conformity statement is implied.
3. **reviewed** — closed incident(s) exist with the period's data complete.
   Badge: blue "Reviewed".
4. **ok** — no incidents and complete data. Badge: green "OK".

Overall verdict mirrors this: `incomplete` → `open` → `documented` → `ok`.
The unit *identity colour* (accent line, title, table dot, chart series) is a
stable palette colour (blue / cyan / green / violet …) and is **never** derived
from status.

## Chart interval semantics (red vs. yellow vs. blue)

- **Red (deviation)** — only intervals where **measured valid** samples exceeded
  a configured safety limit. Derived from raw samples; never extended across a
  gap or to the period end, so an open incident or a sensor dropout is never
  painted red into the unknown future.
- **Yellow (no data)** — buckets with no valid data (missing *or* unavailable /
  invalid). Aligned to where the rendered line breaks, so merely coarse-but-
  present sampling is **not** painted yellow; only genuine gaps are. The line is
  never connected across a gap.
- **Blue (defrost)** — configured defrost intervals (cycle start→end), drawn at
  absolute timestamps so they stay aligned after aggregation.
- No shading for normal valid in-range data.

## Adaptive chart aggregation

Deterministic, time-range dependent bucket aggregation (monthly reports →
**hourly** buckets; bucket width grows if it would exceed `max_points = 800`,
keeping PDF generation bounded). Each bucket carries avg, min, max, valid count.
The chart renders one **calm average line** plus a subtle **min–max envelope**
(so short excursions an average would hide stay visible) over the safety-limit
lines and the interval shading above.

Report **metrics and incidents always use raw samples / validated values** — a
bucket whose average is in range but whose min/max crossed a limit still counts
toward the metrics and still shows the excursion. Aggregation never changes
incident counts, durations, extrema or report metrics (proven in
`tests/test_report_charts.py`). The same aggregation semantics are used for the
overview charts and the detail-card mini-charts.
