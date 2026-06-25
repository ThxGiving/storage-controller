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

# Localized, restrained band fills. Missing data is rendered as a barely-there
# warm-gray hatch (almost invisible) so the temperature line dominates; measured
# violations and defrost stay as soft solids.
_BAND_FILL = {
    "deviation": "#fca5a5",
    "defrost": "#bfdbfe",
}
_BAND_OPACITY = {
    "deviation": 0.38,
    "defrost": 0.40,
}
_UPPER = "#dc2626"
_LOWER = "#2563eb"

# Merge threshold (seconds) per band kind. Bands of the same kind that are
# separated by less than this interval are merged before rendering, preventing
# the barcode effect that appears on dense monthly charts (e.g. many short
# defrost cycles or frequent brief gaps).
_MERGE_GAP: dict[str, float] = {
    "defrost": 7200.0,   # 2 h — handles up to ~12 cycles/day without barcode
    "gap": 3600.0,       # 1 h — short data outages close together
    "deviation": 1800.0, # 30 min — preserve violation shape more faithfully
}

# A very faint warm-gray hatch for missing-data regions — visually secondary,
# just enough texture to distinguish from normal data. The pattern id is made
# unique per chart so multiple charts on a page don't share the same <defs>.
def _gap_pattern(gid: str) -> str:
    return (
        f'<defs><pattern id="{gid}" width="8" height="8" patternUnits="userSpaceOnUse">'
        '<rect width="8" height="8" fill="#f8f7f4"/>'
        '<path d="M0,8 L8,0" stroke="#c8c4a0" stroke-width="0.5" stroke-opacity="0.35"/>'
        "</pattern></defs>"
    )


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _bounds(
    series: list[ChartSeries], lo: float | None, hi: float | None
) -> tuple[float, float, bool, bool]:
    """Compute y-axis display domain with P1/P99 outlier clipping.

    Returns ``(y0, y1, lo_clipped, hi_clipped)``.  lo/hi_clipped are True when
    actual data values exist beyond the displayed domain so the caller can draw
    outlier markers.  Safety limits (lo, hi) are always included in the domain,
    so isolated spikes beyond those limits are the only things that get clipped.
    """
    all_data: list[float] = []   # all avg/min/max envelope values
    avg_data: list[float] = []   # avg only, used for the percentile domain
    for s in series:
        for pt in s.points:
            for k in (1, 2, 3):
                if len(pt) > k and pt[k] is not None:
                    all_data.append(pt[k])
            if len(pt) > 1 and pt[1] is not None:
                avg_data.append(pt[1])

    if not all_data and lo is None and hi is None:
        return 0.0, 10.0, False, False

    # Compute the primary display range from the P1–P99 of the average line.
    # With ≥20 points this quietly clips isolated spikes (sensor errors, door
    # left open) while keeping recurring patterns (defrost peaks, slow warm-up)
    # fully visible.  With fewer points it falls back to the actual min/max.
    if len(avg_data) >= 20:
        sv = sorted(avg_data)
        n = len(sv)

        def _pct(p: float) -> float:
            idx = (n - 1) * p / 100.0
            i0 = int(idx)
            i1 = min(i0 + 1, n - 1)
            return sv[i0] + (idx - i0) * (sv[i1] - sv[i0])

        vmin, vmax = _pct(1.0), _pct(99.0)
    elif avg_data:
        vmin, vmax = min(avg_data), max(avg_data)
    else:
        vmin = lo if lo is not None else 0.0
        vmax = hi if hi is not None else 10.0

    # Safety limits are always visible — they define the compliance boundary.
    if lo is not None:
        vmin = min(vmin, lo)
    if hi is not None:
        vmax = max(vmax, hi)

    # Detect outliers that fall outside the display range.
    lo_clipped = bool(all_data and min(all_data) < vmin)
    hi_clipped = bool(all_data and max(all_data) > vmax)

    # Enforce a 4 °C minimum span, centered, so tight-limit units don't make
    # normal hysteresis oscillations look dramatic.
    if vmax - vmin < 4.0:
        mid = (vmin + vmax) / 2
        vmin = mid - 2.0
        vmax = mid + 2.0

    pad = (vmax - vmin) * 0.14
    return vmin - pad, vmax + pad, lo_clipped, hi_clipped


