# Refrigeration Logbook — Real Home Assistant OS installation & verification

This guide covers installing and verifying the current **Phase 1 + 2** build on
a real Home Assistant OS (or Supervised) instance. It does **not** enable sample
collection — that is Phase 3.

> Production starts with **zero storage units**. Demo data loads only when
> explicitly requested (see §9). Do **not** enable demo seeding on production.

---

## 0. Requirements

| Item            | Value                                                                 |
| --------------- | --------------------------------------------------------------------- |
| App slug        | `storage_controller`                                                  |
| Version         | `0.1.0`                                                                |
| Architectures   | `amd64`, `aarch64` (64-bit only — **not** armv7/armhf/i386)           |
| HA flavor       | Home Assistant **OS** or **Supervised** (Supervisor + Add-on store)   |
| Permissions     | `homeassistant_api: true` only (no host network / privileged / hassio)|
| Ingress         | enabled, internal port `8099`, entry `/`                              |
| AppArmor        | `false` for this build (custom profile shipped but not yet validated) |

The App builds **on the HA host** from source using `build.yaml`
(`ghcr.io/home-assistant/{arch}-base-python:3.12-alpine3.20`). The host needs
outbound access to `ghcr.io` and to PyPI/npm during the first build.

---

## 1. Add the App to Home Assistant

You have two options. **Local add-on** is simplest for testing.

### Option A — Local add-on (recommended for testing)

1. Install the **Samba share** or **Advanced SSH & Web Terminal** add-on.
2. Copy the **`storage-controller/`** folder (the one containing `config.yaml`,
   `Dockerfile`, `build.yaml`, `backend/`, `frontend/`, `migrations/`) into the
   Home Assistant **`/addons/`** share, so it lands at:

   ```
   /addons/storage-controller/
   ```

   (Do **not** copy `repository.yaml` for the local method — that file is only
   for the custom-repository method.)
3. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ (top right) →
   Check for updates**.
4. **Refrigeration Logbook** now appears under **Local add-ons**.

### Option B — Custom repository (Git)

1. Push the **whole repository** (with `repository.yaml` at the root and the
   `storage-controller/` folder) to a Git host. Set the real URL in
   `repository.yaml` and `config.yaml` (`url:`).
2. **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → paste the repo URL
   → **Add**.
3. **Refrigeration Logbook** appears under your repository’s section in the store.

---

## 2. Install and start

1. Open **Refrigeration Logbook** in the Add-on Store and click **Install**.
   First install triggers an on-device container build (a few minutes; longer on
   aarch64). Watch the build progress in the add-on’s **Log** tab.
2. After install, confirm settings on the add-on’s **Info/Configuration** tab:
   - **Start on boot**: on (`boot: auto`)
   - **Watchdog**: on (restarts on `/health` failure)
   - **Show in sidebar**: on (Ingress)
3. Click **Start**.
4. After ~5–15 s, a **Refrigeration Logbook** entry (snowflake-thermometer icon)
   appears in the HA sidebar. Click it to open the UI through Ingress.

There is **no separate login** — Ingress provides authentication.

---

## 3. Real-instance verification checklist

- [ ] Add-on **Install** completes without build errors.
- [ ] Add-on **Start** succeeds; state shows **Started**.
- [ ] Sidebar shows **Refrigeration Logbook**; clicking it opens the UI (no white
      page, no redirect to `/login`).
- [ ] **Overview** shows Home Assistant **Connected** (green pill) within ~15 s.
- [ ] Overview shows a non-zero **Entities** count and a recent **Last event**.
- [ ] **Entities** tab lists your real HA entities; search by ID and by friendly
      name both work; state, unit, domain, device and “last changed” are shown.
- [ ] **Storage units** tab shows **no units** (empty state) — confirms no demo
      data on production.
- [ ] **Settings** tab: switching **Language** (English/Deutsch) updates the UI
      immediately; numbers/dates re-format (e.g. `6,1 °C` in German).
- [ ] Create a test unit (assign one real temperature sensor as room
      temperature) → it saves and shows the live current value. (You may delete
      it again; this does not start collection.)
