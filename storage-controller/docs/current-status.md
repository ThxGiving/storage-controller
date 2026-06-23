# Current status

_Last updated: 2026-06-23 (release 0.1.12, Phase 4.7)._

## Phases

| Phase | Scope | Status |
|------|-------|--------|
| 1 + 2 | App structure, Ingress, storage-unit CRUD, role assignment | shipped, verified on real HA |
| 3 | Independent sample collector + operational dashboard | shipped, verified |
| 4 | Incident engine + defrost-aware evaluation | shipped, verified |
| 4.5 | Bounded retention, aggregation, storage monitoring, IANA timezone (0.1.9) | shipped, verified |
| 4.6 | Defrost **learning** + single-toggle UX (0.1.10) | shipped |
| 4.6.1 | Configurable defrost value mappings + first diagnostics cut (0.1.11) | shipped |
| **4.7** | **Defrost diagnostics & stabilization (0.1.12)** | **this release** |
| 5 | Compact 2-page monthly PDF report (`report_mockup.png`) | not started |

Out of scope until later: aggregation changes, retention changes, PDF reporting,
email, scheduling.

## Phase 4.6 safety rules (still enforced)

- No learned HACCP/legal limits; learned values are operational only.
- `defrost = on` is never a blanket exemption.
- No automatic model approval; suppression requires an **approved** learned model.
- No suppression of excursions before explicit approval.

## Defrost processing path (event → cycle)

1. HA `state_changed` event received (`manager._handle_event`, sets `last_event_at`).
2. Entity mapping lookup (collector index) — else not recorded.
3. Storage-unit lookup (assignment → unit).
4. Raw state extraction (`new_state.state`, `old_state.state`).
5. Normalization (`normalize_bool` with optional per-entity value mapping; precise
   `reason` on failure — never guessed).
6. Duplicate / out-of-order detection (high-water mark per assignment).
7. Persistence (`sensor_samples` / `state_samples`, `UNIQUE(assignment, ts)`).
8. Defrost engine invocation (periodic poll every 30 s over the live cache).
9. Cycle start / end (rising/falling edge); reconstructed start on restart.
10. Recovery evaluation (completes at upper limit, or pre-defrost baseline if none).
11. Incident evaluation.
12. Final result code (see below).

### Result codes
`stored`, `reconciled_on_reconnect`, `duplicate_ignored`, `out_of_order_event`,
`ignored_unchanged`, `normalization_failed`, `unavailable`, `mapping_missing`,
`storage_unit_missing`, `cycle_started`, `cycle_ended`, `engine_not_invoked`,
`persist_failed`.

## Targeted diagnostics (admin, read-only)

- `GET /api/diagnostics/defrost` — per defrost mapping, full chain + a
  human-actionable `problem`.
- `GET /api/diagnostics/entities/{entity_id}`, `GET /api/diagnostics/events/recent`.
- `POST /api/diagnostics/logging/enable|disable`, `GET /api/diagnostics/logging/status`,
  `GET /api/diagnostics/logs` — 30-minute auto-expiring structured logging mode,
  bounded ring buffer (≤1000 buffered, ≤200 returned), filters
  (component / storage_unit_id / entity_id / severity / since). All messages and
  fields are redacted (token / Authorization / cookie / session / passwords /
  API keys / private keys / env values). No raw SQL, no filesystem access.

## Real-instance defrost verification checklist

When a defrost goes **inactive → active → inactive**, capture from
Settings → _Defrost diagnostics_ (or `GET /api/diagnostics/defrost`):

1. `raw_state` and `normalized_bool` + `normalization_reason` (expect a clean
   `true`/`false`, reason `ok`; if `unrecognized_state`, set a value mapping).
2. `last_state_change` advances when HA toggles the switch.
3. `last_event_received` / `last_event_persisted` advance shortly after.
4. `last_engine_evaluation` is recent (engine alive).
5. On **active**: `engine_state` → `active`, `active_cycle_id` set, `problem` null.
6. On **inactive**: cycle moves to recovering then completes;
   `last_completed_cycle_id` set; in the unit's _Defrost learning_ panel the cycle
   shows **completed / counts**.
7. If a cycle is `reconstructed` (restart mid-defrost), `last_cycle_reconstructed`
   is true and timestamps are approximate (by design).

If detection fails, the failing step is identified by the `problem` field and the
`result` of recent events.
