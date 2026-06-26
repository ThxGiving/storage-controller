"""Compose localized multipart report and test emails.

Uses the exact finalized report artifacts (PDF/CSV/JSON) — never a separately
regenerated rendering. User-entered incident notes are never auto-translated.
"""

from __future__ import annotations

import base64
import json
import logging
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import jinja2

from .mailer import RecipientSet, SmtpConfig, SmtpError
from .models import DeliveryFailureCategory, Report
from .reporting.service import report_dir, uploads_root

log = logging.getLogger("report_email")

_TEMPLATES = Path(__file__).parent / "reporting" / "templates"
_JINJA = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES)),
    autoescape=True,
)

_MIME = {"pdf": "application/pdf", "csv": "text/csv", "json": "application/json"}

_SUBJECT = {
    "de": "HACCP-Temperaturbericht – {site} – {period}",
    "en": "HACCP Temperature Report – {site} – {period}",
}
_SUBJECT_INTERIM = {
    "de": "HACCP-Temperaturzwischenbericht – {site} – {period}",
    "en": "HACCP Interim Temperature Report – {site} – {period}",
}

_ATT_LABELS = {
    "de": {
        "pdf": ("PDF-Dokument", "Vollständiger HACCP-Temperaturbericht"),
        "csv": ("CSV-Tabelle", "Rohdaten für Auswertungen und Archivierung"),
        "json": ("JSON-Datei", "Strukturierte Berichtsdaten"),
    },
    "en": {
        "pdf": ("PDF document", "Complete HACCP temperature report"),
        "csv": ("CSV spreadsheet", "Raw data for analysis and archiving"),
        "json": ("JSON file", "Structured report data"),
    },
}

_L = {
    "de": {
        "summary_title": "Berichtszusammenfassung",
        "period": "Berichtszeitraum",
        "timezone": "Zeitzone",
        "monitored": "Überwachte Einheiten",
        "coverage": "Datenabdeckung",
        "deviations": "Bestätigte Abweichungen",
        "open_incidents": "Offene Vorfälle",
        "assessment": "Gesamtergebnis",
        "generated": "Erstellt",
        "verdict_ok": "Vollständig – keine Abweichungen",
        "verdict_documented": "Dokumentierte Abweichungen",
        "verdict_open": "Offene Vorfälle vorhanden",
        "verdict_incomplete": "Unvollständige Daten",
        "next_steps": "Nächste Schritte",
        "steps": [
            "PDF-Bericht öffnen",
            "Angaben und Abweichungen prüfen",
            "Bericht ausdrucken",
            "Unterschrift ergänzen",
            "Bericht gemäß betrieblichen Vorgaben abheften",
        ],
        "attached_files": "Anhänge",
        "attachment_intro": (
            "Der vollständige HACCP-Temperaturbericht ist dieser E-Mail als PDF beigefügt."
        ),
        "disclaimer": (
            "Dieser automatisch erstellte Bericht unterstützt die HACCP-Dokumentation "
            "und ersetzt keine betrieblichen Kontrollen, Messungen oder gesetzlichen "
            "Anforderungen."
        ),
        "automated_notice": "Automatisch erstellter Bericht",
        "interim_label": "Zwischenbericht",
    },
    "en": {
        "summary_title": "Report summary",
        "period": "Reporting period",
        "timezone": "Time zone",
        "monitored": "Monitored units",
        "coverage": "Data coverage",
        "deviations": "Confirmed deviations",
        "open_incidents": "Open incidents",
        "assessment": "Overall assessment",
        "generated": "Generated",
        "verdict_ok": "Complete – no deviations",
        "verdict_documented": "Documented deviations",
        "verdict_open": "Open incidents present",
        "verdict_incomplete": "Incomplete data",
        "next_steps": "Next steps",
        "steps": [
            "Open the PDF report",
            "Review the data and deviations",
            "Print the report",
            "Add the required signature",
            "File the report according to your operational procedures",
        ],
        "attached_files": "Attachments",
        "attachment_intro": (
            "The complete HACCP temperature report is attached to this email as a PDF."
        ),
        "disclaimer": (
            "This automatically generated report supports HACCP documentation and does not "
            "replace operational checks, measurements, or legal requirements."
        ),
        "automated_notice": "Automatically generated report",
        "interim_label": "Interim report",
    },
}

