import pytest

from pace_parser import parse_pace, format_pace


def test_parses_single_km_pace():
    result = parse_pace("4:05/km")
    assert result == {
        "intensity_type": 3,
        "intensity_value": 245000,
        "intensity_value_extend": 245000,
        "intensity_display_unit": 2,
        "hr_type": 0,
        "is_intensity_percent": False,
    }


def test_parses_km_pace_range():
    result = parse_pace("4:05-4:15/km")
    assert result["intensity_value"] == 245000
    assert result["intensity_value_extend"] == 255000
    assert result["intensity_display_unit"] == 2


def test_range_order_normalizes_fast_to_slow():
    """User writes '4:15-4:05' (slow-to-fast). Result must still be fast, slow."""
    result = parse_pace("4:15-4:05/km")
    assert result["intensity_value"] == 245000
    assert result["intensity_value_extend"] == 255000


def test_parses_mile_pace_converts_to_ms_per_km():
    result = parse_pace("8:00/mi")
    # 8:00/mi = 480s/mi. 480 / 1.609344 ≈ 298.258s/km → 298258 ms/km
    assert 298000 <= result["intensity_value"] <= 298500
    assert result["intensity_display_unit"] == 2  # always stored as km


def test_parses_mile_range():
    result = parse_pace("7:30-8:00/mi")
    # Faster (7:30) becomes lower ms/km.
    assert result["intensity_value"] < result["intensity_value_extend"]


def test_whitespace_and_slash_optional():
    assert parse_pace("4:05 km")["intensity_value"] == 245000
    assert parse_pace("  4:05/km  ")["intensity_value"] == 245000
    assert parse_pace("4:05-4:15 /km")["intensity_value"] == 245000


def test_en_dash_accepted():
    assert parse_pace("4:05–4:15/km")["intensity_value"] == 245000  # en-dash


def test_fractional_seconds():
    result = parse_pace("4:05.5/km")
    # 245.5s × 1000 = 245500 ms/km
    assert result["intensity_value"] == 245500


def test_unit_defaults_to_km_when_omitted():
    assert parse_pace("4:05")["intensity_value"] == 245000


def test_invalid_pace_raises():
    with pytest.raises(ValueError):
        parse_pace("not a pace")
    with pytest.raises(ValueError):
        parse_pace("")


def test_seconds_must_be_under_60():
    with pytest.raises(ValueError):
        parse_pace("4:60/km")


def test_format_pace_round_trip_km():
    assert format_pace(245000) == "4:05/km"
    assert format_pace(245000, unit="km") == "4:05/km"


def test_format_pace_round_trip_mi():
    result = parse_pace("8:00/mi")
    formatted = format_pace(result["intensity_value"], unit="mi")
    # Should round-trip close to the original
    assert formatted.startswith("8:00") or formatted.startswith("7:59")


def test_normalize_run_step_expands_pace(monkeypatch):
    """pace field on a run step expands to the raw intensity fields."""
    from run_workout_schema import normalize_run_step_fields

    step = {
        "kind": "training",
        "target_type": "distance",
        "target_distance_meters": 1000,
        "pace": "4:05-4:15/km",
    }
    normalized = normalize_run_step_fields(step, allow_selectors=False)

    assert normalized["intensity_type"] == 3
    assert normalized["intensity_value"] == 245000
    assert normalized["intensity_value_extend"] == 255000
    assert normalized["intensity_display_unit"] == 2
    assert "pace" not in normalized  # consumed


def test_normalize_run_step_raw_fields_win_over_pace():
    """Explicit intensity_value overrides pace parsing to preserve backward compat."""
    from run_workout_schema import normalize_run_step_fields

    step = {
        "kind": "training",
        "target_type": "distance",
        "target_distance_meters": 1000,
        "pace": "4:05/km",
        "intensity_value": 200000,  # explicit override
    }
    normalized = normalize_run_step_fields(step, allow_selectors=False)

    assert normalized["intensity_value"] == 200000  # explicit wins