- [ ] Restart the add-on → the test unit (if kept) and settings **persist**.
- [ ] Add-on **Log** contains **no** `SUPERVISOR_TOKEN` value and no `Bearer …`
      token (only `***REDACTED***` if a token ever appears).

---

## 4. Expected successful startup log sequence

(Add-on **Log** tab. s6 banner lines first, then:)

```
s6-rc: info: service legacy-services successfully started
[run.sh] Applying database migrations...
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial, initial schema (Phase 1 + 2)
[run.sh] Starting Refrigeration Logbook web server on 0.0.0.0:8099
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
2026-..  INFO    [api] Refrigeration Logbook 0.1.0 starting
2026-..  INFO    [database] database: seeded 4 built-in monitoring profiles   ← first boot only
2026-..  INFO    [ha_client] ha_client: connecting to Home Assistant WebSocket
2026-..  INFO    [ha_client] ha_client: authenticated
2026-..  INFO    [ha_client] ha_client: subscribed to state_changed (N entities)
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8099 (Press CTRL+C to quit)
```

Notes:
- The `seeded 4 built-in monitoring profiles` line appears only on the **first**
  boot (profiles are idempotent; later boots log nothing for seeding).
- On production you must **not** see `database: demo data requested ...`.
- The `ha_client` lines are asynchronous and may appear just after
  `Application startup complete`.

---

## 5. Failure signatures (logs + UI)

### Missing Supervisor token

- **Log:** `WARNING [ha_client] ha_client: no token configured, staying disconnected`
- **UI:** Overview → Home Assistant pill **Disconnected** (gray); detail
  “No Home Assistant token available”. `/api/status` →
  `home_assistant.status = "disconnected"`.
- **Meaning:** with `homeassistant_api: true` the token is normally always
  present. Seeing this on real HA points to a Supervisor/platform issue, not a
  user mistake. Health stays **200** (DB ok) — the container is healthy; only HA
  data is unavailable.

### Failed WebSocket authentication (invalid/expired token)

- **Log:** `ERROR [ha_client] ha_client: authentication error: ...`
- **UI:** red **Authentication** pill; detail “Authentication rejected by Home
  Assistant”. `/api/status` → `status = "authentication_error"`.
- Health stays **200**; the App keeps retrying.

### Failed Home Assistant REST authentication

- **Phase 1 + 2 note:** entity states are retrieved over the **WebSocket**
  (`get_states`), so the REST client is **not exercised yet**. A REST 401 will
  not appear in this build. When REST/history is used in **Phase 3+**, a REST
  auth failure will surface as an `httpx`/`ha_client` HTTP 401 error in the log.
  (Flagged here for completeness.)

### Home Assistant unreachable / connection error (not an auth problem)

- **Log:** `WARNING [ha_client] ha_client: connection error: <ExceptionType>`
  (e.g. `ConnectionClosed`, `gaierror`).
- **UI:** yellow **Reconnecting…** pill; `/api/status` → `status = "reconnecting"`,
  with exponential backoff. Health stays **200**.

### Ingress path problems

- **Symptoms:** the add-on **Log** is clean and `/health` (watchdog) is green,
  **but** the sidebar page is blank/white, or the browser console shows **404**
  on `/assets/index-*.js` / `index-*.css`, or API calls 404.
- **Expected:** assets are loaded with **relative** paths and the backend honors
  `X-Ingress-Path`, so this should work. If it does not, capture the browser
  console/network tab — it indicates an asset-base or forwarded-header issue.
- The App must **never** redirect you to `/login` or to `/`.

### Database migration failure

- **Log:** an Alembic traceback right after `[run.sh] Applying database
  migrations...`; the script exits (`set -e`) **before** uvicorn starts, so you
  never see `Uvicorn running`.
- **UI:** the sidebar page fails to load (Ingress 502); the watchdog marks the
  add-on unhealthy and restarts it (possible restart loop).