_L_TEST = {
    "de": {
        "title": "Test-E-Mail erfolgreich",
        "success_message": "Die E-Mail-Konfiguration wurde erfolgreich geprüft.",
        "test_notice": (
            "Diese Nachricht wurde von Refrigeration Logbook als Test versendet. "
            "Es wurde kein echter HACCP-Bericht erstellt oder angehängt."
        ),
        "smtp_label": "SMTP-Konfiguration",
        "host_label": "Server",
        "security_label": "Sicherheit",
        "sender_label": "Absender",
        "recipient_label": "Empfänger",
        "sent_at_label": "Gesendet",
        "action_placeholder": (
            "In echten Berichts-E-Mails erscheint hier der Hinweis zum Prüfen, "
            "Ausdrucken, Unterschreiben und Abheften."
        ),
        "disclaimer": (
            "Dieser automatisch erstellte Bericht unterstützt die HACCP-Dokumentation "
            "und ersetzt keine betrieblichen Kontrollen, Messungen oder gesetzlichen "
            "Anforderungen."
        ),
        "automated_notice": "Test-Nachricht",
    },
    "en": {
        "title": "Test email successful",
        "success_message": "The email configuration was tested successfully.",
        "test_notice": (
            "This message was sent by Refrigeration Logbook as a test. "
            "No real HACCP report was generated or attached."
        ),
        "smtp_label": "SMTP configuration",
        "host_label": "Server",
        "security_label": "Security",
        "sender_label": "Sender",
        "recipient_label": "Recipient",
        "sent_at_label": "Sent",
        "action_placeholder": (
            "In real report emails, this section will contain the instructions "
            "to review, print, sign, and file the report."
        ),
        "disclaimer": (
            "This automatically generated report supports HACCP documentation and does not "
            "replace operational checks, measurements, or legal requirements."
        ),
        "automated_notice": "Test message",
    },
}

_STATUS_COLORS = {
    "ok":           ("#16a34a", "#f0fdf4"),
    "documented":   ("#1d4ed8", "#eff6ff"),
    "open":         ("#dc2626", "#fef2f2"),
    "incomplete":   ("#ea580c", "#fff7ed"),
}


def _cov(value, locale: str) -> str:
    if value is None:
        return "—"
    s = f"{value:.1f}"
    return (s.replace(".", ",") if locale == "de" else s) + " %"


def _size_label(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _logo_data_url(logo_filename: str | None) -> str | None:
    if not logo_filename:
        return None
    try:
        p = uploads_root() / logo_filename
        if not p.is_file():
            return None
        suffix = p.suffix.lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}.get(suffix.lstrip("."), "image/png")
        data = p.read_bytes()
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    except OSError:
        return None