def _x_domain(series: list[ChartSeries]) -> tuple[float, float]:
    xs = [p[0] for s in series for p in s.points if p[0] is not None]
    if not xs:
        return 0.0, 1.0
    return min(xs), max(xs)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _simplify_bands(
    bands: list[ChartBand], x0: float, x1: float  # noqa: ARG001
) -> list[ChartBand]:
    """Merge same-kind bands that are closer than the kind-specific threshold.

    Prevents the barcode visual on dense monthly charts without losing the
    information that events occurred.  The report *model* is never modified;
    only the rendered representation is simplified.
    """
    if not bands:
        return bands

    by_kind: dict[str, list[ChartBand]] = {}
    for b in bands:
        by_kind.setdefault(b.kind, []).append(b)

    out: list[ChartBand] = []
    for kind, blist in by_kind.items():
        threshold = _MERGE_GAP.get(kind, 3600.0)
        slist = sorted(blist, key=lambda b: b.start)
        merged = [ChartBand(kind=kind, start=slist[0].start, end=slist[0].end)]
        for b in slist[1:]:
            last = merged[-1]
            if b.start - last.end <= threshold:
                merged[-1] = ChartBand(
                    kind=kind, start=last.start, end=max(last.end, b.end)
                )
            else:
                merged.append(ChartBand(kind=kind, start=b.start, end=b.end))
        out.extend(merged)
    return out


