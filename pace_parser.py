"""
Human-friendly pace input parsing for run workouts.

COROS stores pace intensity as milliseconds per kilometer in
``intensity_value`` / ``intensity_value_extend``, with ``intensity_type=3``
and ``intensity_display_unit=2`` (km). Agents shouldn't have to know that.

This module accepts human strings like ``"4:05/km"`` or ``"5:30-5:45/mi"``
and emits the raw COROS intensity fields.
"""
from __future__ import annotations

import re
from typing import Any

_METERS_PER_MILE = 1609.344

# Examples matched:
#   "4:05/km"            → single-value km pace
#   "4:05-4:15 /km"      → km pace range (whitespace and slash optional)
#   "5:30-5:45/mi"       → mile pace range (converted to ms/km)
#   "4:05.5/km"          → fractional seconds allowed
_PACE_RE = re.compile(
    r"""
    ^\s*
    (?P<min1>\d+):(?P<sec1>\d{1,2}(?:\.\d+)?)
    (?:\s*[-–]\s*(?P<min2>\d+):(?P<sec2>\d{1,2}(?:\.\d+)?))?
    \s*/?\s*
    (?P<unit>km|kilometer|kilometers|k|mi|mile|miles|m(?:ile)?)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_MI_UNITS = {"mi", "mile", "miles"}
_KM_UNITS = {"km", "kilometer", "kilometers", "k", ""}


def _mmss_to_ms(minutes: int, seconds: float) -> int:
    return int(round((minutes * 60 + seconds) * 1000))


def parse_pace(text: str) -> dict[str, Any]:
    """
    Parse a human pace string into COROS intensity fields.

    The returned dict contains only the fields a run step needs to express a
    pace-based intensity: ``intensity_type`` (3 = pace), ``intensity_value``
    and ``intensity_value_extend`` (milliseconds per km; when a single pace is
    given both get the same value), ``intensity_display_unit`` (2 = km; always
    km internally even when the input was in miles, since COROS converts at
    display time), ``hr_type`` (0 = not an HR intensity), and
    ``is_intensity_percent`` (False — absolute pace, not a percent).

    ``intensity_value`` is always the faster (smaller) number and
    ``intensity_value_extend`` the slower (larger) number regardless of the
    order the user wrote them in.

    Raises ValueError for unparseable input.
    """
    if not isinstance(text, str):
        raise ValueError(f"Pace input must be a string, got {type(text).__name__}.")

    match = _PACE_RE.match(text.strip())
    if not match:
        raise ValueError(
            f"Could not parse pace: {text!r}. "
            "Expected formats: '4:05/km', '4:05-4:15/km', '5:30/mi', '5:30-5:45/mi'."
        )

    min1 = int(match["min1"])
    sec1 = float(match["sec1"])
    if sec1 >= 60:
        raise ValueError(f"Seconds component must be < 60 in pace: {text!r}")
    low_ms_per_unit = _mmss_to_ms(min1, sec1)

    min2_raw = match["min2"]
    sec2_raw = match["sec2"]
    if min2_raw is not None:
        min2 = int(min2_raw)
        sec2 = float(sec2_raw)
        if sec2 >= 60:
            raise ValueError(f"Seconds component must be < 60 in pace: {text!r}")
        high_ms_per_unit = _mmss_to_ms(min2, sec2)
    else:
        high_ms_per_unit = low_ms_per_unit

    unit_raw = (match["unit"] or "km").lower()
    if unit_raw in _MI_UNITS or unit_raw == "m":
        # Convert min/mile to min/km: pace_per_km = pace_per_mile / (miles per km)
        low_ms_per_km = int(round(low_ms_per_unit * 1000.0 / _METERS_PER_MILE))
        high_ms_per_km = int(round(high_ms_per_unit * 1000.0 / _METERS_PER_MILE))
    elif unit_raw in _KM_UNITS:
        low_ms_per_km = low_ms_per_unit
        high_ms_per_km = high_ms_per_unit
    else:
        raise ValueError(f"Unrecognized pace unit: {unit_raw!r} in {text!r}")

    fast, slow = sorted((low_ms_per_km, high_ms_per_km))
    return {
        "intensity_type": 3,
        "intensity_value": fast,
        "intensity_value_extend": slow,
        "intensity_display_unit": 2,
        "hr_type": 0,
        "is_intensity_percent": False,
    }


def format_pace(ms_per_km: int, *, unit: str = "km") -> str:
    """
    Format an ms/km pace back to a human string like "4:05/km".

    Mainly useful for building error messages and documentation examples.
    """
    if unit.lower() in _MI_UNITS:
        ms_per_unit = ms_per_km * _METERS_PER_MILE / 1000.0
        suffix = "/mi"
    else:
        ms_per_unit = ms_per_km
        suffix = "/km"
    total_seconds = ms_per_unit / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds - minutes * 60
    # Handle rounding up to exactly 60 (e.g. 7:59.96 → 8:00)
    if round(seconds, 1) >= 60.0:
        minutes += 1
        seconds = 0.0
    if abs(seconds - round(seconds)) < 0.05:
        return f"{minutes}:{int(round(seconds)):02d}{suffix}"
    return f"{minutes}:{seconds:04.1f}{suffix}"
