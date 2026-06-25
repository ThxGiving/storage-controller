"""Outbound SMTP transport (Phase 6).

Blocking stdlib ``smtplib`` is used inside ``asyncio.to_thread`` (no extra
dependency, Alpine-safe). Three security modes are supported and never inferred
from the port. Failures are classified and **sanitized** — the password and raw
protocol transcripts never appear in returned messages, logs, or diagnostics.
"""

from __future__ import annotations

import re
import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage

from .models import DeliveryFailureCategory, SmtpSecurityMode

# Deliberately permissive but injection-safe address check (one @, no CR/LF/spaces).
_EMAIL_RE = re.compile(r"^[^@\s,;:<>\"\\]+@[^@\s,;:<>\"\\]+\.[^@\s,;:<>\"\\]+$")


class SmtpError(Exception):
    """A sanitized SMTP failure with a stable category."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass
class SmtpConfig:
    host: str
    port: int
    security_mode: str
    auth_enabled: bool = False
    username: str | None = None
    password: str | None = None  # secret — never logged or returned
    sender_name: str | None = None
    sender_email: str | None = None
    reply_to: str | None = None
    timeout: int = 30
    verify_certificates: bool = True
    allow_insecure_plain: bool = False


@dataclass
class RecipientSet:
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[str]:
        return [*self.to, *self.cc, *self.bcc]

    @property
    def count(self) -> int:
        return len(self.all)


def valid_email(addr: str) -> bool:
    a = (addr or "").strip()
    if "\r" in a or "\n" in a:  # header-injection guard
        return False
    return bool(_EMAIL_RE.match(a))


def normalize_recipients(
    to: list[str], cc: list[str] | None = None, bcc: list[str] | None = None
) -> RecipientSet:
    """Trim, validate, strip header-injection, and de-duplicate (case-insensitive)
    across To/CC/BCC, preserving first-seen order and bucket."""
    seen: set[str] = set()
    out = RecipientSet()
    for bucket, items in (("to", to), ("cc", cc or []), ("bcc", bcc or [])):
        target = getattr(out, bucket)
        for raw in items:
            a = (raw or "").strip()
            if not valid_email(a):
                continue
            key = a.lower()
            if key in seen:
                continue
            seen.add(key)
            target.append(a)
    return out


def invalid_addresses(addrs: list[str]) -> list[str]:
    return [a for a in addrs if not valid_email((a or "").strip())]


def _context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _connect(cfg: SmtpConfig) -> smtplib.SMTP:
    """Open a connection honouring the selected security mode. Raises SmtpError."""
    if not cfg.host:
        raise SmtpError(DeliveryFailureCategory.connection.value, "SMTP host is not configured.")
    try:
        if cfg.security_mode == SmtpSecurityMode.implicit_tls.value:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                cfg.host, cfg.port, timeout=cfg.timeout, context=_context(cfg.verify_certificates)
            )
            smtp.ehlo()
        else:
            smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
            smtp.ehlo()
            if cfg.security_mode == SmtpSecurityMode.starttls.value:
                if not smtp.has_extn("starttls"):
                    smtp.close()
                    raise SmtpError(
                        DeliveryFailureCategory.tls.value,
                        "Server does not offer STARTTLS; refusing to send unencrypted.",
                    )
                smtp.starttls(context=_context(cfg.verify_certificates))
                smtp.ehlo()
    except ssl.SSLError as exc:
        raise SmtpError(DeliveryFailureCategory.tls.value, _san_ssl(exc)) from None
    except (TimeoutError, OSError) as exc:
        raise SmtpError(DeliveryFailureCategory.connection.value, _san_conn(exc)) from None

    if cfg.auth_enabled and cfg.username:
        if cfg.security_mode == SmtpSecurityMode.plain.value and not cfg.allow_insecure_plain:
            smtp.close()
            raise SmtpError(
                DeliveryFailureCategory.tls.value,
                "Refusing to send credentials over an unencrypted connection.",
            )
        try:
            smtp.login(cfg.username, cfg.password or "")
        except smtplib.SMTPAuthenticationError as exc:
            smtp.close()
            raise SmtpError(
                DeliveryFailureCategory.authentication.value,
                f"Authentication failed (SMTP {exc.smtp_code}).",
            ) from None
        except (smtplib.SMTPException, OSError) as exc:
            smtp.close()
            raise SmtpError(DeliveryFailureCategory.connection.value, _san_conn(exc)) from None
    return smtp


def test_connection(cfg: SmtpConfig) -> None:
    """Verify connectivity / TLS / auth without sending a message. Raises SmtpError."""
    smtp = _connect(cfg)
    try:
        smtp.noop()
    finally:
        try:
            smtp.quit()
        except smtplib.SMTPException:
            smtp.close()


def send_message(cfg: SmtpConfig, msg: EmailMessage, rcpts: RecipientSet) -> dict[str, str]:
    """Send a prepared message. Returns a per-recipient outcome map
    ``{address: "accepted"|"rejected"}``. Raises SmtpError for whole-message
    failures (connection/auth/all-recipients-refused/...)."""
    smtp = _connect(cfg)
    outcome: dict[str, str] = {a: "accepted" for a in rcpts.all}
    try:
        refused = smtp.send_message(msg, from_addr=cfg.sender_email, to_addrs=rcpts.all)
        for addr in refused:
            outcome[addr] = "rejected"
    except smtplib.SMTPRecipientsRefused as exc:
        for addr in exc.recipients:
            outcome[addr] = "rejected"
    except smtplib.SMTPSenderRefused as exc:
        cat = (
            DeliveryFailureCategory.temporary.value
            if 400 <= exc.smtp_code < 500
            else DeliveryFailureCategory.permanent.value
        )
        raise SmtpError(cat, f"Sender refused (SMTP {exc.smtp_code}).") from None
    except smtplib.SMTPResponseException as exc:
        cat = (
            DeliveryFailureCategory.temporary.value
            if 400 <= exc.smtp_code < 500
            else DeliveryFailureCategory.permanent.value
        )
        raise SmtpError(cat, f"SMTP error {exc.smtp_code}.") from None
    except (smtplib.SMTPException, ssl.SSLError, OSError) as exc:
        raise SmtpError(DeliveryFailureCategory.connection.value, _san_conn(exc)) from None
    finally:
        try:
            smtp.quit()
        except smtplib.SMTPException:
            smtp.close()
    return outcome


def _san_conn(exc: Exception) -> str:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Connection timed out."
    if isinstance(exc, socket.gaierror):
        return "Host could not be resolved."
    return "Could not connect to the SMTP server."


def _san_ssl(_exc: ssl.SSLError) -> str:
    return "TLS negotiation or certificate validation failed."