def render_chart_svg(
    chart: OverviewChart,
    tz: str,
    *,
    width: int = 700,
    plot_h: int = 132,
    legend: bool = True,
    upper_label: str = "Upper limit",
    lower_label: str = "Lower limit",
    x_start: float | None = None,
    x_end: float | None = None,
    note: str | None = None,
) -> str:
    series = [s for s in chart.series if s.points]
    pad_l, pad_r, pad_t, pad_b = 26, 6, 12, 14
    legend_h = 14 if legend else 0
    height = pad_t + plot_h + pad_b + legend_h
    pw = width - pad_l - pad_r
    # The x-axis ALWAYS spans the full reporting period (or the elapsed portion
    # for an interim report) so sparse data appears only at its real position.
    if x_start is not None and x_end is not None and x_end > x_start:
        x0, x1 = x_start, x_end
    else:
        x0, x1 = _x_domain(series)
    y0, y1, lo_clipped, hi_clipped = _bounds(
        series, chart.lower_limit_c, chart.upper_limit_c
    )
    xr = (x1 - x0) or 1.0
    yr = (y1 - y0) or 1.0
    plot_top = pad_t
    plot_bot = pad_t + plot_h

    def sx(x: float) -> float:
        return pad_l + (x - x0) / xr * pw

    def sy(v: float) -> float:
        return plot_top + (y1 - v) / yr * plot_h

    gid = f"scGap{abs(hash((id(chart), x0, y0))) % 1000000:06d}"
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="DejaVu Sans, Helvetica, sans-serif">',
        _gap_pattern(gid),
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        # White plot background so the temperature data dominates, not the shading.
        f'<rect x="{pad_l}" y="{plot_top}" width="{pw}" height="{plot_h}" fill="#ffffff"/>',
    ]

    # Merge dense same-kind bands before rendering to prevent barcode effect.
    all_bands = _simplify_bands(
        list(chart.bands) + [b for s in series for b in s.bands], x0, x1
    )

    # Shaded bands (behind the data).  Missing-data gaps use the subtle hatch;
    # measured violations / defrost use soft solids.
    for b in all_bands:
        bx0 = max(pad_l, sx(b.start))
        bx1 = min(pad_l + pw, sx(b.end))
        if bx1 <= bx0:
            bx1 = bx0 + 1.2  # keep instantaneous events visible as a thin stripe
        if b.kind == "gap":
            p.append(
                f'<rect x="{bx0:.1f}" y="{plot_top}" width="{bx1 - bx0:.1f}" '
                f'height="{plot_h}" fill="url(#{gid})"/>'
            )
            for bx in (bx0, bx1):
                p.append(
                    f'<line x1="{bx:.1f}" y1="{plot_top}" x2="{bx:.1f}" '
                    f'y2="{plot_bot}" stroke="#c8c4a0" stroke-width="0.4" '
                    f'stroke-opacity="0.45"/>'
                )
        else:
            p.append(
                f'<rect x="{bx0:.1f}" y="{plot_top}" width="{bx1 - bx0:.1f}" '
                f'height="{plot_h}" fill="{_BAND_FILL.get(b.kind, "#eee")}" '
                f'fill-opacity="{_BAND_OPACITY.get(b.kind, 0.38)}"/>'
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

    # Limit lines
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

    # Series: subtle min–max envelope + calm average line, broken at genuine gaps.
    # Both envelope and line are clamped to the display domain so no SVG element
    # ever exits the plot area when outliers exist.
    for s_idx, s in enumerate(series):
        seg: list[tuple[float, float, float, float]] = []
        segments: list[list[tuple[float, float, float, float]]] = []
        for pt in s.points:
            if len(pt) < 4 or pt[1] is None:
                if seg:
                    segments.append(seg)
                    seg = []
                continue
            seg.append((pt[0], pt[1], pt[2], pt[3]))
        if seg:
            segments.append(seg)

        for segment in segments:
            # Envelope polygon: forward along hi (clamped), back along lo (clamped).
            top = " ".join(
                f"{sx(x):.1f},{sy(min(hi, y1)):.1f}" for x, _a, _lo, hi in segment
            )
            bot = " ".join(
                f"{sx(x):.1f},{sy(max(lo, y0)):.1f}"
                for x, _a, lo, _hi in reversed(segment)
            )
            p.append(
                f'<polygon points="{top} {bot}" fill="{s.color}" fill-opacity="0.13" '
                f'stroke="none"/>'
            )
            # Average line, clamped so it never exits the plot boundary.
            avg = "".join(
                f"{'L' if i else 'M'}{sx(x):.1f},{sy(max(y0, min(y1, a))):.1f}"
                for i, (x, a, _lo, _hi) in enumerate(segment)
            )
            p.append(
                f'<path d="{avg}" fill="none" stroke="{s.color}" stroke-width="1.3" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )

        # Outlier markers: small triangles at the plot boundary when P1/P99
        # clipping excluded envelope extremes.  The true values are always
        # preserved in the report metrics table.
        all_hi = [hi for seg in segments for _x, _a, _lo, hi in seg if hi is not None]
        all_lo = [lo for seg in segments for _x, _a, lo, _hi in seg if lo is not None]
        # Stack markers for multiple series: offset by series index * 14px.
        x_off = pad_l + pw - 8 - s_idx * 14
        if all_hi and max(all_hi) > y1:
            oy = plot_top + 6
            p.append(
                f'<polygon points="{x_off:.1f},{oy - 4:.1f} {x_off - 3:.1f},{oy + 2:.1f} '
                f'{x_off + 3:.1f},{oy + 2:.1f}" fill="{s.color}" fill-opacity="0.75"/>'
            )
            p.append(
                f'<text x="{x_off - 5:.1f}" y="{oy - 5:.1f}" font-size="5" '
                f'text-anchor="end" fill="{s.color}">{max(all_hi):.1f}°</text>'
            )
        if all_lo and min(all_lo) < y0:
            oy = plot_bot - 6
            p.append(
                f'<polygon points="{x_off:.1f},{oy + 4:.1f} {x_off - 3:.1f},{oy - 2:.1f} '
                f'{x_off + 3:.1f},{oy - 2:.1f}" fill="{s.color}" fill-opacity="0.75"/>'
            )
            p.append(
                f'<text x="{x_off - 5:.1f}" y="{oy + 9:.1f}" font-size="5" '
                f'text-anchor="end" fill="{s.color}">{min(all_lo):.1f}°</text>'
            )

    # Sparse-data annotation (kept subtle, inside the plot)
    if note:
        p.append(
            f'<text x="{pad_l + 4}" y="{plot_top + 9}" font-size="6.4" '
            f'fill="#a16207">{_esc(note)}</text>'
        )

    # Legend row
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


def render_mini_svg(
    series: ChartSeries,
    tz: str,
    *,
    width: int = 320,
    plot_h: int = 80,
    x_start: float | None = None,
    x_end: float | None = None,
) -> str:
    chart = OverviewChart(
        group_key="mini",
        label="",
        series=[series],
        lower_limit_c=series.lower_limit_c,
        upper_limit_c=series.upper_limit_c,
        bands=series.bands,
    )
    return render_chart_svg(
        chart, tz, width=width, plot_h=plot_h, legend=False,
        x_start=x_start, x_end=x_end,
    )
