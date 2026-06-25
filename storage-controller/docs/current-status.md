# Current status

_Last updated: 2026-06-25 (release 0.4.0, Phase 6)._

## Phases

| Phase | Scope | Status |
|------|-------|--------|
| 1 + 2 | App structure, Ingress, storage-unit CRUD, role assignment | shipped, verified on real HA |
| 3 | Independent sample collector + operational dashboard | shipped, verified |
| 4 | Incident engine + defrost-aware evaluation | shipped, verified |
| 4.5–4.7 | Retention/aggregation/storage, defrost learning + diagnostics (0.1.9–0.1.12) | shipped |
| 5 | Compact 2-page monthly PDF report (`report_mockup.png`) (0.2.x) | shipped, verified |
| 5.1 | HA history import (embedded, resumable, chunked) (0.3.0–0.3.2) | shipped |
| 5.2 | State-change state semantics + report chart redesign (0.3.3) | shipped |
| **6** | **Report scheduling + SMTP email delivery (0.4.0)** | **this release (real-SMTP verify pending)** |

## Phase 6 — scheduling & email (0.4.0)

Generates existing report types automatically and delivers them by email. No
redesign of the PDF, charts, history import, incidents, or defrost learning.

- **Tables (migration 0011):** `smtp_settings` (single row), `report_schedules`,
  `schedule_runs` (states + `UNIQUE(schedule, period)` for no-duplicate-runs + lock
  columns), `email_deliveries` (`UNIQUE(delivery_key)` + bounded retries +
  per-recipient outcome).
- **Scheduler** (`scheduler.py`, ticks every 60 s + startup catch-up): one due run
  per (schedule, period); execution lock with stale-lock recovery; restart-safe and
  idempotent (reuses immutable report artifacts via `reporting.service.generate`);
  catch-up of one missed period; `next_run_utc` kept current.
- **Period math** (`scheduling.py`): previous complete calendar month in the
  schedule's IANA timezone (DST-correct, never day subtraction).
- **SMTP** (`mailer.py`, stdlib `smtplib` in a thread): STARTTLS / implicit TLS /
  plain (opt-in insecure); cert verification on by default; mode never inferred
  from the port. Password is app-private — never returned/logged/in diagnostics;
  blank on edit preserves it, explicit clear removes it.
- **Delivery** (`delivery.py`): idempotent on `delivery_key`; retries immediate /
  +5 m / +30 m / +2 h then failed; permanent errors don't retry; per-recipient
  accepted/rejected; **a generated report is preserved even if delivery fails**.
- **States:** pending · generating · generated · sending · completed ·
  partially_failed · failed · skipped · cancelled. Generation and delivery success
  are tracked separately.
- **UI:** "Schedules & Email" page — SMTP settings (+ test connection / test email),
  schedule list, schedule editor, execution history with masked recipients and
  per-run resend/send/cancel. Full EN/DE.
- **Tests:** 231 backend (incl. `test_scheduling_math`, `test_email_transport` with a
  local fake SMTP server, `test_phase6_integration`, `test_phase6_api`), 52 frontend.

**Not yet verified on a real instance:** real SMTP delivery + a forced delivery
failure. See the Phase 6 real-instance checklist below.

## Phase 6 real-instance verification checklist

1. Enter SMTP settings (host, port, security mode, sender, credentials).
2. **Test connection** → expect success (no message sent).
3. **Send test email** to yourself → arrives, clearly labelled.
4. Create a **disabled** test schedule for one unit, recipient = yourself.
5. **Run now** → confirm it states the previous complete month, generates, and sends.
6. Verify the **PDF attachment** opens and matches the report.
7. Verify the **German subject/body** (`HACCP-Temperaturbericht – … – <Monat Jahr>`).
8. Force a delivery failure (wrong port/host) and **Run now (send)** → status shows
   `generated, delivery failed`; the report stays **downloadable**.
9. Fix SMTP and **Resend** → delivery completes; no duplicate logical delivery.
10. Confirm retry timing in execution history after a transient failure.
11. Enable the real monthly schedule.

## Earlier-phase notes

State-change semantics, defrost processing, and diagnostics are unchanged from
0.3.3; see CHANGELOG.md for the full history.
