"""Server-side SVG charts for reports (Phase 5 redesign).

Pure-Python vector SVG matching the mockup: colored per-unit series, configured
red/blue dashed limit lines, shaded deviation / data-gap / defrost bands, a
compact ``°C`` axis, month date labels, and a small legend. No browser, no
dashboard state, no interpolation across gaps.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .model import ChartBand, ChartSeries, OverviewChart

_BAND_FILL = {
    "deviation": "#fecaca",
    "gap": "#fde68a",
    "defrost": "#dbeafe",
}
_UPPER = "#dc2626"
_LOWER = "#2563eb"


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _bounds(series: list[ChartSeries], lo: float | None, hi: float | None):
    vals: list[float] = []
    for s in series:
        vals.extend(v for _, v in s.points if v is not None)
    if lo is not None:
        vals.append(lo)
    if hi is not None:
        vals.append(hi)
    if not vals:
        return 0.0, 10.0
    vmin, vmax = min(vals), max(vals)
    if vmax - vmin < 2.0:
        vmin -= 1.0
        vmax += 1.0
    pad = (vmax - vmin) * 0.14
    return vmin - pad, vmax + pad


def _x_domain(series: list[ChartSeries]):
    xs = [p[0] for s in series for p in s.points if p[0] is not None]
    if not xs:
        return 0.0, 1.0
    return min(xs), max(xs)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_chart_svg(
    chart: OverviewChart,
    tz: str,
    *,
    width: int = 700,
    plot_h: int = 132,
    legend: bool = True,
    upper_label: str = "Upper limit",
    lower_label: str = "Lower limit",
) -> str:
    series = [s for s in chart.series if s.points]
    pad_l, pad_r, pad_t, pad_b = 26, 6, 12, 14
    legend_h = 14 if legend else 0
    height = pad_t + plot_h + pad_b + legend_h
    pw = width - pad_l - pad_r
    x0, x1 = _x_domain(series)
    y0, y1 = _bounds(series, chart.lower_limit_c, chart.upper_limit_c)
    xr = (x1 - x0) or 1.0
    yr = (y1 - y0) or 1.0
    plot_top = pad_t
    plot_bot = pad_t + plot_h

    def sx(x: float) -> float:
        return pad_l + (x - x0) / xr * pw

    def sy(v: float) -> float:
        return plot_top + (y1 - v) / yr * plot_h

    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="DejaVu Sans, Helvetica, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]

    # shaded bands (behind everything)
    all_bands: list[ChartBand] = list(chart.bands) + [b for s in series for b in s.bands]
    for b in all_bands:
        bx0 = max(pad_l, sx(b.start))
        bx1 = min(pad_l + pw, sx(b.end))
        if bx1 <= bx0:
            bx1 = bx0 + 1.2  # keep instantaneous events visible
        p.append(
            f'<rect x="{bx0:.1f}" y="{plot_top}" width="{bx1 - bx0:.1f}" height="{plot_h}" '
            f'fill="{_BAND_FILL.get(b.kind, "#eee")}" fill-opacity="0.55"/>'
        )

    p.append(
        f'<rect x="{pad_l}" y="{plot_top}" width="{pw}" height="{plot_h}" fill="none" '
        f'stroke="#e5e7eb" stroke-width="0.5"/>'
    )

    # y gridlines + labels
    for frac in (0.0, 0.33, 0.66, 1.0):
        v = y1 - frac * yr
        yy = sy(v)
        p.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l + pw}" y2="{yy:.1f}" '
            f'stroke="#f1f1f1" stroke-width="0.5"/>'
        )
        p.append(
            f'<text x="{pad_l - 3}" y="{yy + 2.2:.1f}" font-size="6" text-anchor="end" '
            f'fill="#9ca3af">{v:.0f}</text>'
        )

    p.append(
        f'<text x="2" y="{plot_top + 5}" font-size="6.5" fill="#6b7280">°C</text>'
    )

    # limit lines
    for limit, color in ((chart.upper_limit_c, _UPPER), (chart.lower_limit_c, _LOWER)):
        if limit is not None and y0 <= limit <= y1:
            yy = sy(limit)
            p.append(
                f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l + pw}" y2="{yy:.1f}" '
                f'stroke="{color}" stroke-width="0.8" stroke-dasharray="4,2"/>'
            )

    # x date ticks
    zone = _zone(tz)
    for frac in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        epoch = x0 + frac * xr
        xx = sx(epoch)
        label = datetime.fromtimestamp(epoch, zone).strftime("%d.%m.")
        p.append(
            f'<text x="{xx:.1f}" y="{plot_bot + 9}" font-size="5.8" text-anchor="middle" '
            f'fill="#9ca3af">{label}</text>'
        )

    # series polylines (break at gaps)
    for s in series:
        d: list[str] = []
        pen = False
        for x, v in s.points:
            if v is None:
                pen = False
                continue
            d.append(f"{'L' if pen else 'M'}{sx(x):.1f},{sy(v):.1f}")
            pen = True
        if d:
            p.append(
                f'<path d="{" ".join(d)}" fill="none" stroke="{s.color}" '
                f'stroke-width="0.9" stroke-linejoin="round"/>'
            )

    # legend row
    if legend:
        lx = pad_l
        ly = plot_bot + pad_b + 6
        items: list[tuple[str, str, bool]] = [(s.color, s.name, False) for s in series]
        if chart.upper_limit_c is not None:
            items.append((_UPPER, upper_label, True))
        if chart.lower_limit_c is not None:
            items.append((_LOWER, lower_label, True))
        for color, name, dashed in items:
            dash = ' stroke-dasharray="3,2"' if dashed else ""
            p.append(
                f'<line x1="{lx}" y1="{ly:.1f}" x2="{lx + 10}" y2="{ly:.1f}" '
                f'stroke="{color}" stroke-width="1.1"{dash}/>'
            )
            txt = _esc(name)
            p.append(
                f'<text x="{lx + 13}" y="{ly + 2.2:.1f}" font-size="6" fill="#4b5563">{txt}</text>'
            )
            lx += 16 + len(name) * 3.1 + 8

    p.append("</svg>")
    return "".join(p)


def render_mini_svg(series: ChartSeries, tz: str, *, width: int = 320, plot_h: int = 80) -> str:
    chart = OverviewChart(
        group_key="mini",
        label="",
        series=[series],
        lower_limit_c=series.lower_limit_c,
        upper_limit_c=series.upper_limit_c,
        bands=series.bands,
    )
    return render_chart_svg(chart, tz, width=width, plot_h=plot_h, legend=False)
