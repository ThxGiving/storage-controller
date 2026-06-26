"""Application-level backup and restore for Refrigeration Logbook.

Backup produces a single ZIP archive:

  manifest.json           — format metadata, version, schema revision, checksums
  db/database.sqlite      — consistent DB snapshot via the SQLite backup API
  reports/<uuid>/<file>   — finalized report artifacts (PDF / CSV / JSON)
  uploads/<filename>      — branding assets (logo files)

Restore is a two-step workflow:
  1. validate(archive_bytes) → ValidationResult — non-destructive; checks
     checksums, DB integrity, and schema compatibility.
  2. execute_restore(archive_bytes) → writes a safety backup, extracts
     the archive to a staging directory, drops a .restore_pending marker,
     and sends SIGTERM so the HA supervisor restarts the add-on.

On the next startup, _complete_pending_restore() is called first in the
lifespan hook.  It replaces the live data with the staged data, deletes
the staging directory and the marker, then returns so normal startup
continues.  If the completion itself fails, the marker is left in place
for administrator investigation and the app starts against its current
(pre-restore) data.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import signal
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("backup")

# ── Constants ──────────────────────────────────────────────────────────────────

BACKUP_FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS: frozenset[int] = frozenset({1})

# A restore that would downgrade the schema is rejected outright; a restore
# from an older schema revision into a newer app is allowed — migrations run on
# next startup automatically.
_MAX_BACKUP_SIZE_BYTES = 512 * 1024 * 1024  # 512 MB hard ceiling on upload

# ── Helpers ────────────────────────────────────────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_schema_revision(db_path: Path) -> str:
    """Read the Alembic head revision string from the live database."""
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            return row[0] if row else "0000"
        finally:
            conn.close()
    except Exception:
        return "0000"


def _revision_ordinal(revision: str) -> int:
    """Extract the leading integer from an Alembic revision string."""
    try:
        return int(revision.split("_")[0])
    except (ValueError, IndexError):
        return 0


# ── Backup creation ────────────────────────────────────────────────────────────


@dataclass
class BackupResult:
    archive_path: Path
    manifest: dict[str, Any]
    size_bytes: int


def _build_archive_sync(
    db_path: Path,
    data_dir: Path,
    schema_revision: str,
    app_version: str,
    note: str | None,
) -> tuple[bytes, dict[str, Any]]:
    """Build the ZIP archive in a temporary buffer (synchronous; runs in a thread)."""
    buf = io.BytesIO()
    file_entries: list[dict[str, Any]] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # ── 1. Database snapshot ──────────────────────────────────────────────
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            source = sqlite3.connect(str(db_path))
            dest = sqlite3.connect(str(tmp_path))
            try:
                source.backup(dest)
            finally:
                source.close()
                dest.close()
            db_bytes = tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)

        db_entry = "db/database.sqlite"
        zf.writestr(db_entry, db_bytes)
        file_entries.append(
            {"path": db_entry, "size": len(db_bytes), "sha256": _sha256_bytes(db_bytes)}
        )

        # ── 2. Finalized reports ──────────────────────────────────────────────
        reports_dir = data_dir / "reports"
        if reports_dir.is_dir():
            for uuid_dir in sorted(reports_dir.iterdir()):
                if not uuid_dir.is_dir():
                    continue
                for f in sorted(uuid_dir.iterdir()):
                    if not f.is_file():
                        continue
                    data = f.read_bytes()
                    arc = f"reports/{uuid_dir.name}/{f.name}"
                    zf.writestr(arc, data)
                    file_entries.append(
                        {"path": arc, "size": len(data), "sha256": _sha256_bytes(data)}
                    )

        # ── 3. Branding uploads ───────────────────────────────────────────────
        uploads_dir = data_dir / "uploads"
        if uploads_dir.is_dir():
            for f in sorted(uploads_dir.iterdir()):
                if not f.is_file():
                    continue
                data = f.read_bytes()
                arc = f"uploads/{f.name}"
                zf.writestr(arc, data)
                file_entries.append(
                    {"path": arc, "size": len(data), "sha256": _sha256_bytes(data)}
                )

        # ── 4. Manifest (written last so file_entries is complete) ────────────
        manifest: dict[str, Any] = {
            "format_version": BACKUP_FORMAT_VERSION,
            "app_version": app_version,
            "schema_revision": schema_revision,
            "created_at": datetime.now(UTC).isoformat(),
            "timezone": "UTC",
            "note": note,
            "files": file_entries,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2).encode())

    return buf.getvalue(), manifest


async def create_backup(note: str | None = None) -> BackupResult:
    """Create a ZIP backup and write it under ``/data/backups/``.

    Runs the blocking DB snapshot and archive assembly in a thread pool so the
    event loop stays responsive.
    """
    from . import __version__
    from .config import get_settings

    settings = get_settings()
    db_path = settings.database_path
    backups_dir = settings.data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    schema_rev = await asyncio.to_thread(_current_schema_revision, db_path)
    archive_bytes, manifest = await asyncio.to_thread(
        _build_archive_sync,
        db_path,
        settings.data_dir,
        schema_rev,
        __version__,
        note,
    )

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    archive_path = backups_dir / f"backup_{ts}.zip"
    archive_path.write_bytes(archive_bytes)

    log.info(
        "backup: created %s (%d bytes, schema %s)",
        archive_path.name,
        len(archive_bytes),
        schema_rev,
    )
    return BackupResult(
        archive_path=archive_path,
        manifest=manifest,
        size_bytes=len(archive_bytes),
    )


# ── Validation ─────────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest_summary: dict[str, Any] | None = None


def _validate_archive_sync(archive_bytes: bytes, live_db_path: Path) -> ValidationResult:
    """Full archive validation (synchronous; runs in a thread)."""
    issues: list[str] = []
    warnings: list[str] = []

    # ── Basic ZIP check ───────────────────────────────────────────────────────
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes), "r")
    except zipfile.BadZipFile:
        return ValidationResult(valid=False, issues=["Not a valid ZIP archive."])
    except Exception as exc:
        return ValidationResult(valid=False, issues=[f"Cannot open archive: {exc}"])

    with zf:
        names = set(zf.namelist())

        # ── Manifest ──────────────────────────────────────────────────────────
        if "manifest.json" not in names:
            return ValidationResult(valid=False, issues=["Archive is missing manifest.json."])

        try:
            manifest: dict[str, Any] = json.loads(zf.read("manifest.json"))
        except Exception:
            return ValidationResult(valid=False, issues=["manifest.json is not valid JSON."])

        fv = manifest.get("format_version")
        if fv not in SUPPORTED_FORMAT_VERSIONS:
            return ValidationResult(
                valid=False,
                issues=[
                    f"Unsupported backup format version {fv!r}. "
                    f"Supported: {sorted(SUPPORTED_FORMAT_VERSIONS)}."
                ],
            )

        # ── Schema compatibility ───────────────────────────────────────────────
        backup_rev = manifest.get("schema_revision", "0000")
        live_rev = _current_schema_revision(live_db_path)
        if _revision_ordinal(backup_rev) > _revision_ordinal(live_rev):
            issues.append(
                f"Backup schema revision {backup_rev!r} is newer than the installed "
                f"application schema revision {live_rev!r}. "
                "Upgrade the application to a version that supports this backup before restoring."
            )

        # ── Path traversal guard ──────────────────────────────────────────────
        for name in names:
            if name.startswith("/") or ".." in name.split("/"):
                issues.append(f"Unsafe path in archive: {name!r}.")

        # ── File checksums ────────────────────────────────────────────────────
        for entry in manifest.get("files", []):
            arc_path: str = entry.get("path", "")
            expected_sha: str = entry.get("sha256", "")
            if arc_path not in names:
                issues.append(f"Manifest entry missing from archive: {arc_path!r}.")
                continue
            actual_sha = _sha256_bytes(zf.read(arc_path))
            if actual_sha != expected_sha:
                issues.append(f"Checksum mismatch for {arc_path!r}.")

        # ── Database integrity ────────────────────────────────────────────────
        if "db/database.sqlite" not in names:
            issues.append("Archive does not contain db/database.sqlite.")
        else:
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                tmp_path.write_bytes(zf.read("db/database.sqlite"))
                conn = sqlite3.connect(str(tmp_path))
                try:
                    ic_rows = conn.execute("PRAGMA integrity_check").fetchall()
                    if ic_rows != [("ok",)]:
                        issues.append(
                            f"Database integrity check failed: "
                            f"{', '.join(r[0] for r in ic_rows[:5])}"
                        )
                    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
                    if fk_rows:
                        warnings.append(
                            f"Database has {len(fk_rows)} foreign-key violation(s)."
                        )
                finally:
                    conn.close()
            finally:
                tmp_path.unlink(missing_ok=True)

    manifest_summary = {
        "format_version": manifest.get("format_version"),
        "app_version": manifest.get("app_version"),
        "schema_revision": manifest.get("schema_revision"),
        "created_at": manifest.get("created_at"),
        "note": manifest.get("note"),
        "file_count": len(manifest.get("files", [])),
        "db_size": next(
            (e["size"] for e in manifest.get("files", []) if e["path"] == "db/database.sqlite"),
            None,
        ),
    }

    return ValidationResult(
        valid=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        manifest_summary=manifest_summary,
    )


async def validate_archive(archive_bytes: bytes) -> ValidationResult:
    from .config import get_settings

    if len(archive_bytes) > _MAX_BACKUP_SIZE_BYTES:
        return ValidationResult(
            valid=False,
            issues=[
                f"Archive exceeds maximum allowed size "
                f"({_MAX_BACKUP_SIZE_BYTES // (1024 * 1024)} MB)."
            ],
        )
    return await asyncio.to_thread(
        _validate_archive_sync, archive_bytes, get_settings().database_path
    )


# ── Restore execution ──────────────────────────────────────────────────────────


def _extract_to_staging_sync(archive_bytes: bytes, staging_dir: Path) -> None:
    """Extract the validated archive to the staging directory."""
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        for member in zf.infolist():
            # Skip the manifest — it was already read during validation.
            if member.filename == "manifest.json":
                continue
            # Reject any path that looks dangerous (already checked, but defence in depth).
            parts = member.filename.split("/")
            if any(p in ("", "..") for p in parts):
                continue
            dest = staging_dir / member.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member.filename))


async def execute_restore(archive_bytes: bytes) -> dict[str, Any]:
    """Write a safety backup, extract to staging, write the pending marker, restart.

    Returns immediately after writing the marker — the caller should respond to
    the client before the SIGTERM fires (the signal is sent after a short delay).
    """
    from .config import get_settings

    settings = get_settings()
    staging_dir = settings.data_dir / ".restore_staging"
    marker_path = settings.data_dir / ".restore_pending"

    # Safety backup of the current state.
    safety = await create_backup(note="auto: safety backup before restore")
    log.info("restore: safety backup written to %s", safety.archive_path)

    # Extract the incoming archive to the staging area.
    await asyncio.to_thread(_extract_to_staging_sync, archive_bytes, staging_dir)
    log.info("restore: staged to %s", staging_dir)

    # Drop the pending-restore marker.
    marker_path.write_text(
        json.dumps(
            {
                "staging_dir": str(staging_dir),
                "safety_backup": str(safety.archive_path),
                "initiated_at": datetime.now(UTC).isoformat(),
            }
        )
    )

    # Schedule a SIGTERM after 500 ms so the HTTP response is flushed first.
    async def _delayed_sigterm() -> None:
        await asyncio.sleep(0.5)
        log.info("restore: sending SIGTERM for restart")
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(_delayed_sigterm())

    return {
        "status": "restore_pending",
        "safety_backup": safety.archive_path.name,
        "message": "Restore staged. The application will restart and complete the restore.",
    }


# ── Startup completion hook ────────────────────────────────────────────────────


def _restore_directory_sync(src: Path, dst: Path) -> None:
    """Replace dst with src atomically using rename where possible."""
    if not src.exists():
        return
    if dst.exists():
        # Move the old directory aside then replace.
        old = dst.parent / (dst.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        dst.rename(old)
    shutil.copytree(src, dst)
    shutil.rmtree(dst.parent / (dst.name + ".old"), ignore_errors=True)


def complete_pending_restore(data_dir: Path, db_path: Path) -> bool:
    """Called at application startup.  If a pending-restore marker exists, complete
    the restore from the staging directory and return True.  Returns False if there
    is nothing to do.

    Any error is logged and leaves the marker in place for manual recovery.
    """
    marker_path = data_dir / ".restore_pending"
    if not marker_path.exists():
        return False

    log.warning("restore: pending restore marker found — completing restore from staging")
    try:
        marker = json.loads(marker_path.read_text())
        staging_dir = Path(marker["staging_dir"])

        # ── Database ──────────────────────────────────────────────────────────
        backup_db = staging_dir / "db" / "database.sqlite"
        if not backup_db.exists():
            raise FileNotFoundError(f"Staged database not found: {backup_db}")

        source = sqlite3.connect(str(backup_db))
        dest = sqlite3.connect(str(db_path))
        try:
            source.backup(dest)
        finally:
            source.close()
            dest.close()
        log.info("restore: database restored from %s", backup_db)

        # ── Reports ──────────────────────────────────────────────────────────
        _restore_directory_sync(staging_dir / "reports", data_dir / "reports")
        log.info("restore: reports directory restored")

        # ── Uploads ──────────────────────────────────────────────────────────
        _restore_directory_sync(staging_dir / "uploads", data_dir / "uploads")
        log.info("restore: uploads directory restored")

        # ── Cleanup ───────────────────────────────────────────────────────────
        shutil.rmtree(staging_dir, ignore_errors=True)
        marker_path.unlink(missing_ok=True)

        log.info("restore: completed successfully")
        return True

    except Exception as exc:
        log.error(
            "restore: failed to complete pending restore — marker left in place: %s",
            exc,
            exc_info=True,
        )
        return False


# ── Local backup file helpers ──────────────────────────────────────────────────


def list_backup_files(data_dir: Path) -> list[dict[str, Any]]:
    """Return metadata for all backup archives on disk, newest first."""
    backups_dir = data_dir / "backups"
    if not backups_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for p in backups_dir.glob("backup_*.zip"):
        try:
            stat = p.stat()
            manifest_summary = _peek_manifest(p)
            results.append(
                {
                    "filename": p.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                    "manifest": manifest_summary,
                }
            )
        except OSError:
            pass

    results.sort(key=lambda r: r["modified_at"], reverse=True)
    return results


def _peek_manifest(archive_path: Path) -> dict[str, Any] | None:
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            if "manifest.json" not in zf.namelist():
                return None
            m = json.loads(zf.read("manifest.json"))
            return {
                "format_version": m.get("format_version"),
                "app_version": m.get("app_version"),
                "schema_revision": m.get("schema_revision"),
                "created_at": m.get("created_at"),
                "note": m.get("note"),
                "file_count": len(m.get("files", [])),
            }
    except Exception:
        return None
