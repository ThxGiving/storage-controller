from __future__ import annotations

from app.status_logic import (
    STATUS_CONFIG_ERROR,
    STATUS_DISCONNECTED,
    STATUS_NEAR_LIMIT,
    STATUS_NORMAL,
    STATUS_OUTSIDE_RANGE,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    compute_status,
)


def _status(**over):
    base = dict(
        connected=True,
        has_room_assignment=True,
        room_exists=True,
        quality="valid",
        normalized_c=5.0,
        lower_limit_c=0.0,
        upper_limit_c=8.0,
        warning_margin_c=0.5,
        is_stale=False,
    )
    base.update(over)
    return compute_status(**base)


def test_normal():
    assert _status(normalized_c=5.0) == STATUS_NORMAL


def test_outside_range_high():
    assert _status(normalized_c=8.5) == STATUS_OUTSIDE_RANGE


def test_outside_range_low():
    assert _status(normalized_c=-1.0) == STATUS_OUTSIDE_RANGE


def test_near_limit_upper():
    assert _status(normalized_c=7.7) == STATUS_NEAR_LIMIT


def test_near_limit_lower():
    assert _status(normalized_c=0.3) == STATUS_NEAR_LIMIT


def test_configuration_error_without_room_assignment():
    assert _status(has_room_assignment=False) == STATUS_CONFIG_ERROR


def test_configuration_error_when_entity_missing():
    assert _status(room_exists=False) == STATUS_CONFIG_ERROR


def test_disconnected():
    assert _status(connected=False) == STATUS_DISCONNECTED


def test_unavailable_quality():
    assert _status(quality="unavailable", normalized_c=None) == STATUS_UNAVAILABLE


def test_stale():
    assert _status(is_stale=True) == STATUS_STALE


def test_disconnected_takes_priority_over_range():
    assert _status(connected=False, normalized_c=99.0) == STATUS_DISCONNECTED