- **Action:** read the Alembic error; the most common causes are a corrupted
  `/data/storage-controller.db` or a downgrade mismatch after a rollback (see §8).

### AppArmor denial (only if AppArmor is later enabled)

- This build ships `apparmor: false`, so denials should not occur. If you set
  `apparmor: true`:
- **Log (Supervisor / host `dmesg`):**
  `audit: ... apparmor="DENIED" operation="..." profile="storage_controller" ...`
- **Symptoms:** s6 services fail to start; the container restart-loops; `/health`
  never becomes reachable.
- **Action:** set `apparmor: false` again to confirm the denial was the cause,
  then refine `apparmor.txt` (Phase 7 hardening).

---

## 6. Health endpoint reference

- `GET /health` returns **200** only when the web server is up, the database is
  reachable, and migrations are applied (the `storage_units` table is queryable).
  Otherwise **503**.
- **Home Assistant disconnection does NOT make the container unhealthy** — HA
  state is reported separately via `/api/status` (`connected` / `reconnecting` /
  `disconnected` / `authentication_error`). The watchdog targets `/health`.

---

## 7. Safe update workflow (revised build)

`/data` (database, settings, future reports) **persists** across updates,
rebuilds and restarts. It is removed only on **uninstall**.

1. **Take an HA backup first** (Settings → System → Backups → Create backup;
   include the Refrigeration Logbook add-on). The add-on uses **cold** backup, so
   `/data` is captured consistently.
2. **Bump the version** in `config.yaml` (e.g. `0.1.0 → 0.1.1`). HA only offers
   an update when the version changes.
3. Deliver the new files:
   - **Local add-on:** overwrite `/addons/storage-controller/` with the new
     files → **Settings → Add-ons → ⋮ → Check for updates** → open the add-on →
     **Rebuild** (local add-ons build on-device). If the version changed, an
     **Update** button appears; either Rebuild or Update works.
   - **Custom repo:** push the new commit/tag → **⋮ → Check for updates** → the
     add-on shows **Update** → click **Update**.
4. After it restarts, re-run the **§3 checklist** and confirm the new version in
   **Settings → About** / `/api/status` (`version`).

Migrations run automatically on start (`alembic upgrade head`) and only move
**forward**. Always update to an equal-or-newer schema version.

---

## 8. Rollback procedure (preserves `/data`)

Do **not uninstall** — uninstall deletes `/data`. Instead roll the code back:

1. **Stop** the add-on.
2. Restore the previous build:
   - **Local add-on:** put the previous version’s files back into
     `/addons/storage-controller/` (and set `version:` back) → **Rebuild**.
   - **Custom repo:** check out the previous tag/commit and push, or restore the
     add-on from the **HA backup** taken in §7.
3. **Start** the add-on and re-run the §3 checklist.

`/data` is untouched by stop/rebuild/restart, so your database and settings
survive the rollback.

**Schema caution:** if the newer build added a migration and wrote data with the
new schema, rolling the *code* back to a version that predates that migration can
leave the DB schema **ahead** of the code. For Phase 1 + 2 there is only one
migration (`0001_initial`), so this is not yet a concern; from Phase 3 onward,
prefer restoring `/data` from the pre-update backup when rolling back across a
migration boundary.

---

## 9. Demo data (must stay OFF on production)

- Production **starts empty** — no storage units are created automatically.
  Built-in monitoring profiles are seeded (read-only templates), but **no units**.
- Demo units load **only** when explicitly requested, via either:
  - the environment flag `STORAGE_CONTROLLER_LOAD_DEMO_DATA=true`, or
  - the command `storage-controller seed-demo` (run inside the container).
- This build sets **neither**, so production stays clean. **Do not** set the flag
  on your production instance. (The seed is idempotent in any case — running it
  twice creates no duplicates — but keep it off in production.)

---

## 10. After verification → Phase 3

Once the above is confirmed on the real instance, Phase 3 will implement
independent sample collection (persisting `state_changed` events for assigned
entities, normalization, availability handling, heartbeat samples and the
time-series chart with visible gaps), using the actual entities and events
observed on your instance.
```
