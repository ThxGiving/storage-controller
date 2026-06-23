"""Assemble the immutable :class:`ReportModel` from recorded data (Phase 5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

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
    defrost_summary,
    incident_summaries,
    month_range_utc,
    sample_metrics,
)
from .model import (
    BrandingSnapshot,
    ChartSeries,
    OverviewChart,
    ReportModel,
    ReportSummary,
    ThresholdSnapshot,
    UnitReport,
)

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
            session,
            storage_unit_id=uid,
            start_utc=start_utc,
            end_utc=end_utc,
            has_approved_model=approved is not None,
        )

        total_inc = sum(i.duration_seconds for i in incidents)
        longest = max((i.duration_seconds for i in incidents), default=0)
        extreme = None
        for i in incidents:
            if i.extreme_value_c is not None and (
                extreme is None or abs(i.extreme_value_c) > abs(extreme)
            ):
                extreme = i.extreme_value_c

        group = chart_group_for(unit)
        chart = ChartSeries(
            unit_id=uid,
            name=unit.short_report_name or unit.name,
            points=sm.chart_points,
            lower_limit_c=unit.lower_limit_c,
            upper_limit_c=unit.upper_limit_c,
        )
        units_out.append(
            UnitReport(
                id=uid,
                name=unit.name,
                short_name=unit.short_report_name,
                unit_type=unit.unit_type,
                profile_name=unit.applied_profile_name,
                chart_group=group,
                thresholds=ThresholdSnapshot(
                    lower_limit_c=unit.lower_limit_c,
                    upper_limit_c=unit.upper_limit_c,
                    warning_margin_c=unit.warning_margin_c,
                ),
                min_c=sm.min_c,
                max_c=sm.max_c,
                avg_c=sm.avg_c,
                time_above_seconds=sm.time_above_seconds,
                time_below_seconds=sm.time_below_seconds,
                incident_count=len(incidents),
                total_incident_seconds=total_inc,
                longest_incident_seconds=longest,
                incident_extreme_c=extreme,
                data_quality=sm.data_quality,
                defrost=defrost,
                incidents=incidents,
                chart=chart,
            )
        )

    overview = _overview_charts(units_out, locale)
    coverages = [
        u.data_quality.coverage_percent
        for u in units_out
        if u.data_quality.coverage_percent is not None
    ]
    overall_cov = round(sum(coverages) / len(coverages), 1) if coverages else None
    with_inc = sum(1 for u in units_out if u.incident_count > 0)
    incomplete = any(u.data_quality.incomplete or u.data_quality.missing_entity for u in units_out)
    status = "incomplete" if incomplete else ("attention" if with_inc else "ok")

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
        detail_level=detail_level,
        branding=brand_snapshot,
        summary=ReportSummary(
            total_units=len(units_out),
            units_with_incidents=with_inc,
            total_incidents=sum(u.incident_count for u in units_out),
            overall_status=status,
            coverage_percent=overall_cov,
        ),
        units=units_out,
        overview_charts=overview,
    )


def _overview_charts(units: list[UnitReport], locale: str) -> list[OverviewChart]:
    groups: dict[str, list[UnitReport]] = {}
    for u in units:
        groups.setdefault(u.chart_group, []).append(u)
    charts: list[OverviewChart] = []
    # Stable, compact ordering; at most two overview charts on page 1.
    for key in sorted(groups, key=lambda k: (k != "chilled", k != "frozen", k)):
        members = groups[key]
        label = _GROUP_LABEL.get(key, {}).get(locale) or _GROUP_LABEL.get(key, {}).get("en") or key
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
