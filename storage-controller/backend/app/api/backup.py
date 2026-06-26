"""Backup and restore API (Phase 7).

All endpoints require an administrator identity via the HA Ingress header.
Operations are audited.

POST   /api/backup               — create a new backup; returns BackupJobOut
GET    /api/backup               — list existing backup records
GET    /api/backup/{id}/download — stream the ZIP archive
DELETE /api/backup/{id}          — delete backup record and archive from disk
POST   /api/backup/validate      — validate an uploaded archive (dry-run)
POST   /api/backup/restore       — validate + execute restore (triggers restart)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..backup import (
    ValidationResult,
    create_backup,
    execute_restore,
    list_backup_files,
    validate_archive,
)
from ..config import get_settings
from ..db import get_db
from ..errors import AppError
from ..models import AuditEvent, BackupJob, BackupStatus

log = logging.getLogger("api")

router = APIRouter(prefix="/api/backup", tags=["backup"])

_MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB — same limit as backup.py


# ── Auth helper ────────────────────────────────────────────────────────────────


def _require_admin(request: Request) -> str:
    user = request.headers.get("X-Remote-User-Display-Name", "").strip()
    if not user:
        user = request.headers.get("X-Remote-User-Name", "admin")
    return user


# ── Output schema helpers ──────────────────────────────────────────────────────


def _job_to_dict(job: BackupJob) -> dict:
    return {
        "id": job.id,
        "created_at": job.created_at.isoformat(),
        "status": job.status,
        "filename": job.filename,
        "size_bytes": job.size_bytes,
        "format_version": job.format_version,
        "app_version": job.app_version,
        "schema_revision": job.schema_revision,
        "note": job.note,
        "is_safety_backup": job.is_safety_backup,
        "error_message": job.error_message,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("")
async def create_backup_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new backup archive and record it in the database."""
    user = _require_admin(request)

    try:
        result = await create_backup()
    except Exception as exc:
        log.error("backup: creation failed: %s", exc, exc_info=True)
        raise AppError(500, "backup_failed", f"Backup creation failed: {exc}") from exc

    job = BackupJob(
        created_at=datetime.now(UTC),
        status=BackupStatus.completed.value,
        filename=result.archive_path.name,
        size_bytes=result.size_bytes,
        format_version=result.manifest.get("format_version", 1),
        app_version=result.manifest.get("app_version", ""),
        schema_revision=result.manifest.get("schema_revision", ""),
        note=None,
        is_safety_backup=False,
    )
    db.add(job)
    db.add(
        AuditEvent(
            component="backup",
            action="backup_created",
            user=user,
            object_type="backup_job",
            object_id=result.archive_path.name,
            details_json=f'{{"filename":"{result.archive_path.name}","size":{result.size_bytes}}}',
        )
    )
    await db.commit()
    await db.refresh(job)

    return _job_to_dict(job)


@router.get("")
async def list_backups(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return all backup records, newest first."""
    rows = (
        await db.execute(
            select(BackupJob).order_by(BackupJob.created_at.desc())
        )
    ).scalars().all()
    return [_job_to_dict(j) for j in rows]


@router.get("/{job_id}/download")
async def download_backup(job_id: int, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    """Stream the backup ZIP archive to the client."""
    job = await db.get(BackupJob, job_id)
    if job is None:
        raise AppError(404, "not_found", "Backup record not found.")

    settings = get_settings()
    archive_path = settings.data_dir / "backups" / job.filename
    if not archive_path.is_file():
        raise AppError(404, "file_missing", "Backup file not found on disk.")

    def _iter():
        with archive_path.open("rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{job.filename}"',
            "Content-Length": str(archive_path.stat().st_size),
        },
    )


@router.delete("/{job_id}")
async def delete_backup(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a backup record and its archive from disk."""
    user = _require_admin(request)

    job = await db.get(BackupJob, job_id)
    if job is None:
        raise AppError(404, "not_found", "Backup record not found.")

    settings = get_settings()
    archive_path = settings.data_dir / "backups" / job.filename
    archive_path.unlink(missing_ok=True)

    db.add(
        AuditEvent(
            component="backup",
            action="backup_deleted",
            user=user,
            object_type="backup_job",
            object_id=job.filename,
        )
    )
    await db.delete(job)
    await db.commit()
    return {"deleted": True, "filename": job.filename}


@router.post("/validate")
async def validate_backup_endpoint(file: UploadFile) -> dict:
    """Validate an uploaded backup archive without modifying any data.

    Returns a validation summary including any issues, warnings, and manifest
    metadata.  Does not require authentication because no data is modified.
    """
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise AppError(413, "too_large", "Uploaded archive exceeds the 512 MB limit.")

    result: ValidationResult = await validate_archive(data)
    return {
        "valid": result.valid,
        "issues": result.issues,
        "warnings": result.warnings,
        "manifest": result.manifest_summary,
    }


@router.post("/restore")
async def restore_backup_endpoint(
    file: UploadFile,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate and execute a restore from the uploaded archive.

    Flow:
      1. Read and validate the archive.
      2. If validation passes: create a safety backup, stage the archive,
         write a .restore_pending marker, and schedule a SIGTERM.
      3. The application restarts; on startup the pending restore is completed.

    The response is sent before the SIGTERM fires.  The caller should expect
    the application to become briefly unavailable while it restarts.
    """
    user = _require_admin(request)

    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise AppError(413, "too_large", "Uploaded archive exceeds the 512 MB limit.")

    result: ValidationResult = await validate_archive(data)
    if not result.valid:
        raise AppError(
            422,
            "invalid_backup",
            "Archive validation failed: " + "; ".join(result.issues),
        )

    # Audit before the restart makes it impossible to write to the DB afterwards.
    db.add(
        AuditEvent(
            component="backup",
            action="restore_initiated",
            user=user,
            object_type="backup_job",
            object_id=file.filename or "upload",
            details_json=(
                f'{{"app_version":"{result.manifest_summary.get("app_version") if result.manifest_summary else ""}"}}'
            ),
        )
    )
    await db.commit()

    outcome = await execute_restore(data)
    return outcome
