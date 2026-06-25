"""SMTP settings + test endpoints (Phase 6).

The password is write-only: it is never returned (only ``password_configured``),
never logged, and never placed in diagnostics. An empty password on update
preserves the stored secret; ``clear_password`` removes it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..errors import AppError
from ..mailer import SmtpError, normalize_recipients, send_message, test_connection, valid_email
from ..models import AuditEvent, ReportBrandingSettings, SmtpSettings
from ..report_email import compose_test_email
from ..schemas import EmailTestRequest, SmtpSettingsIn, SmtpSettingsOut, SmtpTestResult
from ..smtp_store import get_or_create, to_config

log = logging.getLogger("api")
router = APIRouter(prefix="/api/settings/email", tags=["email"])

_VALID_MODES = {"starttls", "implicit_tls", "plain"}


def _user(request: Request) -> str | None:
    return request.headers.get("X-Remote-User-Name") or request.headers.get("X-Remote-User-Id")


def _loads(raw: str | None) -> list[str]:
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def _out(row: SmtpSettings) -> SmtpSettingsOut:
    return SmtpSettingsOut(
        host=row.host,
        port=row.port,
        security_mode=row.security_mode,
        auth_enabled=row.auth_enabled,
        username=row.username,
        password_configured=bool(row.password_secret),
        sender_name=row.sender_name,
        sender_email=row.sender_email,
        reply_to=row.reply_to,
        connection_timeout_seconds=row.connection_timeout_seconds,
        verify_certificates=row.verify_certificates,
        allow_insecure_plain=row.allow_insecure_plain,
        default_to=_loads(row.default_to_json),
        default_cc=_loads(row.default_cc_json),
        default_bcc=_loads(row.default_bcc_json),
        max_attachment_bytes=row.max_attachment_bytes,
        site_name=row.site_name,
        last_test_at=row.last_test_at,
        last_test_ok=row.last_test_ok,
        last_test_error=row.last_test_error,
    )


@router.get("", response_model=SmtpSettingsOut)
async def get_email_settings(db: AsyncSession = Depends(get_db)) -> SmtpSettingsOut:
    row = await get_or_create(db)
    await db.commit()
    return _out(row)


@router.put("", response_model=SmtpSettingsOut)
async def update_email_settings(
    payload: SmtpSettingsIn, request: Request, db: AsyncSession = Depends(get_db)
) -> SmtpSettingsOut:
    if payload.security_mode not in _VALID_MODES:
        raise AppError("invalid_security_mode", status_code=422)
    for addr in [*payload.default_to, *payload.default_cc, *payload.default_bcc]:
        if not valid_email(addr):
            raise AppError("invalid_recipient", status_code=422)

    row = await get_or_create(db)
    row.host = (payload.host or "").strip() or None
    row.port = payload.port
    row.security_mode = payload.security_mode
    row.auth_enabled = payload.auth_enabled
    row.username = (payload.username or "").strip() or None
    # Secret handling: explicit clear, else a non-empty value replaces, else preserve.
    if payload.clear_password:
        row.password_secret = None
    elif payload.password:
        row.password_secret = payload.password
    row.sender_name = (payload.sender_name or "").strip() or None
    row.sender_email = (payload.sender_email or "").strip() or None
    row.reply_to = (payload.reply_to or "").strip() or None
    row.connection_timeout_seconds = payload.connection_timeout_seconds
    row.verify_certificates = payload.verify_certificates
    row.allow_insecure_plain = payload.allow_insecure_plain
    row.default_to_json = json.dumps([a.strip() for a in payload.default_to])
    row.default_cc_json = json.dumps([a.strip() for a in payload.default_cc])
    row.default_bcc_json = json.dumps([a.strip() for a in payload.default_bcc])
    row.max_attachment_bytes = payload.max_attachment_bytes
    row.site_name = (payload.site_name or "").strip() or None
    row.updated_at = datetime.now(UTC)
    db.add(
        AuditEvent(
            component="email", action="smtp_config_updated", user=_user(request),
            object_type="smtp_settings", object_id="1",
            detail=f"host={row.host} mode={row.security_mode}",  # never the password
        )
    )
    await db.commit()
    return _out(row)


@router.post("/test-connection", response_model=SmtpTestResult)
async def test_smtp_connection(
    request: Request, db: AsyncSession = Depends(get_db)
) -> SmtpTestResult:
    row = await get_or_create(db)
    cfg = to_config(row)
    result = SmtpTestResult(ok=True)
    try:
        await asyncio.to_thread(test_connection, cfg)
    except SmtpError as exc:
        result = SmtpTestResult(ok=False, category=exc.category, message=exc.message)
    row.last_test_at = datetime.now(UTC)
    row.last_test_ok = result.ok
    row.last_test_error = None if result.ok else result.message
    db.add(
        AuditEvent(
            component="email", action="smtp_test_connection", user=_user(request),
            object_type="smtp_settings", object_id="1",
            detail="ok" if result.ok else f"failed:{result.category}",
        )
    )
    await db.commit()
    return result


@router.post("/test-email", response_model=SmtpTestResult)
async def send_test_email(
    payload: EmailTestRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> SmtpTestResult:
    if not valid_email(payload.recipient):
        raise AppError("invalid_recipient", status_code=422)
    row = await get_or_create(db)
    cfg = to_config(row)
    rcpts = normalize_recipients([payload.recipient])

    branding = await db.scalar(select(ReportBrandingSettings).where(ReportBrandingSettings.id == 1))
    locale = getattr(payload, "locale", None) or "en"

    msg = compose_test_email(
        cfg,
        payload.recipient,
        org_name=branding.organization_name if branding else None,
        site_name=branding.site_name if branding else (row.site_name or None),
        logo_filename=branding.logo_filename if branding else None,
        locale=locale,
    )

    result = SmtpTestResult(ok=True, message="Test email sent.")
    try:
        outcome = await asyncio.to_thread(send_message, cfg, msg, rcpts)
        if any(o == "rejected" for o in outcome.values()):
            result = SmtpTestResult(ok=False, category="recipient_rejected",
                                    message="Recipient was rejected by the server.")
    except SmtpError as exc:
        result = SmtpTestResult(ok=False, category=exc.category, message=exc.message)
    db.add(
        AuditEvent(
            component="email", action="smtp_test_email", user=_user(request),
            object_type="smtp_settings", object_id="1",
            detail="ok" if result.ok else f"failed:{result.category}",
        )
    )
    await db.commit()
    return result
