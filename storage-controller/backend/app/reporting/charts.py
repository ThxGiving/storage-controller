"""Server-side SVG charts for reports (Phase 5).

Pure-Python vector SVG — no browser, no dashboard state. Print-readable with a
grayscale-friendly dash vocabulary, explicit °C units, configured safety-limit
lines, and visible gaps (missing periods are breaks, never interpolated).
"""

from __future__ import annotations

from datetime import UTC, datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from .model import ChartSeries, OverviewChart

# Grayscale-distinct stroke styles cycled per series.
_STROKES = [
    ("#1f2937", "none"),
    ("#374151", "5,3"),
    ("#4b5563", "2,2"),
    ("#6b7280", "7,2,2,2"),
]


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _series_bounds(series: list[ChartSeries], lo: float | None, hi: float | None):
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
    if vmax - vmin < 1.0:
        vmin -= 1.0
        vmax += 1.0
    pad = (vmax - vmin) * 0.12
    return vmin - pad, vmax + pad


def _x_domain(series: list[ChartSeries]) -> tuple[float, float]:
    xs = [p[0] for s in series for p in s.points if p[0] is not None]
    if not xs:
        now = datetime.now(UTC).timestamp()
        return now, now + 1
    return min(xs), max(xs)


def render_chart_svg(
    chart: OverviewChart,
    tz: str,
    *,
    width: int = 520,
    height: int = 150,
) -> str:
    series = [s for s in chart.series if s.points]
    pad_l, pad_r, pad_t, pad_b = 30, 8, 8, 18
    pw = width - pad_l - pad_r
    ph = height - pad_t - pad_b
    x0, x1 = _x_domain(series)
    y0, y1 = _series_bounds(series, chart.lower_limit_c, chart.upper_limit_c)
    xr = (x1 - x0) or 1.0
    yr = (y1 - y0) or 1.0

    def sx(x: float) -> float:
        return pad_l + (x - x0) / xr * pw

    def sy(v: float) -> float:
        return pad_t + (y1 - v) / yr * ph

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="DejaVu Sans, sans-serif">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<rect x="{pad_l}" y="{pad_t}" width="{pw}" height="{ph}" fill="#fafafa" '
        f'stroke="#e5e7eb" stroke-width="0.5"/>',
    ]

    # y gridlines + labels
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = y1 - frac * (y1 - y0)
        yy = sy(v)
        parts.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l + pw}" y2="{yy:.1f}" '
            f'stroke="#eee" stroke-width="0.5"/>'
        )
        parts.append(
            f'<text x="{pad_l - 3}" y="{yy + 2.5:.1f}" font-size="6" text-anchor="end" '
            f'fill="#6b7280">{v:.0f}</text>'
        )

    # limit lines
    for limit, dash, color in (
        (chart.upper_limit_c, "3,2", "#b91c1c"),
        (chart.lower_limit_c, "3,2", "#1d4ed8"),
    ):
        if limit is not None and y0 <= limit <= y1:
            yy = sy(limit)
            parts.append(
                f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{pad_l + pw}" y2="{yy:.1f}" '
                f'stroke="{color}" stroke-width="0.8" stroke-dasharray="{dash}"/>'
            )

    # x ticks (day-of-month in report tz)
    zone = _zone(tz)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        epoch = x0 + frac * xr
        xx = sx(epoch)
        day = datetime.fromtimestamp(epoch, zone).day
        parts.append(
            f'<text x="{xx:.1f}" y="{height - 6}" font-size="6" text-anchor="middle" '
            f'fill="#6b7280">{day}</text>'
        )

    # series polylines, breaking at gaps
    for i, s in enumerate(series):
        color, dash = _STROKES[i % len(_STROKES)]
        d: list[str] = []
        pen_down = False
        for x, v in s.points:
            if v is None:
                pen_down = False
                continue
            cmd = "L" if pen_down else "M"
            d.append(f"{cmd}{sx(x):.1f},{sy(v):.1f}")
            pen_down = True
        if d:
            parts.append(
                f'<path d="{" ".join(d)}" fill="none" stroke="{color}" '
                f'stroke-width="0.9" stroke-dasharray="{dash}"/>'
            )

    parts.append("</svg>")
    return "".join(parts)


def render_mini_svg(series: ChartSeries, tz: str, *, width: int = 230, height: int = 70) -> str:
    chart = OverviewChart(
        group_key="mini",
        label=escape(series.name),
        series=[series],
        lower_limit_c=series.lower_limit_c,
        upper_limit_c=series.upper_limit_c,
    )
    return render_chart_svg(chart, tz, width=width, height=height)
