"""Safe normalization of Home Assistant states into samples.

Core safety rule: unknown / unavailable / invalid / NaN / missing values are
NEVER coerced to zero. They are stored with a quality flag and NULL numeric
values so the chart can render real gaps.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from .models import Quality

UNAVAILABLE_STATES = {"unavailable", "none", ""}
UNKNOWN_STATES = {"unknown"}

_TRUE_STATES = {"on", "true", "1", "open", "opened", "active", "home", "detected", "yes"}
_FALSE_STATES = {"off", "false", "0", "closed", "inactive", "idle", "away", "clear", "no"}


@dataclass(frozen=True)
class BoolMapping:
    """Per-entity active/inactive state vocabulary (e.g. a Dixell defrost coil
    that reports values other than on/off). Matching is case-insensitive and is
    tried before the built-in vocabulary."""

    active: frozenset[str] = field(default_factory=frozenset)
    inactive: frozenset[str] = field(default_factory=frozenset)
    invert: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.active or self.inactive)


def parse_bool_mapping(value_mapping_json: str | None) -> BoolMapping:
    """Parse the stored ``value_mapping_json`` into a :class:`BoolMapping`.

    Accepts ``{"active": [...], "inactive": [...], "invert": bool}``. Unknown or
    malformed JSON yields an empty (unconfigured) mapping — never raises.
    """
    if not value_mapping_json:
        return BoolMapping()
    try:
        data = json.loads(value_mapping_json)
    except (ValueError, TypeError):
        return BoolMapping()
    if not isinstance(data, dict):
        return BoolMapping()

    def _set(key: str) -> frozenset[str]:
        raw = data.get(key)
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return frozenset()
        return frozenset(str(v).strip().lower() for v in raw if str(v).strip())

    return BoolMapping(
        active=_set("active"),
        inactive=_set("inactive"),
        invert=bool(data.get("invert", False)),
    )

_FAHRENHEIT_UNITS = {"°f", "f", "fahrenheit"}
_CELSIUS_UNITS = {"°c", "c", "celsius"}


@dataclass(frozen=True)
class NumericResult:
    quality: Quality
    raw_value: str | None
    numeric_value: float | None  # value in the original unit
    normalized_value_c: float | None  # value converted to Celsius
    original_unit: str | None


@dataclass(frozen=True)
class BoolResult:
    quality: Quality
    raw_state: str | None
    normalized_bool: bool | None
    # Machine-readable explanation for diagnostics: ok | unavailable | unknown |
    # missing | unrecognized_state
    reason: str = "ok"


def fahrenheit_to_celsius(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


def normalize_numeric(
    raw_state: str | None,
    unit: str | None,
    *,
    plausible_min_c: float | None = None,
    plausible_max_c: float | None = None,
) -> NumericResult:
    raw = None if raw_state is None else str(raw_state)
    unit_norm = (unit or "").strip()
    low = (raw or "").strip().lower()

    if raw is None or low in UNAVAILABLE_STATES:
        return NumericResult(Quality.unavailable, raw, None, None, unit_norm or None)
    if low in UNKNOWN_STATES:
        return NumericResult(Quality.unknown, raw, None, None, unit_norm or None)

    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return NumericResult(Quality.invalid, raw, None, None, unit_norm or None)

    if math.isnan(numeric) or math.isinf(numeric):
        return NumericResult(Quality.invalid, raw, None, None, unit_norm or None)

    if unit_norm.lower() in _FAHRENHEIT_UNITS:
        normalized_c = fahrenheit_to_celsius(numeric)
    else:
        # Celsius or unknown unit: assume the value is already Celsius.
        normalized_c = numeric

    quality = Quality.valid
    if (
        (plausible_min_c is not None and normalized_c < plausible_min_c)
        or (plausible_max_c is not None and normalized_c > plausible_max_c)
    ):
        quality = Quality.implausible

    return NumericResult(quality, raw, numeric, normalized_c, unit_norm or None)


def normalize_bool(
    raw_state: str | None,
    *,
    invert: bool = False,
    mapping: BoolMapping | None = None,
) -> BoolResult:
    raw = None if raw_state is None else str(raw_state)
    low = (raw or "").strip().lower()

    if raw is None:
        return BoolResult(Quality.unavailable, raw, None, reason="missing")
    if low in UNAVAILABLE_STATES:
        return BoolResult(Quality.unavailable, raw, None, reason="unavailable")
    if low in UNKNOWN_STATES:
        return BoolResult(Quality.unknown, raw, None, reason="unknown")

    # A configured per-entity mapping wins over the built-in vocabulary, so a
    # controller exposing values other than on/off can still be normalized.
    if mapping is not None and mapping.configured:
        if low in mapping.active:
            value = True
        elif low in mapping.inactive:
            value = False
        elif low in _TRUE_STATES:
            value = True
        elif low in _FALSE_STATES:
            value = False
        else:
            return BoolResult(Quality.invalid, raw, None, reason="unrecognized_state")
        combined_invert = invert ^ mapping.invert
        if combined_invert:
            value = not value
        return BoolResult(Quality.valid, raw, value)

    if low in _TRUE_STATES:
        value = True
    elif low in _FALSE_STATES:
        value = False
    else:
        # Unrecognised operational state — keep the raw text, no boolean guess.
        return BoolResult(Quality.invalid, raw, None, reason="unrecognized_state")

    if invert:
        value = not value
    return BoolResult(Quality.valid, raw, value)
