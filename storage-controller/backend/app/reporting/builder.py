"""Assemble the immutable :class:`ReportModel` from recorded data (Phase 5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..learning_service import get_active_model
from ..models import REPORT_MODEL_VERSION, ReportBrandingSettings, StorageUnit
from ..settings_store import get_collector_settings, get_timezone_name
from ..timezone import resolve_timezone
from .labels import labels, month_name
from .metrics import (
    chart_group_for,
    defrost_ranges,
    defrost_summary,
    incident_summaries,
    month_range_utc,
    sample_metrics,
)
from .model import (
    BrandingSnapshot,
    ChartBand,
    ChartSeries,
    FlatIncident,
    OverviewChart,
    ReportModel,
    ReportSummary,
    ThresholdSnapshot,
    UnitReport,
)

# Per-unit series colors (cycled).
_PALETTE = ["#2563eb", "#16a34a", "#7c3aed", "#0891b2", "#db2777", "#ca8a04", "#0f766e"]
_ACCENT = {"ok": "#16a34a", "reviewed": "#2563eb", "attention": "#ea580c"}

_UNIT_TYPE_LABEL: dict[str, dict[str, str]] = {
    "day_cold_room": {"en": "Day cold room", "de": "Tageskühlhaus"},
    "freezer_room": {"en": "Freezer room", "de": "TK-Kühlhaus"},
    "vegetable_cold_room": {"en": "Vegetable cold room", "de": "Gemüsekühlhaus"},
    "beverage_cold_room": {"en": "Beverage cold room", "de": "Getränkekühlhaus"},
    "refrigerator": {"en": "Refrigerator", "de": "Kühlschrank"},
    "freezer": {"en": "Freezer", "de": "Gefrierschrank"},
    "refrigerated_counter": {"en": "Refrigerated counter", "de": "Kühltheke"},
    "custom": {"en": "Storage unit", "de": "Lagereinheit"},
}


def _parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None

_GROUP_LABEL = {
    "chilled": {"en": "Chilled units", "de": "Kühlbereiche"},
    "frozen": {"en": "Frozen units", "de": "Tiefkühlbereiche"},
}


def branding_snapshot(b: ReportBrandingSettings | None) -> BrandingSnapshot:
    if b is None:
        return BrandingSnapshot(report_title="HACCP Temperature Report")
    labels: list[str] = []
    if b.signature_labels_json:
        try:
            parsed = json.loads(b.signature_labels_json)
            if isinstance(parsed, list):
                labels = [str(x) for x in parsed]
        except (ValueError, TypeError):
            labels = []
    return BrandingSnapshot(
        organization_name=b.organization_name,
        site_name=b.site_name,
        address=b.address,
        contact=b.contact,
        logo_filename=b.logo_filename,
        report_title=b.report_title or "HACCP Temperature Report",
        subtitle=b.subtitle,
        accent=b.accent,
        footer_text=b.footer_text,
        disclaimer=b.disclaimer,
        signature_labels=labels,
    )


async def build_report_model(
    session: AsyncSession,
    *,
    uuid: str,
    year: int,
    month: int,
    unit_ids: list[int],
    locale: str,
    timezone: str | None,
    detail_level: str,
    now: datetime | None = None,
) -> ReportModel:
    now = now or datetime.now(UTC)
    tz_name = timezone or await get_timezone_name(session)
    tz = resolve_timezone(tz_name, now)
    start_utc, end_utc = month_range_utc(year, month, tz_name)
    collector = await get_collector_settings(session)
    heartbeat = collector.heartbeat_interval_seconds

    branding = await session.get(ReportBrandingSettings, 1)
    brand_snapshot = branding_snapshot(branding)
    # Localize the default report title when no custom title is configured.
    if branding is None or not branding.report_title:
        brand_snapshot.report_title = labels(locale)["report_title_default"]

    units_out: list[UnitReport] = []
    flat: list[FlatIncident] = []
    color_i = 0
    for uid in unit_ids:
        unit = await session.scalar(
            select(StorageUnit)
            .where(StorageUnit.id == uid)
            .options(selectinload(StorageUnit.assignments))
        )
        if unit is None:
            continue
        sm = await sample_metrics(
            session,
            storage_unit_id=uid,
            start_utc=start_utc,
            end_utc=end_utc,
            lower=unit.lower_limit_c,
            upper=unit.upper_limit_c,
            heartbeat_seconds=heartbeat,
        )
        incidents = await incident_summaries(
            session, storage_unit_id=uid, start_utc=start_utc, end_utc=end_utc
        )
        approved = await get_active_model(session, uid)
        defrost = await defrost_summary(
            session, storage_unit_id=uid, start_utc=start_utc, end_utc=end_utc,
            has_approved_model=approved is not None,
        )
        d_ranges = await defrost_ranges(
            session, storage_unit_id=uid, start_utc=start_utc, end_utc=end_utc
        )

        total_inc = sum(i.duration_seconds for i in incidents)
        longest = max((i.duration_seconds for i in incidents), default=0)
        extreme = None
        for i in incidents:
            if i.extreme_value_c is not None and (
                extreme is None or abs(i.extreme_value_c) > abs(extreme)
            ):
                extreme = i.extreme_value_c

        open_states = {"pending_violation", "active_violation", "recovering"}
        has_open = any(i.state in open_states for i in incidents)
        all_doc = incidents and all(i.documented for i in incidents)
        if has_open or (incidents and not all_doc):
            status = "attention"
        elif incidents:
            status = "reviewed"
        else:
            status = "ok"

        # Chart bands: deviations (incidents), data gaps, defrost periods.
        bands: list[ChartBand] = []
        for i in incidents:
            st, en = _parse_iso(i.opened_at), _parse_iso(i.closed_at) or end_utc.timestamp()
            if st is not None:
                bands.append(ChartBand(kind="deviation", start=st, end=en))
        for gs, ge in sm.gap_ranges:
            bands.append(ChartBand(kind="gap", start=gs, end=ge))
        for ds, de in d_ranges:
            bands.append(ChartBand(kind="defrost", start=ds, end=de))

        color = _PALETTE[color_i % len(_PALETTE)]
        color_i += 1
        group = chart_group_for(unit)
        chart = ChartSeries(
            unit_id=uid,
            name=unit.short_report_name or unit.name,
            color=color,
            points=sm.chart_points,
            lower_limit_c=unit.lower_limit_c,
            upper_limit_c=unit.upper_limit_c,
            bands=bands,
        )
        type_label = unit.applied_profile_name or _UNIT_TYPE_LABEL.get(unit.unit_type, {}).get(
            locale, unit.unit_type
        )
        units_out.append(
            UnitReport(
                id=uid, name=unit.name, short_name=unit.short_report_name,
                unit_type=unit.unit_type, type_label=type_label,
                profile_name=unit.applied_profile_name, chart_group=group,
                status=status, accent=_ACCENT[status],
                thresholds=ThresholdSnapshot(
                    lower_limit_c=unit.lower_limit_c, upper_limit_c=unit.upper_limit_c,
                    warning_margin_c=unit.warning_margin_c,
                ),
                min_c=sm.min_c, max_c=sm.max_c, avg_c=sm.avg_c,
                time_above_seconds=sm.time_above_seconds,
                time_below_seconds=sm.time_below_seconds,
                outside_seconds=sm.time_above_seconds + sm.time_below_seconds,
                incident_count=len(incidents), total_incident_seconds=total_inc,
                longest_incident_seconds=longest, incident_extreme_c=extreme,
                data_quality=sm.data_quality, defrost=defrost, incidents=incidents,
                chart=chart,
            )
        )
        for i in incidents:
            flat.append(
                FlatIncident(
                    n=0, unit_name=unit.name, opened_at=i.opened_at,
                    duration_seconds=i.duration_seconds, extreme_value_c=i.extreme_value_c,
                    cause=i.cause, corrective_action=i.corrective_action, state=i.state,
                    documented=i.documented,
                )
            )

    flat.sort(key=lambda f: f.opened_at)
    for idx, f in enumerate(flat, 1):
        f.n = idx

    overview = _overview_charts(units_out, locale)
    coverages = [
        u.data_quality.coverage_percent
        for u in units_out
        if u.data_quality.coverage_percent is not None
    ]
    overall_cov = round(sum(coverages) / len(coverages), 1) if coverages else None
    with_inc = sum(1 for u in units_out if u.incident_count > 0)
    incomplete = any(u.data_quality.incomplete or u.data_quality.missing_entity for u in units_out)
    _open = {"pending_violation", "active_violation", "recovering"}
    open_inc = sum(1 for f in flat if f.state in _open)
    confirmed = sum(1 for f in flat if f.documented)
    if incomplete:
        status = "incomplete"
        verdict = "incomplete"
    elif open_inc:
        status = "attention"
        verdict = "open"
    elif flat:
        status = "attention"
        verdict = "documented"
    else:
        status = "ok"
        verdict = "ok"

    L = labels(locale)
    dq_ok = not incomplete
    dq_note = L["dq_ok"] if dq_ok else L["dq_incomplete"]

    # Period range label: 01.05.2026 00:00 – 31.05.2026 23:59 (last minute of month)
    zone = ZoneInfo(tz_name) if _safe_zone(tz_name) else ZoneInfo("UTC")
    s_local = start_utc.astimezone(zone)
    e_local = (end_utc - timedelta(minutes=1)).astimezone(zone)
    range_label = (
        f"{s_local.strftime('%d.%m.%Y %H:%M')} – {e_local.strftime('%d.%m.%Y %H:%M')}"
    )

    return ReportModel(
        version=REPORT_MODEL_VERSION,
        uuid=uuid,
        generated_at=now.isoformat(),
        locale=locale,
        timezone=tz_name,
        timezone_label=tz.label,
        period_year=year,
        period_month=month,
        period_label=f"{month_name(month, locale)} {year}",
        period_start_utc=start_utc.isoformat(),
        period_end_utc=end_utc.isoformat(),
        period_range_label=range_label,
        detail_level=detail_level,
        branding=brand_snapshot,
        summary=ReportSummary(
            total_units=len(units_out),
            monitored_count=len(units_out),
            units_with_incidents=with_inc,
            total_incidents=len(flat),
            confirmed_deviations=confirmed,
            open_incidents=open_inc,
            overall_status=status,
            verdict=verdict,
            coverage_percent=overall_cov,
        ),
        units=units_out,
        overview_charts=overview,
        incidents_flat=flat,
        data_quality_ok=dq_ok,
        data_quality_note=dq_note,
    )


def _safe_zone(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:  # noqa: BLE001
        return False


def _overview_charts(units: list[UnitReport], locale: str) -> list[OverviewChart]:
    groups: dict[str, list[UnitReport]] = {}
    for u in units:
        groups.setdefault(u.chart_group, []).append(u)
    charts: list[OverviewChart] = []
    # Stable, compact ordering; at most two overview charts on page 1.
    L = labels(locale)
    group_label = {"chilled": L["chilled_group"], "frozen": L["frozen_group"]}
    for key in sorted(groups, key=lambda k: (k != "chilled", k != "frozen", k)):
        members = groups[key]
        label = group_label.get(key) or _GROUP_LABEL.get(key, {}).get(locale) or key
        lowers = [
            u.thresholds.lower_limit_c for u in members if u.thresholds.lower_limit_c is not None
        ]
        uppers = [
            u.thresholds.upper_limit_c for u in members if u.thresholds.upper_limit_c is not None
        ]
        charts.append(
            OverviewChart(
                group_key=key,
                label=label,
                series=[u.chart for u in members if u.chart is not None],
                lower_limit_c=min(lowers) if lowers else None,
                upper_limit_c=max(uppers) if uppers else None,
            )
        )
    return charts[:2]
