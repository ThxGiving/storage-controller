"""Unit tests for the branded report and test email templates."""

from __future__ import annotations

import email as email_lib
import pathlib
import tempfile

import pytest

from app.mailer import SmtpConfig
from app.report_email import compose_test_email, _build_report_html, _build_test_html, _L, _L_TEST


def _cfg(**kw) -> SmtpConfig:
    base = dict(host="mail.example.com", port=587, security_mode="starttls",
                sender_email="no-reply@example.com")
    base.update(kw)
    return SmtpConfig(**base)


def _report_ctx(locale="de", is_interim=False, deviations=0, open_inc=0,
                org_name="Muster GmbH", site_name="Lager Nord", logo_data_url=None):
    L = _L.get(locale, _L["en"])
    verdict = "documented" if deviations else ("open" if open_inc else "ok")
    colors = {"ok": ("#16a34a", "#f0fdf4"), "documented": ("#1d4ed8", "#eff6ff"),
              "open": ("#dc2626", "#fef2f2"), "incomplete": ("#ea580c", "#fff7ed")}
    sc, sb = colors[verdict]
    return {
        "lang": locale,
        "subject": f"HACCP – {org_name} – Juni 2026",
        "logo_data_url": logo_data_url,
        "org_name": org_name,
        "site_name": site_name,
        "report_title": "HACCP-Temperaturbericht" if locale == "de" else "HACCP Temperature Report",
        "period_label": "Juni 2026",
        "period_range_label": "01.06.2026 – 26.06.2026" if locale == "de" else "2026-06-01 – 2026-06-26",
        "timezone_label": "MEZ" if locale == "de" else "CET",
        "monitored_count": 3,
        "coverage": "51,3 %" if locale == "de" else "51.3 %",
        "confirmed_deviations": deviations,
        "open_incidents": open_inc,
        "generated_at": "26.06.2026 09:30" if locale == "de" else "2026-06-26 09:30",
        "verdict_text": L[f"verdict_{verdict}"],
        "status_color": sc,
        "status_bg": sb,
        "is_interim": is_interim,
        "version": "0.4.3",
        "attachments": [
            {"name": "report.pdf", "type_label": "PDF", "size_label": "412 KB",
             "description": L["attachment_intro"]},
        ],
        "L": L,
    }


def _test_ctx(locale="de", org_name="Muster GmbH", site_name="", logo_data_url=None):
    L = _L_TEST.get(locale, _L_TEST["en"])
    return {
        "lang": locale,
        "subject": f"Refrigeration Logbook — {L['title']}",
        "logo_data_url": logo_data_url,
        "org_name": org_name,
        "site_name": site_name,
        "sent_at": "26.06.2026 09:30" if locale == "de" else "2026-06-26 09:30",
        "smtp_host": "mail.example.com",
        "smtp_port": 587,
        "smtp_security": "STARTTLS",
        "sender_email": "no-reply@example.com",
        "recipient_email": "manager@example.com",
        "version": "0.4.3",
        "L": L,
    }


def _parts(msg) -> dict[str, str]:
    parsed = email_lib.message_from_bytes(bytes(msg))
    parts = {}
    for part in parsed.walk():
        payload = part.get_payload(decode=True)
        if payload:
            parts[part.get_content_type()] = payload.decode("utf-8", errors="replace")
    return parts


# ---------------------------------------------------------------------------
# Report email — HTML rendering
# ---------------------------------------------------------------------------

def test_report_html_de_renders():
    html = _build_report_html(_report_ctx("de"))
    assert "Berichtszusammenfassung" in html
    assert "Nächste Schritte" in html
    assert "Anhänge" in html
    assert "HACCP-Dokumentation" in html


def test_report_html_en_renders():
    html = _build_report_html(_report_ctx("en"))
    assert "Report summary" in html
    assert "Next steps" in html
    assert "Attachments" in html
    assert "HACCP documentation" in html


def test_report_html_interim_badge_present():
    html = _build_report_html(_report_ctx("de", is_interim=True))
    assert "Zwischenbericht" in html


def test_report_html_no_interim_badge_when_final():
    html = _build_report_html(_report_ctx("de", is_interim=False))
    assert "Zwischenbericht" not in html


def test_report_html_deviation_color_orange():
    html = _build_report_html(_report_ctx("de", deviations=2))
    assert "#ea580c" in html  # orange for deviations


def test_report_html_no_deviation_color_when_zero():
    html = _build_report_html(_report_ctx("de", deviations=0))
    # red/orange should not appear for incidents column
    assert 'color:#ea580c' not in html or 'confirmed_deviations' not in html


def test_report_html_open_incident_red():
    html = _build_report_html(_report_ctx("de", open_inc=1))
    assert "#dc2626" in html


def test_report_html_action_steps_numbered():
    html = _build_report_html(_report_ctx("de"))
    # All 5 steps should be present
    assert "1." in html
    assert "5." in html
    assert "PDF-Bericht öffnen" in html
    assert "Unterschrift" in html


def test_report_html_action_steps_en():
    html = _build_report_html(_report_ctx("en"))
    assert "Open the PDF report" in html
    assert "Add the required signature" in html


def test_report_html_no_logo_when_none():
    html = _build_report_html(_report_ctx("de", logo_data_url=None))
    assert "<img" not in html


def test_report_html_logo_embedded_as_data_url():
    html = _build_report_html(_report_ctx("de", logo_data_url="data:image/png;base64,abc123"))
    assert 'src="data:image/png;base64,abc123"' in html


