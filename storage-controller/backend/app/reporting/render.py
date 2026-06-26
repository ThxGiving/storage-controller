"""Render the immutable report model to HTML / PDF / CSV / JSON (Phase 5).

Pipeline: ReportModel → Jinja2 HTML + print CSS + server-side SVG charts →
WeasyPrint PDF. CSV and JSON are derived from the same model. Nothing is rendered
from the dashboard or by screenshotting.
"""

from __future__ import annotations

import base64
import csv
import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .charts import render_chart_svg, render_mini_svg
from .labels import labels
from .model import ReportModel

_TEMPLATES = Path(__file__).parent / "templates"


def _num(v: float, digits: int, locale: str) -> str:
    """Locale-aware decimal: German uses a comma, English a dot."""
    out = f"{v:.{digits}f}"
    return out.replace(".", ",") if locale == "de" else out


def _fmt_duration(seconds, locale: str) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    m, _ = divmod(rem, 60)
    if h and m:
        return f"{h}\u00a0h\u00a0{m}\u00a0min"
    if h:
        return f"{h}\u00a0h"
    return f"{m}\u00a0min"


def _fmt_temp(v, locale: str) -> str:
    return "\u2014" if v is None else f"{_num(v, 1, locale)}\u00a0\u00b0C"


def _fmt_pct(v, locale: str) -> str:
    return "\u2014" if v is None else f"{_num(v, 1, locale)}\u00a0%"


def _fmt_lim(v, locale: str) -> str:
    """A bare limit number for ranges like 0,0 \u2013 8,0 \u00b0C."""
    return "\u2014" if v is None else _num(v, 1, locale)


def _fmt_cov(v, below_min, locale: str) -> str:
    """Coverage %, but ``< 0,1 %`` when there is data yet it rounds below 0.1%,
    so the report never shows ``0,0 %`` next to real min/avg/max values."""
    if below_min:
        return f"<\u00a0{_num(0.1, 1, locale)}\u00a0%"
    return _fmt_pct(v, locale)


def _fmt_dt(iso, locale: str) -> str:
    if not iso:
        return "\u2014"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if locale == "de":
        return dt.strftime("%d.%m.%Y, %H:%M")
    return dt.strftime("%Y-%m-%d %H:%M")


def _env(locale: str) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["dur"] = lambda s: _fmt_duration(s, locale)
    env.filters["temp"] = lambda v: _fmt_temp(v, locale)
    env.filters["pct"] = lambda v: _fmt_pct(v, locale)
    env.filters["lim"] = lambda v: _fmt_lim(v, locale)
    env.filters["dt"] = lambda v: _fmt_dt(v, locale)
    env.filters["cov"] = lambda v, below=False: _fmt_cov(v, below, locale)
    return env


def _logo_data_uri(logo_path: Path | None) -> str | None:
    if logo_path is None or not logo_path.is_file():
        return None
    suffix = logo_path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}.get(suffix.lstrip("."), "image/png")
    try:
        data = logo_path.read_bytes()
    except OSError:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _epoch(iso: str) -> float | None:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def _sparse_note(chart, x0, x1, locale: str, tz: str, L) -> str | None:
    """If a chart's data starts well after the period start, annotate from when
    measurements are actually available (keeps the full axis, stays honest)."""
    if x0 is None or x1 is None or x1 <= x0:
        return None
    xs = [p[0] for s in chart.series for p in s.points if len(p) > 1 and p[1] is not None]
    if not xs:
        return None
    earliest = min(xs)
    if earliest <= x0 + 0.1 * (x1 - x0):  # data covers most of the period → no note
        return None
    try:
        zone = ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    dt = datetime.fromtimestamp(earliest, zone)
    date = dt.strftime("%d.%m.%Y" if locale == "de" else "%Y-%m-%d")
    return L["incomplete_from"].format(date=date)


def render_html(model: ReportModel, *, logo_path: Path | None = None) -> str:
    L = labels(model.locale)
    x0 = _epoch(model.period_start_utc)
    # Use the model's effective end (= generated_at for interim, = period_end for final).
    # Falls back to legacy generated_at clip for models stored before this field existed.
    if model.effective_end_utc:
        x1 = _epoch(model.effective_end_utc)
    else:
        x1 = _epoch(model.period_end_utc)
        gen_epoch = _epoch(model.generated_at)
        if gen_epoch and x1 and gen_epoch < x1:
            x1 = gen_epoch

    overview_svgs = [
        render_chart_svg(
            c, model.timezone, upper_label=L["upper_limit"], lower_label=L["lower_limit"],
            x_start=x0, x_end=x1, locale=model.locale,
            note=_sparse_note(c, x0, x1, model.locale, model.timezone, L),
        )
        for c in model.overview_charts
    ]
    _n = len(model.units)
    mini_svgs: dict[int, str] = {}
    for _i, u in enumerate(model.units):
        if u.chart:
            mini_svgs[u.id] = render_mini_svg(
                u.chart, model.timezone,
                width=320,
                x_start=x0, x_end=x1, locale=model.locale,
            )
    from .. import __version__
    from .accent import normalize_accent, accent_tokens
    bac = accent_tokens(normalize_accent(model.branding.accent))

    template = _env(model.locale).get_template("report.html")
    return template.render(
        m=model,
        L=L,
        overview_svgs=overview_svgs,
        mini_svgs=mini_svgs,
        logo_uri=_logo_data_uri(logo_path),
        version=__version__,
        bac=bac,
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
