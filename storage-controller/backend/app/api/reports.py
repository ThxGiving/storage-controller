"""Reports API (Phase 5).

Authenticated (Ingress) access; report creation and deletion require an
administrator identity and are audited. Reports are immutable after generation.
Downloads stream from ``/data/reports/<uuid>/`` — no user-controlled paths.
"""

from __future__ import annotations

import json
import logging
import uuid as uuidlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..errors import AppError
from ..models import (
    REPORT_MODEL_VERSION,
    AuditEvent,
    Report,
    ReportBrandingSettings,
    ReportDetailLevel,
    ReportStatus,
    StorageUnit,
)
from ..reporting.builder import build_report_model
from ..reporting.metrics import month_range_utc
from ..reporting.render import render_preview_html
from ..reporting.service import (
    delete_report_files,
    generate,
    report_dir,
)
from ..schemas import (
    ReportCreate,
    ReportOut,
    ReportPreviewOut,
)

log = logging.getLogger("api")

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _require_admin(request: Request) -> str:
    user = request.headers.get("X-Remote-User-Name") or request.headers.get("X-Remote-User-Id")
    if not user:
        raise AppError("admin_required", status_code=403)
    return user


def _ids(raw: str) -> list[int]:
    try:
        data = json.loads(raw)
        return [int(x) for x in data] if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _out(r: Report) -> ReportOut:
    return ReportOut(
        id=r.id,
        uuid=r.uuid,
        status=r.status,
        period_year=r.period_year,
        period_month=r.period_month,
        locale=r.locale,
        timezone=r.timezone,
        detail_level=r.detail_level,
        storage_unit_ids=_ids(r.storage_unit_ids_json),
        checksum_sha256=r.checksum_sha256,
        has_pdf=r.pdf_filename is not None,
        has_csv=r.csv_filename is not None,
        has_json=r.json_filename is not None,
        created_by=r.created_by,
        created_at=r.created_at,
        generated_at=r.generated_at,
        duration_ms=r.duration_ms,
        failure_category=r.failure_category,
        error_message=r.error_message,
    )


async def _branding(db: AsyncSession) -> ReportBrandingSettings | None:
    return await db.get(ReportBrandingSettings, 1)


async def _validate_units(db: AsyncSession, ids: list[int]) -> list[int]:
    rows = (await db.scalars(select(StorageUnit.id).where(StorageUnit.id.in_(ids)))).all()
    valid = [i for i in ids if i in set(rows)]
    if not valid:
        raise AppError("no_valid_storage_units", status_code=422)
    return valid


def _resolve_options(payload: ReportCreate, branding: ReportBrandingSettings | None):
    locale = payload.locale or (branding.default_locale if branding else "en")
    detail = payload.detail_level or (
        branding.default_detail_level if branding else ReportDetailLevel.standard.value
    )
    if detail not in {d.value for d in ReportDetailLevel}:
        detail = ReportDetailLevel.standard.value
    if locale not in ("en", "de"):
        locale = "en"
    timezone = payload.timezone or (branding.default_timezone if branding else None)
    return locale, detail, timezone