def _fmt_dt(iso: str, locale: str) -> str:
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso)
        if locale == "de":
            return dt.strftime("%d.%m.%Y %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return iso[:16].replace("T", " ")


def _attachments(report: Report, formats: list[str]) -> list[tuple[str, str, bytes]]:
    d = report_dir(report.uuid)
    names = {"pdf": report.pdf_filename, "csv": report.csv_filename, "json": report.json_filename}
    out: list[tuple[str, str, bytes]] = []
    for fmt in formats:
        name = names.get(fmt)
        path = d / name if name else None
        if not name or path is None or not path.is_file():
            raise SmtpError(
                DeliveryFailureCategory.attachment_missing.value,
                f"Report attachment '{fmt}' is missing.",
            )
        out.append((name, _MIME[fmt], path.read_bytes()))
    return out


def _default_bac() -> dict:
    from .reporting.accent import normalize_accent, accent_tokens
    return accent_tokens(normalize_accent(None))


def _build_report_html(ctx: dict) -> str:
    try:
        if "bac" not in ctx:
            ctx = {**ctx, "bac": _default_bac()}
        tpl = _JINJA.get_template("email_report.html")
        return tpl.render(**ctx)
    except Exception as exc:
        log.error("email_report.html render failed: %s", exc)
        raise


def _build_test_html(ctx: dict) -> str:
    try:
        if "bac" not in ctx:
            ctx = {**ctx, "bac": _default_bac()}
        tpl = _JINJA.get_template("email_test.html")
        return tpl.render(**ctx)
    except Exception as exc:
        log.error("email_test.html render failed: %s", exc)
        raise


def _build_report_plain(ctx: dict, L: dict) -> str:
    lines = [
        ctx["subject"],
        "",
        L["attachment_intro"],
        "",
        f"{L['period']}: {ctx['period_range_label']}",
        f"{L['timezone']}: {ctx['timezone_label']}",
        f"{L['monitored']}: {ctx['monitored_count']}",
        f"{L['coverage']}: {ctx['coverage']}",
        f"{L['deviations']}: {ctx['confirmed_deviations']}",
        f"{L['open_incidents']}: {ctx['open_incidents']}",
        f"{L['assessment']}: {ctx['verdict_text']}",
        f"{L['generated']}: {ctx['generated_at']}",
        "",
        f"{L['next_steps']}:",
    ]
    for i, step in enumerate(L["steps"], 1):
        lines.append(f"  {i}. {step}")
    lines += [
        "",
        f"{L['attached_files']}: " + ", ".join(a["name"] for a in ctx["attachments"]),
        "",
        L["disclaimer"],
    ]
    return "\n".join(lines)


def _build_test_plain(ctx: dict, L: dict) -> str:
    return "\n".join([
        ctx["subject"],
        "",
        L["success_message"],
        "",
        f"{L['host_label']}: {ctx['smtp_host']}:{ctx['smtp_port']}",
        f"{L['security_label']}: {ctx['smtp_security']}",
        f"{L['sender_label']}: {ctx['sender_email']}",
        f"{L['recipient_label']}: {ctx['recipient_email']}",
        f"{L['sent_at_label']}: {ctx['sent_at']}",
        "",
        L["test_notice"],
        "",
        f"[{L['action_placeholder']}]",
        "",
        L["disclaimer"],
    ])


def compose(
    report: Report,
    cfg: SmtpConfig,
    rcpts: RecipientSet,
    formats: list[str],
    *,
    max_bytes: int,
    site_name: str | None = None,
) -> tuple[EmailMessage, int]:
    """Build the report email. Raises SmtpError on attachment/size problems."""
    try:
        model = json.loads(report.model_json or "{}")
    except (ValueError, TypeError):
        model = {}

    locale = (report.locale or "en")[:2]
    L = _L.get(locale, _L["en"])
    att_labels = _ATT_LABELS.get(locale, _ATT_LABELS["en"])

    summary = model.get("summary", {})
    branding = model.get("branding", {})
    is_interim = model.get("is_interim", False)

    site = (
        site_name
        or branding.get("site_name")
        or branding.get("organization_name")
        or "Refrigeration Logbook"
    )
    from .reporting.accent import normalize_accent, accent_tokens
    bac = accent_tokens(normalize_accent(branding.get("accent")))
    period = model.get("period_label", f"{report.period_year}-{report.period_month:02d}")

    verdict = summary.get("verdict", "incomplete")
    verdict_key = f"verdict_{verdict}" if f"verdict_{verdict}" in L else "verdict_incomplete"
    status_color, status_bg = _STATUS_COLORS.get(verdict, _STATUS_COLORS["incomplete"])

    files = _attachments(report, formats)

    att_ctx = []
    for name, mime, data in files:
        fmt = next((f for f, m in _MIME.items() if m == mime), "pdf")
        type_label, description = att_labels.get(fmt, (fmt.upper(), ""))
        att_ctx.append({
            "name": name,
            "type_label": type_label,
            "size_label": _size_label(len(data)),
            "description": description,
        })

    from . import __version__
    generated_at = _fmt_dt(model.get("generated_at", ""), locale)

    ctx = {
        "lang": locale,
        "subject": (_SUBJECT_INTERIM if is_interim else _SUBJECT).get(locale, _SUBJECT["en"]).format(
            site=site, period=period
        ),
        "logo_data_url": _logo_data_url(branding.get("logo_filename")),
        "org_name": branding.get("organization_name") or "",
        "site_name": branding.get("site_name") or "",
        "report_title": branding.get("report_title") or (
            "HACCP-Temperaturbericht" if locale == "de" else "HACCP Temperature Report"
        ),
        "period_label": period,
        "period_range_label": model.get("period_range_label") or period,
        "timezone_label": model.get("timezone_label") or model.get("timezone") or "UTC",
        "monitored_count": summary.get("monitored_count", 0),
        "coverage": _cov(summary.get("coverage_percent"), locale),
        "confirmed_deviations": summary.get("confirmed_deviations", 0),
        "open_incidents": summary.get("open_incidents", 0),
        "generated_at": generated_at,
        "verdict_text": L[verdict_key],
        "status_color": status_color,
        "status_bg": status_bg,
        "is_interim": is_interim,
        "attachments": att_ctx,
        "version": __version__,
        "L": L,
        "bac": bac,
    }

    msg = EmailMessage()
    msg["Subject"] = ctx["subject"]
    if cfg.sender_email:
        msg["From"] = formataddr((cfg.sender_name or site, cfg.sender_email))
    if rcpts.to:
        msg["To"] = ", ".join(rcpts.to)
    if rcpts.cc:
        msg["Cc"] = ", ".join(rcpts.cc)
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to

    plain = _build_report_plain(ctx, L)
    msg.set_content(plain, subtype="plain", charset="utf-8")

    try:
        html = _build_report_html(ctx)
        msg.add_alternative(html, subtype="html", charset="utf-8")
    except Exception as exc:
        log.warning("HTML email rendering failed, sending plain text only: %s", exc)

    for name, mime, data in files:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)

    size = len(bytes(msg))
    if size > max_bytes:
        raise SmtpError(
            DeliveryFailureCategory.message_too_large.value,
            f"Attachments exceed the limit ({size} > {max_bytes} bytes).",
        )
    return msg, size


