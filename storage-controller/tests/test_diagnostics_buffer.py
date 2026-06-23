"""Structured diagnostics buffer: redaction, expiry, bounded ring buffer, filters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app import diagnostics as diag
from app.diagnostics import DiagnosticsRecorder, redact


def test_redaction_of_secrets():
    out = redact(
        {
            "SUPERVISOR_TOKEN": "abc123",
            "Authorization": "Bearer xyz",
            "Cookie": "session=foo",
            "smtp_password": "hunter2",
            "api_key": "k-1",
            "private_key": "-----BEGIN-----",
            "nested": {"session_id": "s1", "ok": "visible"},
            "note": "token=deadbeef should vanish and bearer ABCDEF too",
        }
    )
    assert out["SUPERVISOR_TOKEN"] == "«redacted»"
    assert out["Authorization"] == "«redacted»"
    assert out["Cookie"] == "«redacted»"
    assert out["smtp_password"] == "«redacted»"
    assert out["api_key"] == "«redacted»"
    assert out["private_key"] == "«redacted»"
    assert out["nested"]["session_id"] == "«redacted»"
    assert out["nested"]["ok"] == "visible"
    assert "deadbeef" not in out["note"] and "ABCDEF" not in out["note"]


def test_mode_gates_logging_and_disabled_by_default():
    rec = DiagnosticsRecorder()
    assert rec.mode_status().enabled is False
    rec.log("info", "x", "should be dropped")
    assert rec.mode_status().buffered_logs == 0

    rec.enable_mode(minutes=30, user="admin")
    assert rec.mode_active() is True
    rec.log("info", "collector", "kept")
    assert rec.mode_status().buffered_logs == 1


def test_mode_auto_expires():
    rec = DiagnosticsRecorder()
    rec.enable_mode(minutes=30)
    rec._mode_expires = datetime.now(UTC) - timedelta(seconds=1)  # force expiry
    assert rec.mode_active() is False
    rec.log("info", "c", "after expiry")
    assert rec.mode_status().buffered_logs == 0


def test_ring_buffer_hard_cap():
    rec = DiagnosticsRecorder()
    rec.enable_mode()
    for i in range(1200):
        rec.log("info", "c", f"m{i}")
    # Hard maximum 1000 buffered entries; oldest discarded.
    assert rec.mode_status().buffered_logs == 1000
    # Returned entries are capped at 200.
    assert len(rec.query_logs(limit=999)) == 200


def test_log_filters():
    rec = DiagnosticsRecorder()
    rec.enable_mode()
    rec.log("info", "collector", "a", storage_unit_id=1, entity_id="e1")
    rec.log("warning", "defrost_engine", "b", storage_unit_id=2, entity_id="e2")
    assert len(rec.query_logs(component="collector")) == 1
    assert len(rec.query_logs(storage_unit_id=2)) == 1
    assert len(rec.query_logs(entity_id="e1")) == 1
    # severity is a minimum threshold
    assert len(rec.query_logs(severity="warning")) == 1


def test_event_trace_result_codes_exist():
    # The full Phase 4.7 result vocabulary is present.
    for code in [
        "stored", "reconciled_on_reconnect", "duplicate_ignored", "out_of_order_event",
        "normalization_failed", "mapping_missing", "storage_unit_missing",
        "cycle_started", "cycle_ended", "engine_not_invoked", "persist_failed",
    ]:
        assert isinstance(code, str)
    assert diag.RECONCILED_ON_RECONNECT == "reconciled_on_reconnect"
    assert diag.OUT_OF_ORDER_EVENT == "out_of_order_event"
