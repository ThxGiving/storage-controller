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


def test_entity_last_seen_prefers_newest_timestamp():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.status_logic import entity_last_seen, stale_after_seconds

    t = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    e = SimpleNamespace(last_changed=t, last_updated=t.replace(minute=5),
                        last_reported=t.replace(minute=30))
    assert entity_last_seen(e) == t.replace(minute=30)
    assert entity_last_seen(SimpleNamespace(last_changed=None, last_updated=t)) == t
    assert entity_last_seen(SimpleNamespace()) is None
    assert stale_after_seconds(600) == 45 * 60
    assert stale_after_seconds(7200) == 7200


def test_parse_link_timestamp_formats():
    from datetime import UTC, datetime

    from app.status_logic import parse_link_timestamp

    t = datetime(2026, 10, 20, 17, 36, 28, tzinfo=UTC)
    assert parse_link_timestamp("2026-10-20T19:36:28+0200") == t  # ESPHome strftime %z
    assert parse_link_timestamp("2026-10-20T19:36:28+02:00") == t
    assert parse_link_timestamp("2026-10-20T17:36:28Z") == t
    for bad in (None, "", "on", "-20.2", "unavailable", "garbage", "2026-13-40T00:00:00Z"):
        assert parse_link_timestamp(bad) is None


def test_link_connected_binary_and_timestamp():
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.status_logic import link_connected

    now = datetime(2026, 10, 20, 17, 36, 28, tzinfo=UTC)
    plain = SimpleNamespace(invert_state=False, value_mapping_json=None)

    def up(state, assignment=plain):
        return link_connected(SimpleNamespace(state=state), assignment, now=now,
                              max_age_seconds=600)

    assert up("on") is True
    assert up("off") is False
    assert up("unavailable") is False
    assert up("unknown") is False
    assert up("off", SimpleNamespace(invert_state=True, value_mapping_json=None)) is True
    assert up((now - timedelta(seconds=30)).isoformat()) is True
    assert up((now - timedelta(minutes=11)).isoformat()) is False
    assert up("not a time") is False
    assert link_connected(None, plain, now=now, max_age_seconds=600) is False


def test_room_is_stale_follows_link():
    from datetime import UTC, datetime, timedelta

    from app.status_logic import room_is_stale

    now = datetime(2026, 10, 20, 17, 36, 28, tzinfo=UTC)
    base = dict(connected=True, quality="valid", last_seen=now - timedelta(minutes=55),
                now=now, offline_delay_seconds=600)
    assert room_is_stale(**base, link_up=None) is True  # no link entity: 45-min rule
    assert room_is_stale(**base, link_up=True) is False  # gateway still polling
    assert room_is_stale(**base, link_up=False) is False  # reported as unavailable instead
    base["last_seen"] = now - timedelta(minutes=30)
    assert room_is_stale(**base, link_up=None) is False
