"""Report generation orchestration (Phase 5).

Builds the immutable model, renders PDF/CSV/JSON, and finalizes atomically under
``/data/reports/<uuid>/`` with a SHA-256 checksum. The DB record and file state are
kept consistent: a failed generation never leaves a report marked completed, and
temporary files are cleaned up.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Report, ReportStatus
from .builder import build_report_model
from .model import ReportModel
from .render import render_csv, render_json, render_pdf

log = logging.getLogger("reports")

PDF_NAME = "report.pdf"
CSV_NAME = "report.csv"
JSON_NAME = "report.json"


def reports_root() -> Path:
    return get_settings().data_dir / "reports"


def uploads_root() -> Path:
    return get_settings().data_dir / "uploads"


def report_dir(uuid: str) -> Path:
    return reports_root() / uuid


def _logo_path(model: ReportModel) -> Path | None:
    name = model.branding.logo_filename
    if not name:
        return None
    p = uploads_root() / name
    return p if p.is_file() else None


def _write_files(target: Path, pdf: bytes, csv_s: str, json_s: str) -> None:
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / PDF_NAME).write_bytes(pdf)
    (tmp / CSV_NAME).write_text(csv_s, encoding="utf-8")
    (tmp / JSON_NAME).write_text(json_s, encoding="utf-8")
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)


def _render_blocking(model: ReportModel, logo: Path | None) -> tuple[bytes, str, str]:
    """CPU-bound rendering; run in a worker thread so the event loop isn't blocked."""
    pdf = render_pdf(model, logo_path=logo)
    return pdf, render_csv(model), render_json(model)


async def generate(session: AsyncSession, report: Report) -> Report:
    """Generate ``report`` in place. Commits status transitions via the caller's
    session. Returns the (possibly failed) report — never raises for render errors."""
    started = datetime.now(UTC)
    report.status = ReportStatus.generating.value
    report.started_at = started
    await session.flush()

    try:
        unit_ids = _json_list(report.storage_unit_ids_json)
        model = await build_report_model(
            session,
            uuid=report.uuid,
            year=report.period_year,
            month=report.period_month,
            unit_ids=unit_ids,
            locale=report.locale,
            timezone=report.timezone,
            detail_level=report.detail_level,
        )
        pdf, csv_s, json_s = await asyncio.to_thread(_render_blocking, model, _logo_path(model))
        await asyncio.to_thread(_write_files, report_dir(report.uuid), pdf, csv_s, json_s)

        model_json = model.model_dump_json()
        report.model_json = model_json
        report.branding_snapshot_json = model.branding.model_dump_json()
        report.checksum_sha256 = hashlib.sha256(model_json.encode("utf-8")).hexdigest()
        report.pdf_filename = PDF_NAME
        report.csv_filename = CSV_NAME
        report.json_filename = JSON_NAME
        report.status = ReportStatus.completed.value
        finished = datetime.now(UTC)
        report.finished_at = finished
        report.generated_at = finished
        report.duration_ms = int((finished - started).total_seconds() * 1000)
        log.info("reports: generated %s (%s)", report.uuid, report.duration_ms)
    except Exception as exc:  # noqa: BLE001 — record sanitized failure, never crash
        shutil.rmtree(report_dir(report.uuid).with_name(report.uuid + ".tmp"), ignore_errors=True)
        report.status = ReportStatus.failed.value
        report.failure_category = type(exc).__name__
        report.error_message = "Report generation failed."  # sanitized, no stack/internals
        report.finished_at = datetime.now(UTC)
        log.warning("reports: generation failed for %s: %s", report.uuid, type(exc).__name__)
    await session.flush()
    return report


def _json_list(raw: str) -> list[int]:
    import json

    try:
        data = json.loads(raw)
        return [int(x) for x in data] if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def delete_report_files(uuid: str) -> None:
    shutil.rmtree(report_dir(uuid), ignore_errors=True)
