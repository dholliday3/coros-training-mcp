"""
Shared strength-workout field vocabulary.

Mirrors run_workout_schema.py: exposes the field set accepted by
``create_strength_workout`` and the generic ``update_workout`` when the
target is a strength program. The goal is agent discoverability — agents
shouldn't have to read source to know what they can patch.

Strength exercises come from the COROS catalogue; resolve ``origin_id`` /
``overview`` / ``name`` via ``list_exercises`` (``sport_type=4``).
"""
from __future__ import annotations

from typing import Any


# Strength uses targetType 2 (time seconds) and 3 (reps).
STRENGTH_TARGET_TYPE_ALIASES = {
    "time": 2,
    "reps": 3,
}


def get_strength_workout_schema() -> dict[str, Any]:
    create_exercise_fields = [
        {
            "name": "origin_id",
            "required": True,
            "description": "Catalogue exercise ID from list_exercises (sport_type=4).",
        },
        {
            "name": "name",
            "required": False,
            "description": "T-code name (e.g. 'T1010' for Planks). Typically copied from list_exercises.",
        },
        {
            "name": "overview",
            "required": False,
            "description": "sid_strength_* overview key (e.g. 'sid_strength_planks'). Copied from list_exercises.",
        },
        {
            "name": "target_type",
            "required": True,
            "description": "Strength target type.",
            "allowed_values": sorted(STRENGTH_TARGET_TYPE_ALIASES) + [2, 3],
            "notes": "Accept string aliases ('time', 'reps') or raw ints (2=time, 3=reps).",
        },
        {
            "name": "target_value",
            "required": True,
            "description": "Seconds (if target_type=time) or rep count (if target_type=reps).",
        },
        {
            "name": "rest_seconds",
            "required": False,
            "description": "Rest after this exercise, in seconds. Default 60.",
        },
    ]
    update_patch_fields = [
        {"name": "name", "description": "Update the step's display name."},
        {"name": "overview", "description": "Update the sid_strength_* key — pair with origin_id when swapping exercises."},
        {
            "name": "origin_id",
            "description": "Swap to a different catalog exercise. Usually paired with name + overview so the label matches.",
        },
        {
            "name": "target_type",
            "description": "'time', 'reps', or raw ints 2 / 3.",
            "allowed_values": sorted(STRENGTH_TARGET_TYPE_ALIASES) + [2, 3],
        },
        {"name": "target_value", "description": "New seconds or rep count."},
        {"name": "rest_seconds", "description": "Strength-friendly alias for rest_value."},
        {"name": "rest_value", "description": "Raw COROS rest value (seconds)."},
        {"name": "rest_type", "description": "Raw COROS rest type (1 = seconds is typical)."},
        {"name": "sets", "description": "Set count for this specific exercise."},
    ]
    selector_fields = [
        {"name": "step_index", "description": "Zero-based exercise index in the fetched workout."},
        {"name": "step_id", "description": "Existing COROS exercise ID."},
        {"name": "step_name", "description": "Existing exercise T-code name (e.g. 'T1010')."},
    ]
    top_level_fields = [
        {"name": "name", "description": "Workout name (appears in the library and on the watch)."},
        {"name": "sets", "description": "Circuit repetition count — repeats all exercises this many times."},
    ]
    return {
        "notes": [
            "create_strength_workout and update_workout share the same exercise-level vocabulary.",
            "Exercises come from list_exercises(sport_type=4); use its output to fill origin_id / name / overview.",
            "update_workout accepts the step_updates format described here for strength workouts, identified by (workout_id from list_workouts).",
            "To swap an exercise in an existing strength workout, patch origin_id + overview + name in one update.",
            "Adding or removing exercises isn't supported by update_workout yet — clone-with-edits only modifies existing exercises.",
        ],
        "create_strength_workout": {
            "top_level_fields": top_level_fields,
            "exercise_fields": create_exercise_fields,
        },
        "update_workout_for_strength": {
            "selector_fields": selector_fields,
            "patch_fields": update_patch_fields,
        },
        "exercise_catalog_lookup": {
            "tool": "list_exercises",
            "args": {"sport_type": 4},
            "use": "Resolve origin_id, name (T-code), and overview (sid_strength_* key) for any strength exercise.",
        },
        "target_type_aliases": dict(STRENGTH_TARGET_TYPE_ALIASES),
    }