@router.post("/preview", response_model=ReportPreviewOut)
async def preview_report(
    payload: ReportCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> ReportPreviewOut:
    _require_admin(request)
    ids = await _validate_units(db, payload.storage_unit_ids)
    branding = await _branding(db)
    locale, detail, timezone = _resolve_options(payload, branding)
    model = await build_report_model(
        db,
        uuid="preview",
        year=payload.year,
        month=payload.month,
        unit_ids=ids,
        locale=locale,
        timezone=timezone,
        detail_level=detail,
    )
    from ..reporting.service import _logo_path  # local import avoids cycle at import time

    html = render_preview_html(model, logo_path=_logo_path(model))
    return ReportPreviewOut(model=model.model_dump(), html=html)


@router.post("", response_model=ReportOut, status_code=201)
async def create_report(
    payload: ReportCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> ReportOut:
    user = _require_admin(request)
    ids = await _validate_units(db, payload.storage_unit_ids)
    branding = await _branding(db)
    locale, detail, timezone = _resolve_options(payload, branding)

    if not payload.allow_duplicate:
        existing = await db.scalar(
            select(Report).where(
                Report.period_year == payload.year,
                Report.period_month == payload.month,
                Report.locale == locale,
                Report.detail_level == detail,
                Report.status.in_(
                    [ReportStatus.completed.value, ReportStatus.generating.value]
                ),
            )
        )
        if existing is not None and set(_ids(existing.storage_unit_ids_json)) == set(ids):
            raise AppError("duplicate_report", status_code=409)

    start_utc, end_utc = month_range_utc(payload.year, payload.month, timezone or "Europe/Berlin")
    report = Report(
        uuid=str(uuidlib.uuid4()),
        status=ReportStatus.queued.value,
        period_year=payload.year,
        period_month=payload.month,
        period_start_utc=start_utc,
        period_end_utc=end_utc,
        locale=locale,
        timezone=timezone or "Europe/Berlin",
        detail_level=detail,
        storage_unit_ids_json=json.dumps(ids),
        report_model_version=REPORT_MODEL_VERSION,
        created_by=user,
        created_at=datetime.now(UTC),
    )
    db.add(report)
    await db.flush()

    await generate(db, report)

    ok = report.status == ReportStatus.completed.value
    db.add(
        AuditEvent(
            component="reports",
            action="report_generated" if ok else "report_failed",
            user=user,
            object_type="report",
            object_id=report.uuid,
            detail=f"{payload.year}-{payload.month:02d} units={ids} {report.status}",
        )
    )
    await db.commit()
    return _out(report)


@router.get("", response_model=list[ReportOut])
async def list_reports(db: AsyncSession = Depends(get_db)) -> list[ReportOut]:
    rows = (
        await db.scalars(select(Report).order_by(Report.created_at.desc()).limit(200))
    ).all()
    return [_out(r) for r in rows]


async def _get(db: AsyncSession, report_id: int) -> Report:
    r = await db.get(Report, report_id)
    if r is None:
        raise AppError("report_not_found", status_code=404)
    return r


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: int, db: AsyncSession = Depends(get_db)) -> ReportOut:
    return _out(await _get(db, report_id))


def _file(report: Report, name: str | None, media: str, suffix: str) -> FileResponse:
    if name is None or report.status != ReportStatus.completed.value:
        raise AppError("report_not_ready", status_code=409)
    path = report_dir(report.uuid) / name
    if not path.is_file():
        raise AppError("report_file_missing", status_code=404)
    filename = f"report-{report.period_year}-{report.period_month:02d}-{report.uuid[:8]}.{suffix}"
    return FileResponse(path, media_type=media, filename=filename)


@router.get("/{report_id}/pdf")
async def report_pdf(report_id: int, db: AsyncSession = Depends(get_db)):
    r = await _get(db, report_id)
    return _file(r, r.pdf_filename, "application/pdf", "pdf")


@router.get("/{report_id}/csv")
async def report_csv(report_id: int, db: AsyncSession = Depends(get_db)):
    r = await _get(db, report_id)
    return _file(r, r.csv_filename, "text/csv", "csv")


@router.get("/{report_id}/json")
async def report_json(report_id: int, db: AsyncSession = Depends(get_db)):
    r = await _get(db, report_id)
    if r.model_json is None:
        raise AppError("report_not_ready", status_code=409)
    return StreamingResponse(iter([r.model_json]), media_type="application/json")


@router.delete("/{report_id}", status_code=204)
async def delete_report(
    report_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    user = _require_admin(request)
    r = await _get(db, report_id)
    uuid = r.uuid
    db.add(
        AuditEvent(
            component="reports",
            action="report_deleted",
            user=user,
            object_type="report",
            object_id=uuid,
            detail=f"{r.period_year}-{r.period_month:02d}",
        )
    )
    await db.delete(r)
    await db.commit()
    delete_report_files(uuid)
