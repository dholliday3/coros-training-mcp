"""Tests for strength workout update vocabulary and schema tool."""
import copy

import pytest

import coros_api
import server


def _make_strength_workout() -> dict:
    """Minimal strength workout raw payload mirroring a real response."""
    return {
        "id": "wk-1",
        "idInPlan": "0",
        "name": "Test Circuit",
        "sportType": 4,
        "exerciseNum": 2,
        "exercises": [
            {
                "id": "1",
                "name": "T1010",
                "originId": "425827856334110721",
                "overview": "sid_strength_planks",
                "exerciseType": 2,
                "sportType": 4,
                "targetType": 2,
                "targetValue": 30,
                "restType": 1,
                "restValue": 10,
                "sets": 1,
                "groupId": "0",
                "isGroup": False,
                "intensityType": 1,
                "intensityValue": 0,
            },
            {
                "id": "2",
                "name": "T1076",
                "originId": "425832906678779905",
                "overview": "sid_strength_bicycle_crunches",
                "exerciseType": 2,
                "sportType": 4,
                "targetType": 2,
                "targetValue": 30,
                "restType": 1,
                "restValue": 10,
                "sets": 1,
                "groupId": "0",
                "isGroup": False,
                "intensityType": 1,
                "intensityValue": 0,
            },
        ],
    }


def test_target_type_accepts_reps_alias():
    workout = _make_strength_workout()
    coros_api._apply_step_updates(workout, [
        {"step_name": "T1010", "target_type": "reps", "target_value": 15},
    ])
    assert workout["exercises"][0]["targetType"] == 3
    assert workout["exercises"][0]["targetValue"] == 15


def test_rest_seconds_alias_updates_rest_value():
    workout = _make_strength_workout()
    coros_api._apply_step_updates(workout, [
        {"step_index": 0, "rest_seconds": 45},
    ])
    assert workout["exercises"][0]["restValue"] == 45


def test_origin_id_swaps_exercise():
    """Swapping origin_id + overview + name replaces one catalog exercise with another."""
    workout = _make_strength_workout()
    coros_api._apply_step_updates(workout, [
        {
            "step_name": "T1076",
            "origin_id": "426618429085237248",
            "name": "T1150",
            "overview": "sid_strength_bird_dog_type",
        },
    ])
    swapped = workout["exercises"][1]
    assert swapped["originId"] == "426618429085237248"
    assert swapped["name"] == "T1150"
    assert swapped["overview"] == "sid_strength_bird_dog_type"


def test_unknown_target_type_alias_gives_clear_error():
    workout = _make_strength_workout()
    with pytest.raises(ValueError) as exc:
        coros_api._apply_step_updates(workout, [
            {"step_index": 0, "target_type": "weight"},
        ])
    assert "Unsupported target_type" in str(exc.value)
    assert "reps" in str(exc.value)


@pytest.mark.anyio
async def test_get_strength_workout_schema_exposes_patch_vocabulary():
    result = await server.get_strength_workout_schema()
    schema = result["schema"]
    assert "create_strength_workout" in schema
    assert "update_workout_for_strength" in schema
    assert "exercise_catalog_lookup" in schema
    patch_field_names = {f["name"] for f in schema["update_workout_for_strength"]["patch_fields"]}
    # The strength-specific additions must be discoverable.
    assert "origin_id" in patch_field_names
    assert "rest_seconds" in patch_field_names
    assert "reps" in schema["target_type_aliases"]
