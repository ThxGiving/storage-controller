"""Compose the localized multipart report email (Phase 6).

Uses the **exact finalized report artifacts** (PDF/CSV/JSON under the report's
immutable directory) — never a separately regenerated rendering. User-entered
incident notes and corrective actions are never auto-translated; the body only
states localized summary facts.
"""

from __future__ import annotations

import json
from email.message import EmailMessage
from email.utils import formataddr

from .mailer import RecipientSet, SmtpConfig, SmtpError
from .models import DeliveryFailureCategory, Report
from .reporting.service import report_dir

_MIME = {"pdf": "application/pdf", "csv": "text/csv", "json": "application/json"}

_SUBJECT = {
    "de": "HACCP-Temperaturbericht – {site} – {period}",
    "en": "HACCP Temperature Report – {site} – {period}",
}

_L = {
    "de": {
        "intro": "Im Anhang finden Sie den automatisch erzeugten HACCP-Temperaturbericht.",
        "site": "Standort",
        "period": "Berichtszeitraum",
        "result": "Gesamtergebnis",
        "coverage": "Datenabdeckung",
        "incidents": "Abweichungen gesamt",
        "open": "Offene Vorfälle",
        "generated": "Erstellt am",
        "attachments": "Anhänge",
        "ok": "Vollständig ohne Abweichungen",
        "deviations": "Dokumentierte Abweichungen",
        "open_state": "Offene Vorfälle vorhanden",
        "disclaimer": (
            "Dieser Bericht dokumentiert Temperaturdaten zur Unterstützung der "
            "HACCP-Dokumentation und ersetzt keine betrieblichen Kontrollen."
        ),
    },
    "en": {
        "intro": "Please find attached the automatically generated HACCP temperature report.",
        "site": "Site",
        "period": "Reporting period",
        "result": "Overall result",
        "coverage": "Data coverage",
        "incidents": "Total deviations",
        "open": "Open incidents",
        "generated": "Generated",
        "attachments": "Attachments",
        "ok": "Complete with no deviations",
        "deviations": "Documented deviations",
        "open_state": "Open incidents present",
        "disclaimer": (
            "This report documents temperature data to support HACCP records and "
            "does not replace operational controls."
        ),
    },
}


def _result_text(L: dict, summary: dict) -> str:
    if summary.get("open_incidents"):
        return L["open_state"]
    if summary.get("confirmed_deviations"):
        return L["deviations"]
    return L["ok"]


def _cov(value, locale: str) -> str:
    if value is None:
        return "—"
    s = f"{value:.1f}"
    return (s.replace(".", ",") if locale == "de" else s) + " %"


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


def compose(
    report: Report,
    cfg: SmtpConfig,
    rcpts: RecipientSet,
    formats: list[str],
    *,
    max_bytes: int,
    site_name: str | None = None,
) -> tuple[EmailMessage, int]:
    """Build the email. Raises SmtpError(attachment_missing|message_too_large|internal)."""
    try:
        model = json.loads(report.model_json or "{}")
    except (ValueError, TypeError):
        model = {}
    locale = (report.locale or "en")[:2]
    L = _L.get(locale, _L["en"])
    summary = model.get("summary", {})
    branding = model.get("branding", {})
    site = (
        site_name
        or branding.get("site_name")
        or branding.get("organization_name")
        or "Storage Controller"
    )
    period = model.get("period_label", f"{report.period_year}-{report.period_month:02d}")

    files = _attachments(report, formats)

    msg = EmailMessage()
    msg["Subject"] = _SUBJECT.get(locale, _SUBJECT["en"]).format(site=site, period=period)
    if cfg.sender_email:
        msg["From"] = formataddr((cfg.sender_name or site, cfg.sender_email))
    if rcpts.to:
        msg["To"] = ", ".join(rcpts.to)
    if rcpts.cc:
        msg["Cc"] = ", ".join(rcpts.cc)
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to

    att_list = ", ".join(n for n, _m, _b in files)
    rows = [
        (L["site"], site),
        (L["period"], model.get("period_range_label") or period),
        (L["result"], _result_text(L, summary)),
        (L["coverage"], _cov(summary.get("coverage_percent"), locale)),
        (L["incidents"], str(summary.get("confirmed_deviations", 0))),
        (L["open"], str(summary.get("open_incidents", 0))),
        (L["generated"], model.get("generated_at", "")[:16].replace("T", " ")),
        (L["attachments"], att_list),
    ]
    plain = (
        L["intro"]
        + "\n\n"
        + "\n".join(f"{k}: {v}" for k, v in rows)
        + "\n\n"
        + L["disclaimer"]
    )
    msg.set_content(plain, subtype="plain", charset="utf-8")

    html_rows = "".join(
        f'<tr><td style="padding:2px 12px 2px 0;color:#555">{k}</td>'
        f'<td style="padding:2px 0"><b>{_esc(str(v))}</b></td></tr>'
        for k, v in rows
    )
    html = (
        f'<div style="font-family:Helvetica,Arial,sans-serif;font-size:14px;color:#111">'
        f"<p>{_esc(L['intro'])}</p>"
        f'<table style="border-collapse:collapse;font-size:13px">{html_rows}</table>'
        f'<p style="color:#777;font-size:12px;margin-top:16px">{_esc(L["disclaimer"])}</p></div>'
    )
    msg.add_alternative(html, subtype="html", charset="utf-8")

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


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
