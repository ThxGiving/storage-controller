from __future__ import annotations

import math

from app.models import Quality
from app.normalization import fahrenheit_to_celsius, normalize_bool, normalize_numeric


def test_celsius_passthrough():
    r = normalize_numeric("5.90000009536743", "°C")
    assert r.quality == Quality.valid
    assert r.numeric_value == 5.90000009536743
    assert abs(r.normalized_value_c - 5.9) < 1e-6
    assert r.original_unit == "°C"


def test_fahrenheit_conversion():
    r = normalize_numeric("41", "°F")
    assert r.quality == Quality.valid
    assert abs(r.normalized_value_c - 5.0) < 1e-9
    assert r.numeric_value == 41.0
    assert r.original_unit == "°F"
    assert abs(fahrenheit_to_celsius(32) - 0.0) < 1e-9


def test_unavailable_not_zeroed():
    for state in ("unavailable", "none", ""):
        r = normalize_numeric(state, "°C")
        assert r.quality == Quality.unavailable
        assert r.numeric_value is None
        assert r.normalized_value_c is None


def test_unknown_state():
    r = normalize_numeric("unknown", "°C")
    assert r.quality == Quality.unknown
    assert r.normalized_value_c is None


def test_invalid_non_numeric():
    r = normalize_numeric("warm", "°C")
    assert r.quality == Quality.invalid
    assert r.numeric_value is None


def test_nan_and_inf_invalid():
    assert normalize_numeric("nan", "°C").quality == Quality.invalid
    assert normalize_numeric(str(math.inf), "°C").quality == Quality.invalid


def test_implausible_outside_plausible_range():
    r = normalize_numeric("80", "°C", plausible_min_c=-30, plausible_max_c=30)
    assert r.quality == Quality.implausible
    assert r.normalized_value_c == 80.0  # value still preserved, not dropped


def test_bool_on_off():
    assert normalize_bool("on").normalized_bool is True
    assert normalize_bool("off").normalized_bool is False
    assert normalize_bool("ON").normalized_bool is True


def test_bool_invert():
    r = normalize_bool("on", invert=True)
    assert r.normalized_bool is False
    assert r.quality == Quality.valid


def test_bool_unavailable_not_false():
    r = normalize_bool("unavailable")
    assert r.quality == Quality.unavailable
    assert r.normalized_bool is None  # never coerced to False


def test_bool_unknown_text_invalid():
    r = normalize_bool("heating")
    assert r.quality == Quality.invalid
    assert r.normalized_bool is None
