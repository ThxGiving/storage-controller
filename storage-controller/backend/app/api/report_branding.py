"""Report branding settings + logo upload (Phase 5).

Branding is editable; a snapshot is frozen into each generated report so later
edits never change already-generated reports. Logo uploads are validated (PNG/JPEG,
bounded size), stored under ``/data/uploads`` with a safe UUID filename — no
user-controlled paths, no external URLs.
"""

from __future__ import annotations

import json
import logging
import uuid as uuidlib

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..errors import AppError
from ..models import AuditEvent, ReportBrandingSettings
from ..reporting.accent import normalize_accent, validate_accent
from ..reporting.service import uploads_root
from ..schemas import ReportBrandingOut, ReportBrandingUpdate

log = logging.getLogger("api")

router = APIRouter(prefix="/api/report-branding", tags=["reports"])

_MAX_LOGO_BYTES = 2 * 1024 * 1024
_ALLOWED = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg"}


def _require_admin(request: Request) -> str:
    user = request.headers.get("X-Remote-User-Name") or request.headers.get("X-Remote-User-Id")
    if not user:
        raise AppError("admin_required", status_code=403)
    return user


async def _get_or_create(db: AsyncSession) -> ReportBrandingSettings:
    b = await db.get(ReportBrandingSettings, 1)
    if b is None:
        b = ReportBrandingSettings(id=1)
        db.add(b)
        await db.flush()
    return b


def _to_out(b: ReportBrandingSettings) -> ReportBrandingOut:
    labels: list[str] = []
    if b.signature_labels_json:
        try:
            parsed = json.loads(b.signature_labels_json)
            labels = [str(x) for x in parsed] if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            labels = []
    return ReportBrandingOut(
        organization_name=b.organization_name,
        site_name=b.site_name,
        address=b.address,
        contact=b.contact,
        logo_filename=b.logo_filename,
        report_title=b.report_title,
        subtitle=b.subtitle,
        accent=b.accent,
        footer_text=b.footer_text,
        disclaimer=b.disclaimer,
        signature_labels=labels,
        default_locale=b.default_locale,
        default_timezone=b.default_timezone,
        default_detail_level=b.default_detail_level,
    )


@router.get("", response_model=ReportBrandingOut)
async def get_branding(db: AsyncSession = Depends(get_db)) -> ReportBrandingOut:
    return _to_out(await _get_or_create(db))


@router.patch("", response_model=ReportBrandingOut)
async def update_branding(
    payload: ReportBrandingUpdate, request: Request, db: AsyncSession = Depends(get_db)
) -> ReportBrandingOut:
    user = _require_admin(request)
    b = await _get_or_create(db)
    data = payload.model_dump(exclude_unset=True)
    if "accent" in data and data["accent"] is not None:
        if not validate_accent(data["accent"]):
            raise AppError("invalid_accent_color", status_code=422)
        data["accent"] = normalize_accent(data["accent"])
    labels = data.pop("signature_labels", None)
    for k, v in data.items():
        setattr(b, k, v)
    if labels is not None:
        b.signature_labels_json = json.dumps([str(x) for x in labels])
    db.add(
        AuditEvent(
            component="reports", action="branding_updated", user=user,
            object_type="report_branding", object_id="1",
        )
    )
    await db.commit()
    return _to_out(b)


@router.post("/logo", response_model=ReportBrandingOut)
async def upload_logo(
    request: Request, file: UploadFile, db: AsyncSession = Depends(get_db)
) -> ReportBrandingOut:
    user = _require_admin(request)
    suffix = _ALLOWED.get((file.content_type or "").lower())
    if suffix is None:
        raise AppError("invalid_logo_type", status_code=422)
    data = await file.read(_MAX_LOGO_BYTES + 1)
    if len(data) > _MAX_LOGO_BYTES:
        raise AppError("logo_too_large", status_code=422)
    if not data:
        raise AppError("invalid_logo_type", status_code=422)

    root = uploads_root()
    root.mkdir(parents=True, exist_ok=True)
    safe_name = f"logo-{uuidlib.uuid4().hex}{suffix}"  # UUID-based, no user input
    (root / safe_name).write_bytes(data)

    b = await _get_or_create(db)
    old = b.logo_filename
    b.logo_filename = safe_name
    db.add(
        AuditEvent(
            component="reports", action="branding_logo_uploaded", user=user,
            object_type="report_branding", object_id="1", detail=safe_name,
        )
    )
    await db.commit()
    if old and old != safe_name:
        (root / old).unlink(missing_ok=True)
    return _to_out(b)


@router.get("/logo")
async def get_logo(db: AsyncSession = Depends(get_db)):
    b = await db.get(ReportBrandingSettings, 1)
    if b is None or not b.logo_filename:
        raise AppError("logo_not_found", status_code=404)
    path = uploads_root() / b.logo_filename
    if not path.is_file():
        raise AppError("logo_not_found", status_code=404)
    media = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}.get(path.suffix.lstrip("."), "image/png")
    return FileResponse(path, media_type=media)
