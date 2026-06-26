# Backup & Restore

This document covers the two available backup mechanisms for the Refrigeration Logbook add-on,
recovery procedures for different failure scenarios, and known limitations.

---

## Home Assistant Backup vs Application Backup

| Data | HA Backup | App Backup | Notes |
|------|-----------|------------|-------|
| Database | Yes (unverified — see below) | Yes | |
| Generated reports | Yes (unverified) | Yes | |
| Branding assets | Yes (unverified) | Yes | |
| Schedules | Yes (unverified) | Yes | |
| SMTP password | Yes (unverified) | Yes (in DB) | Password is stored encrypted in DB; verify after restore |
| App backup archives | Yes (unverified) | N/A | |
| Temporary files | No | No | |

---

## What "unverified" means

Home Assistant add-on backups typically include the add-on's `/data` directory, which is where
this application stores its database, generated reports, branding files, and backup archives.
The entries above are marked **unverified** until a real HA backup archive has been inspected to
confirm exact coverage.

To verify: take an HA backup, download the `.tar` file, and inspect the inner tar for
`data/storage_controller.db`, `data/reports/`, `data/branding/`, and `data/backups/`. Once
confirmed, update this table accordingly.

---

## Recovery procedures

### Case A — HA backup available

1. In Home Assistant, navigate to **Settings → System → Backups**.
2. Select the relevant backup and restore the Refrigeration Logbook add-on.
3. Restart the add-on after the restore completes.
4. Open the add-on UI and navigate to **Settings → Backup & Restore**.
5. If a yellow SMTP warning banner appears, go to **Settings → Email** and send a test email
   to confirm the SMTP password survived the restore.

### Case B — Only app backup available (no HA backup)

1. Install a fresh instance of the Refrigeration Logbook add-on.
2. Wait for the add-on to start and open the UI.
3. Navigate to **Settings → Backup & Restore**.
4. Click **Choose backup file** and select the `.zip` archive.
5. Once validation passes, click **Confirm Restore**. A safety backup of the current (empty)
   state is created automatically before restoring.
6. The add-on restarts automatically. After it comes back up, verify the data.
7. Check the SMTP warning banner and confirm email settings.

---

## SMTP re-entry note

After **any** restore, verify SMTP settings by navigating to **Settings → Email** and sending
a test email. The SMTP password is stored inside the database and should survive a restore that
includes the database file. However, it is good practice to confirm this explicitly — especially
after a full add-on reinstall — because some deployment scenarios may not preserve `/data`.

If the password is missing (the UI will show a yellow warning banner on the Backup & Restore
page), re-enter it in the Email settings and send a test email before the next scheduled report.

---

## Known limitations

- **WAL files in-flight during HA snapshot**: If a Home Assistant snapshot is taken while the
  application is running, the SQLite WAL (Write-Ahead Log) file may contain in-flight
  transactions. On the next startup after a restore, the application runs
  `PRAGMA wal_checkpoint(TRUNCATE)` automatically to bring the database to a consistent state.

- **SMTP password after restore**: The SMTP password is stored in the database and should
  survive a database restore. Verify by sending a test email after any restore operation.
  The Backup & Restore page will display a warning banner if the password appears to be absent.

- **Scheduler jobs interrupted mid-run**: If the add-on process is killed while a scheduled
  report is generating or being sent, the job record is left in an intermediate state. On the
  next startup, the application detects these stale records and marks them as failed so the
  scheduler can retry them on the next scheduled run.
