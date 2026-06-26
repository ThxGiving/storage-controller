"""Brand accent color utilities.

Derives a complete set of display tokens from a single canonical #RRGGBB value.
Only the base color is persisted; all derived tokens are computed at render time.
"""

from __future__ import annotations

import re

DEFAULT_ACCENT = "#1E3A5F"
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_accent(color: str | None) -> str:
    """Return canonical #RRGGBB (upper) or DEFAULT_ACCENT if absent/invalid."""
    if not color:
        return DEFAULT_ACCENT
    c = color.strip()
    if not _HEX_RE.match(c):
        return DEFAULT_ACCENT
    return "#" + c[1:].upper()


def validate_accent(color: str) -> bool:
    """True iff color is a syntactically valid #RRGGBB hex string."""
    return bool(_HEX_RE.match(color.strip()))


def _lin(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(r: int, g: int, b: int) -> float:
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(lum_a: float, lum_b: float) -> float:
    hi, lo = (lum_a, lum_b) if lum_a > lum_b else (lum_b, lum_a)
    return (hi + 0.05) / (lo + 0.05)


def accent_tokens(accent: str) -> dict:
    """Derive a full set of display tokens from a canonical brand accent hex.

    Keys
    ----
    base             The normalized accent itself.
    fg               Primary text on accent background (#fff or #111827).
    secondary_fg     Muted/secondary text on accent background.
    subtle_bg        Very light tint (12 % accent over white).
    border           Medium tint (35 % accent over white) for borders.
    dark             20 % darkened accent for hover / emphasis text.
    light            45 % accent blended with white for fills.
    low_contrast_warning
                     True when WCAG contrast ratio < 4.5 — warn in settings UI.
    """
    a = normalize_accent(accent)
    r, g, b = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    lum = _luminance(r, g, b)

    fg = "#ffffff" if lum < 0.35 else "#111827"

    if lum < 0.35:
        sfr = int(r + (255 - r) * 0.60)
        sfg = int(g + (255 - g) * 0.60)
        sfb = int(b + (255 - b) * 0.60)
    else:
        sfr = int(r * 0.55)
        sfg = int(g * 0.55)
        sfb = int(b * 0.55)
    secondary_fg = f"#{sfr:02x}{sfg:02x}{sfb:02x}"

    def _mix(c: int, w: float) -> str:
        return f"{int(c * w + 255 * (1 - w)):02x}"

    subtle_bg = f"#{_mix(r, 0.12)}{_mix(g, 0.12)}{_mix(b, 0.12)}"
    border = f"#{_mix(r, 0.35)}{_mix(g, 0.35)}{_mix(b, 0.35)}"
    dark = f"#{int(r * 0.80):02x}{int(g * 0.80):02x}{int(b * 0.80):02x}"
    light = f"#{_mix(r, 0.45)}{_mix(g, 0.45)}{_mix(b, 0.45)}"

    fg_lum = 1.0 if fg == "#ffffff" else _luminance(17, 24, 39)
    low_contrast_warning = _contrast(lum, fg_lum) < 4.5

    return {
        "base": a,
        "fg": fg,
        "secondary_fg": secondary_fg,
        "subtle_bg": subtle_bg,
        "border": border,
        "dark": dark,
        "light": light,
        "low_contrast_warning": low_contrast_warning,
    }