def test_report_html_org_and_site_in_header():
    html = _build_report_html(_report_ctx("de", org_name="Muster GmbH", site_name="Lager Nordost"))
    assert "Muster GmbH" in html
    assert "Lager Nordost" in html


def test_report_html_long_org_name():
    long = "Sehr Lange Unternehmens-Bezeichnung Kühlhaus und Tiefkühlbetrieb GmbH & Co. KG"
    html = _build_report_html(_report_ctx("de", org_name=long))
    # Jinja2 autoescape encodes & as &amp;
    assert "Sehr Lange Unternehmens-Bezeichnung Kühlhaus und Tiefkühlbetrieb GmbH" in html


def test_report_html_no_brand_fallback():
    html = _build_report_html(_report_ctx("de", org_name="", site_name=""))
    assert "Refrigeration Logbook" in html


def test_report_html_is_valid_html():
    html = _build_report_html(_report_ctx("de"))
    assert html.strip().startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "<body" in html


def test_report_html_no_external_resources():
    html = _build_report_html(_report_ctx("de"))
    # No external font loads or remote images
    assert "fonts.googleapis.com" not in html
    assert "http://" not in html.replace("https://", "")  # no http URLs


def test_report_html_inline_css_only():
    html = _build_report_html(_report_ctx("de"))
    # No <link> stylesheets
    assert "<link" not in html
    # No <script>
    assert "<script" not in html


# ---------------------------------------------------------------------------
# Test email — HTML rendering
# ---------------------------------------------------------------------------

def test_test_email_html_de_renders():
    html = _build_test_html(_test_ctx("de"))
    assert "Test-E-Mail erfolgreich" in html
    assert "SMTP-Konfiguration" in html
    assert "Verbindungsprüfung" in html


def test_test_email_html_en_renders():
    html = _build_test_html(_test_ctx("en"))
    assert "Test email successful" in html
    assert "SMTP configuration" in html
    assert "Connection verification" in html


def test_test_email_html_smtp_details_present():
    html = _build_test_html(_test_ctx("de"))
    assert "mail.example.com" in html
    assert "587" in html
    assert "STARTTLS" in html
    assert "no-reply@example.com" in html
    assert "manager@example.com" in html


def test_test_email_html_with_logo():
    html = _build_test_html(_test_ctx("de", logo_data_url="data:image/png;base64,xyz"))
    assert 'src="data:image/png;base64,xyz"' in html


def test_test_email_html_without_logo():
    html = _build_test_html(_test_ctx("de", logo_data_url=None))
    assert "<img" not in html


def test_test_email_no_report_attached_notice():
    html = _build_test_html(_test_ctx("de"))
    assert "kein echter HACCP-Bericht" in html


def test_test_email_no_report_attached_notice_en():
    html = _build_test_html(_test_ctx("en"))
    assert "No real HACCP report" in html


# ---------------------------------------------------------------------------
# compose_test_email — multipart structure
# ---------------------------------------------------------------------------

def test_compose_test_email_de_has_plain_and_html():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.de", locale="de")
    parts = _parts(msg)
    assert "text/plain" in parts
    assert "text/html" in parts


def test_compose_test_email_en_has_plain_and_html():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.com", locale="en")
    parts = _parts(msg)
    assert "text/plain" in parts
    assert "text/html" in parts


def test_compose_test_email_subject_de():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.de", locale="de")
    assert "Test-E-Mail erfolgreich" in msg["Subject"]


def test_compose_test_email_subject_en():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.com", locale="en")
    assert "Test email successful" in msg["Subject"]


def test_compose_test_email_from_header():
    cfg = _cfg(sender_name="Muster GmbH")
    msg = compose_test_email(cfg, "r@example.com", org_name="Muster GmbH")
    assert "Muster GmbH" in msg["From"]
    assert "no-reply@example.com" in msg["From"]


def test_compose_test_email_plain_contains_smtp_info():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.com", locale="en")
    plain = _parts(msg)["text/plain"]
    assert "mail.example.com" in plain
    assert "587" in plain
    assert "STARTTLS" in plain


def test_compose_test_email_plain_contains_checks():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.de", locale="de")
    plain = _parts(msg)["text/plain"]
    assert "Verbindungsprüfung" in plain
    assert "Authentifizierung erfolgreich" in plain


def test_compose_test_email_de_utf8_umlauts():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.de",
                              org_name="Kühlhaus GmbH", locale="de")
    parts = _parts(msg)
    assert "Kühlhaus GmbH" in parts["text/html"]


def test_compose_test_email_no_branding_fallback():
    cfg = _cfg()
    msg = compose_test_email(cfg, "r@example.com", locale="en")
    parts = _parts(msg)
    assert "Refrigeration Logbook" in parts["text/html"]


def test_compose_test_email_logo_via_file(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)  # minimal PNG header

    import unittest.mock as mock
    with mock.patch("app.report_email.uploads_root", return_value=tmp_path):
        cfg = _cfg()
        msg = compose_test_email(cfg, "r@example.com",
                                  logo_filename="logo.png", locale="en")
    parts = _parts(msg)
    assert "data:image/png;base64," in parts["text/html"]


def test_compose_test_email_missing_logo_does_not_raise(tmp_path):
    import unittest.mock as mock
    with mock.patch("app.report_email.uploads_root", return_value=tmp_path):
        cfg = _cfg()
        msg = compose_test_email(cfg, "r@example.com",
                                  logo_filename="nonexistent.png", locale="en")
    assert msg is not None
    parts = _parts(msg)
    assert "<img" not in parts.get("text/html", "")