def compose_test_email(
    cfg: SmtpConfig,
    recipient: str,
    *,
    org_name: str | None = None,
    site_name: str | None = None,
    logo_filename: str | None = None,
    accent_color: str | None = None,
    locale: str = "en",
) -> EmailMessage:
    """Build a branded SMTP test email (no report attached)."""
    from datetime import UTC, datetime
    from . import __version__

    L = _L_TEST.get(locale[:2], _L_TEST["en"])
    now_str = _fmt_dt(datetime.now(UTC).isoformat(), locale)

    security_display = {
        "starttls": "STARTTLS",
        "implicit_tls": "TLS (implicit)",
        "plain": "Plain (unencrypted)",
    }.get(getattr(cfg, "security_mode", "starttls") or "starttls", "STARTTLS")

    from .reporting.accent import normalize_accent, accent_tokens
    bac = accent_tokens(normalize_accent(accent_color))

    subject = f"Refrigeration Logbook — {L['title']}"

    ctx = {
        "lang": locale[:2],
        "subject": subject,
        "logo_data_url": _logo_data_url(logo_filename),
        "org_name": org_name or "",
        "site_name": site_name or "",
        "sent_at": now_str,
        "smtp_host": getattr(cfg, "host", "") or "",
        "smtp_port": getattr(cfg, "port", 587),
        "smtp_security": security_display,
        "sender_email": cfg.sender_email or "",
        "recipient_email": recipient,
        "version": __version__,
        "L": L,
        "bac": bac,
    }

    msg = EmailMessage()
    msg["Subject"] = subject
    if cfg.sender_email:
        name = org_name or cfg.sender_name or "Refrigeration Logbook"
        msg["From"] = formataddr((name, cfg.sender_email))
    msg["To"] = recipient

    plain = _build_test_plain(ctx, L)
    msg.set_content(plain, subtype="plain", charset="utf-8")

    try:
        html = _build_test_html(ctx)
        msg.add_alternative(html, subtype="html", charset="utf-8")
    except Exception as exc:
        log.warning("HTML test email rendering failed, sending plain text only: %s", exc)

    return msg
