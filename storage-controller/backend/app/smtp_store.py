"""SMTP settings persistence + helpers (Phase 6).

The stored password is app-private: it lives only in the App's own ``/data``
database, is never returned by the API, logged, or placed in diagnostics. On
update an empty password field preserves the existing secret; clearing it is an
explicit separate action.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from .mailer import RecipientSet, SmtpConfig, normalize_recipients
from .models import SmtpSettings

# Bounded retry backoff: immediate, +5 min, +30 min, +2 h, then failed.
RETRY_SCHEDULE_SECONDS: list[int] = [0, 300, 1800, 7200]
MAX_ATTEMPTS = len(RETRY_SCHEDULE_SECONDS)


async def get_or_create(session: AsyncSession) -> SmtpSettings:
    row = await session.get(SmtpSettings, 1)
    if row is None:
        row = SmtpSettings(id=1)
        session.add(row)
        await session.flush()
    return row


def to_config(row: SmtpSettings) -> SmtpConfig:
    return SmtpConfig(
        host=row.host or "",
        port=row.port,
        security_mode=row.security_mode,
        auth_enabled=row.auth_enabled,
        username=row.username,
        password=row.password_secret,
        sender_name=row.sender_name,
        sender_email=row.sender_email,
        reply_to=row.reply_to,
        timeout=row.connection_timeout_seconds,
        verify_certificates=row.verify_certificates,
        allow_insecure_plain=row.allow_insecure_plain,
    )


def _loads(raw: str | None) -> list[str]:
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def default_recipients(row: SmtpSettings) -> RecipientSet:
    return normalize_recipients(
        _loads(row.default_to_json), _loads(row.default_cc_json), _loads(row.default_bcc_json)
    )


def merge_recipients(
    schedule_to, schedule_cc, schedule_bcc, defaults: RecipientSet
) -> RecipientSet:
    """Per-schedule recipients override defaults; if a schedule has no To, fall
    back to the configured default recipients."""
    to = schedule_to or defaults.to
    cc = schedule_cc or defaults.cc
    bcc = schedule_bcc or defaults.bcc
    return normalize_recipients(to, cc, bcc)


def delivery_key(
    *, schedule_id: int | None, report_uuid: str, rcpts: RecipientSet, formats: list[str]
) -> str:
    """Stable identity for a logical delivery: schedule + report + recipient set +
    attachment set. A retry reuses this; a different recipient/attachment set is a
    different logical delivery."""
    canon = json.dumps(
        {
            "s": schedule_id or 0,
            "r": report_uuid,
            "to": sorted(a.lower() for a in rcpts.to),
            "cc": sorted(a.lower() for a in rcpts.cc),
            "bcc": sorted(a.lower() for a in rcpts.bcc),
            "f": sorted(formats),
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(canon.encode()).hexdigest()[:32]


def mask_email(addr: str) -> str:
    """Mask an address for ordinary diagnostics/history: ``a***@e***.com``."""
    addr = (addr or "").strip()
    if "@" not in addr:
        return "***"
    local, _, domain = addr.partition("@")
    dom = domain.split(".")
    dm = (dom[0][:1] + "***") if dom and dom[0] else "***"
    rest = ("." + ".".join(dom[1:])) if len(dom) > 1 else ""
    return f"{local[:1]}***@{dm}{rest}"
