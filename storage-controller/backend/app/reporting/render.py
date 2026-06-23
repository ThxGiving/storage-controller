"""Render the immutable report model to HTML / PDF / CSV / JSON (Phase 5).

Pipeline: ReportModel → Jinja2 HTML + print CSS + server-side SVG charts →
WeasyPrint PDF. CSV and JSON are derived from the same model. Nothing is rendered
from the dashboard or by screenshotting.
"""

from __future__ import annotations

import base64
import csv
import io
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .charts import render_chart_svg, render_mini_svg
from .labels import labels
from .model import ReportModel

_TEMPLATES = Path(__file__).parent / "templates"


def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "0m"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, _ = divmod(rem, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _fmt_temp(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f} °C"


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f}%"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["dur"] = _fmt_duration
    env.filters["temp"] = _fmt_temp
    env.filters["pct"] = _fmt_pct
    return env


def _logo_data_uri(logo_path: Path | None) -> str | None:
    if logo_path is None or not logo_path.is_file():
        return None
    suffix = logo_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    try:
        data = logo_path.read_bytes()
    except OSError:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def render_html(model: ReportModel, *, logo_path: Path | None = None) -> str:
    L = labels(model.locale)
    overview_svgs = [render_chart_svg(c, model.timezone) for c in model.overview_charts]
    mini_svgs = {
        u.id: render_mini_svg(u.chart, model.timezone) for u in model.units if u.chart
    }
    template = _env().get_template("report.html")
    return template.render(
        m=model,
        L=L,
        overview_svgs=overview_svgs,
        mini_svgs=mini_svgs,
        logo_uri=_logo_data_uri(logo_path),
    )


def render_preview_html(model: ReportModel, *, logo_path: Path | None = None) -> str:
    """Self-contained HTML (CSS inlined) for an in-app print-approximating preview."""
    html = render_html(model, logo_path=logo_path)
    css = (_TEMPLATES / "print.css").read_text(encoding="utf-8")
    return html.replace(
        '<link rel="stylesheet" href="print.css"/>', f"<style>{css}</style>"
    )


def render_pdf(model: ReportModel, *, logo_path: Path | None = None) -> bytes:
    from weasyprint import HTML  # imported lazily so tests can run without it

    html = render_html(model, logo_path=logo_path)
    return HTML(string=html, base_url=str(_TEMPLATES)).write_pdf()


def render_json(model: ReportModel) -> str:
    return model.model_dump_json(indent=2)


def render_csv(model: ReportModel) -> str:
    L = labels(model.locale)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([L["report_id"], model.uuid])
    w.writerow([L["period"], model.period_label])
    w.writerow([L["generated"], model.generated_at])
    w.writerow([L["timezone"], model.timezone_label])
    w.writerow([])
    w.writerow([
        L["unit"], L["type"], "lower_c", "upper_c", L["min"], L["max"], L["avg"],
        L["coverage"], L["unavailable"] + "_s", L["time_above"] + "_s",
        L["time_below"] + "_s", L["incidents"], L["longest_incident"] + "_s",
        L["defrost_cycles"],
    ])
    for u in model.units:
        w.writerow([
            u.name,
            u.profile_name or u.unit_type,
            u.thresholds.lower_limit_c if u.thresholds.lower_limit_c is not None else "",
            u.thresholds.upper_limit_c if u.thresholds.upper_limit_c is not None else "",
            u.min_c if u.min_c is not None else "",
            u.max_c if u.max_c is not None else "",
            u.avg_c if u.avg_c is not None else "",
            u.data_quality.coverage_percent if u.data_quality.coverage_percent is not None else "",
            u.data_quality.unavailable_seconds,
            u.time_above_seconds,
            u.time_below_seconds,
            u.incident_count,
            u.longest_incident_seconds,
            u.defrost.cycle_count if u.defrost else 0,
        ])
    return buf.getvalue()
