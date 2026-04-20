import os
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client


pytestmark = pytest.mark.anyio


def _skip_unless_live_enabled():
    if os.environ.get("COROS_MCP_LIVE") != "1":
        pytest.skip("Set COROS_MCP_LIVE=1 to run live Keychain-backed MCP tests.")


def _skip_unless_destructive_live_enabled():
    if os.environ.get("COROS_MCP_LIVE_DESTRUCTIVE") != "1":
        pytest.skip("Set COROS_MCP_LIVE_DESTRUCTIVE=1 to run destructive live MCP tests.")


def _live_server_params() -> tuple[Path, StdioServerParameters]:
    repo_root = Path(__file__).resolve().parents[1]
    launcher = repo_root / "run-coros-mcp.zsh"
    if not launcher.exists():
        pytest.skip("Live launcher is missing.")

    env = os.environ.copy()
    return repo_root, StdioServerParameters(
        command=str(launcher),
        args=[],
        cwd=repo_root,
        env=env,
    )


async def _call_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    assert result.isError is False
    assert isinstance(result.structuredContent, dict)
    return result.structuredContent


def _find_scheduled_item(items: list[dict], *, name: str, happen_day: str) -> dict:
    return next(
        item
        for item in items
        if item.get("workout_name") == name and item.get("happen_day") == happen_day
    )


async def _cleanup_named_artifacts(
    session: ClientSession,
    *,
    base_name: str,
    created_workout_ids: set[str],
    start_day: str,
    end_day: str,
) -> list[str]:
    cleanup_errors: list[str] = []

    try:
        cleanup_window = await _call_tool(
            session,
            "list_scheduled_workouts",
            {"start_day": start_day, "end_day": end_day},
        )
        for item in cleanup_window.get("scheduled_workouts", []):
            if str(item.get("workout_name", "")).startswith(base_name):
                result = await _call_tool(
                    session,
                    "remove_scheduled_workout",
                    {
                        "plan_id": item["plan_id"],
                        "id_in_plan": item["id_in_plan"],
                        "plan_program_id": item["plan_program_id"],
                    },
                )
                if result.get("removed") is not True:
                    cleanup_errors.append(
                        f"Failed to remove scheduled item {item['id_in_plan']}: {result}"
                    )
    except Exception as exc:  # pragma: no cover - best effort cleanup
        cleanup_errors.append(f"Failed to list/remove scheduled cleanup items: {exc}")

    for workout_id in created_workout_ids:
        try:
            result = await _call_tool(
                session,
                "delete_workout",
                {"workout_id": workout_id},
            )
            if result.get("deleted") is not True:
                cleanup_errors.append(f"Failed to delete workout {workout_id}: {result}")
        except Exception as exc:  # pragma: no cover - best effort cleanup
            cleanup_errors.append(f"Failed to delete workout {workout_id}: {exc}")

    return cleanup_errors


async def test_live_launcher_lists_scheduled_workouts():
    _skip_unless_live_enabled()
    _, params = _live_server_params()

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "list_scheduled_workouts",
                {"start_day": "20260420", "end_day": "20260504"},
            )

    assert result.isError is False
    assert "scheduled_workouts" in result.structuredContent
    assert "error" not in result.structuredContent


async def test_live_end_to_end_workflow_creates_updates_moves_replaces_and_cleans_up():
    _skip_unless_live_enabled()
    _skip_unless_destructive_live_enabled()

    _, params = _live_server_params()
    today = date.today()
    first_day = (today + timedelta(days=30)).strftime("%Y%m%d")
    second_day = (today + timedelta(days=31)).strftime("%Y%m%d")
    run_id = f"{int(time.time())}"
    base_name = f"MCP TEST {run_id}"
    created_workout_ids: set[str] = set()
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            try:
                created = await _call_tool(
                    session,
                    "create_workout",
                    {
                        "name": base_name,
                        "sport_type": 2,
                        "steps": [
                            {
                                "name": "Warm-up",
                                "duration_minutes": 10,
                                "power_low_w": 100,
                                "power_high_w": 140,
                            },
                            {
                                "name": "Main Block",
                                "duration_minutes": 20,
                                "power_low_w": 150,
                                "power_high_w": 190,
                            },
                            {
                                "name": "Cool-down",
                                "duration_minutes": 5,
                                "power_low_w": 80,
                                "power_high_w": 110,
                            },
                        ],
                    },
                )
                original_workout_id = created["workout_id"]
                created_workout_ids.add(original_workout_id)

                workouts = await _call_tool(session, "list_workouts", {})
                assert any(w["id"] == original_workout_id for w in workouts["workouts"])

                fetched_original = await _call_tool(
                    session, "get_workout", {"workout_id": original_workout_id}
                )
                assert fetched_original["workout"]["id"] == original_workout_id
                assert fetched_original["workout"]["name"] == base_name

                scheduled = await _call_tool(
                    session,
                    "schedule_workout",
                    {
                        "workout_id": original_workout_id,
                        "happen_day": first_day,
                        "sort_no": 1,
                    },
                )
                assert scheduled["scheduled"] is True

                scheduled_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                original_entry = _find_scheduled_item(
                    scheduled_window["scheduled_workouts"],
                    name=base_name,
                    happen_day=first_day,
                )

                moved = await _call_tool(
                    session,
                    "move_scheduled_workout",
                    {
                        "plan_id": original_entry["plan_id"],
                        "id_in_plan": original_entry["id_in_plan"],
                        "plan_program_id": original_entry["plan_program_id"],
                        "workout_id": original_workout_id,
                        "happen_day": second_day,
                        "sort_no": 1,
                    },
                )
                assert moved["moved"] is True

                moved_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                assert not any(
                    item.get("workout_name") == base_name and item.get("happen_day") == first_day
                    for item in moved_window["scheduled_workouts"]
                )
                moved_entry = _find_scheduled_item(
                    moved_window["scheduled_workouts"],
                    name=base_name,
                    happen_day=second_day,
                )

                updated = await _call_tool(
                    session,
                    "update_workout",
                    {
                        "workout_id": original_workout_id,
                        "name": f"{base_name} Updated",
                        "step_updates": [
                            {
                                "step_name": "Main Block",
                                "target_duration_seconds": 900,
                            }
                        ],
                    },
                )
                updated_workout_id = updated["new_workout_id"]
                created_workout_ids.add(updated_workout_id)
                fetched_updated = await _call_tool(
                    session, "get_workout", {"workout_id": updated_workout_id}
                )
                assert fetched_updated["workout"]["name"] == f"{base_name} Updated"

                replaced = await _call_tool(
                    session,
                    "replace_scheduled_workout",
                    {
                        "plan_id": moved_entry["plan_id"],
                        "id_in_plan": moved_entry["id_in_plan"],
                        "plan_program_id": moved_entry["plan_program_id"],
                        "workout_id": original_workout_id,
                        "happen_day": second_day,
                        "sort_no": 1,
                        "name": f"{base_name} Replacement",
                        "step_updates": [
                            {
                                "step_name": "Main Block",
                                "target_duration_seconds": 600,
                            }
                        ],
                    },
                )
                replacement_workout_id = replaced["new_workout_id"]
                created_workout_ids.add(replacement_workout_id)
                assert replaced["replaced"] is True

                replaced_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                replacement_entry = _find_scheduled_item(
                    replaced_window["scheduled_workouts"],
                    name=f"{base_name} Replacement",
                    happen_day=second_day,
                )
                assert not any(
                    item.get("workout_name") == base_name and item.get("happen_day") == second_day
                    for item in replaced_window["scheduled_workouts"]
                )
                assert replacement_entry["workout_name"] == f"{base_name} Replacement"
            finally:
                cleanup_errors = await _cleanup_named_artifacts(
                    session,
                    base_name=base_name,
                    created_workout_ids=created_workout_ids,
                    start_day=first_day,
                    end_day=second_day,
                )

    assert not cleanup_errors, f"Cleanup errors: {cleanup_errors}"


async def test_live_run_workflow_creates_updates_moves_replaces_and_cleans_up():
    _skip_unless_live_enabled()
    _skip_unless_destructive_live_enabled()

    _, params = _live_server_params()
    today = date.today()
    first_day = (today + timedelta(days=34)).strftime("%Y%m%d")
    second_day = (today + timedelta(days=35)).strftime("%Y%m%d")
    run_id = f"{int(time.time())}"
    base_name = f"MCP RUN TEST {run_id}"
    created_workout_ids: set[str] = set()

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            try:
                created = await _call_tool(
                    session,
                    "create_run_workout",
                    {
                        "name": base_name,
                        "steps": [
                            {
                                "kind": "warmup",
                                "name": "Warm-up",
                                "target_type": "distance",
                                "target_distance_meters": 2000,
                            },
                            {
                                "kind": "training",
                                "name": "Rep",
                                "target_type": "distance",
                                "target_distance_meters": 1000,
                                "intensity_type": 2,
                                "intensity_value": 160,
                                "intensity_value_extend": 170,
                            },
                            {
                                "kind": "rest",
                                "name": "Recovery",
                                "target_type": "time",
                                "target_duration_seconds": 120,
                            },
                            {
                                "kind": "cooldown",
                                "name": "Cool-down",
                                "target_type": "distance",
                                "target_distance_meters": 1500,
                            },
                        ],
                    },
                )
                original_workout_id = created["workout_id"]
                created_workout_ids.add(original_workout_id)
                assert created["sport_type"] == 1
                assert created["estimated_distance_meters"] == 4500
                assert created["estimated_time_seconds"] == 120

                workouts = await _call_tool(session, "list_workouts", {})
                assert any(w["id"] == original_workout_id for w in workouts["workouts"])

                fetched_original = await _call_tool(
                    session, "get_workout", {"workout_id": original_workout_id}
                )
                assert fetched_original["workout"]["id"] == original_workout_id
                assert fetched_original["workout"]["name"] == base_name
                assert fetched_original["workout"]["sport_type"] == 1
                assert fetched_original["workout"]["exercise_count"] == 4
                rep_step = next(
                    ex
                    for ex in fetched_original["workout"]["exercises"]
                    if ex.get("name") == "Rep"
                )
                assert rep_step["target_type"] == 5
                assert rep_step["target_value"] == 100000

                scheduled = await _call_tool(
                    session,
                    "schedule_workout",
                    {
                        "workout_id": original_workout_id,
                        "happen_day": first_day,
                        "sort_no": 1,
                    },
                )
                assert scheduled["scheduled"] is True

                scheduled_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                original_entry = _find_scheduled_item(
                    scheduled_window["scheduled_workouts"],
                    name=base_name,
                    happen_day=first_day,
                )
                assert original_entry["sport_type"] == 1

                moved = await _call_tool(
                    session,
                    "move_scheduled_workout",
                    {
                        "plan_id": original_entry["plan_id"],
                        "id_in_plan": original_entry["id_in_plan"],
                        "plan_program_id": original_entry["plan_program_id"],
                        "workout_id": original_workout_id,
                        "happen_day": second_day,
                        "sort_no": 1,
                    },
                )
                assert moved["moved"] is True

                moved_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                moved_entry = _find_scheduled_item(
                    moved_window["scheduled_workouts"],
                    name=base_name,
                    happen_day=second_day,
                )

                updated = await _call_tool(
                    session,
                    "update_run_workout",
                    {
                        "workout_id": original_workout_id,
                        "name": f"{base_name} Updated",
                        "estimated_distance_meters": 4300,
                        "step_updates": [
                            {
                                "step_name": "Rep",
                                "target_type": "distance",
                                "target_distance_meters": 800,
                            },
                            {
                                "step_name": "Recovery",
                                "target_type": "time",
                                "target_duration_seconds": 90,
                            },
                        ],
                    },
                )
                updated_workout_id = updated["new_workout_id"]
                created_workout_ids.add(updated_workout_id)
                fetched_updated = await _call_tool(
                    session, "get_workout", {"workout_id": updated_workout_id}
                )
                assert fetched_updated["workout"]["name"] == f"{base_name} Updated"
                assert fetched_updated["workout"]["estimated_distance"] == 430000
                updated_rep = next(
                    ex
                    for ex in fetched_updated["workout"]["exercises"]
                    if ex.get("name") == "Rep"
                )
                updated_recovery = next(
                    ex
                    for ex in fetched_updated["workout"]["exercises"]
                    if ex.get("name") == "Recovery"
                )
                assert updated_rep["target_type"] == 5
                assert updated_rep["target_value"] == 80000
                assert updated_recovery["target_type"] == 2
                assert updated_recovery["target_value"] == 90

                replaced = await _call_tool(
                    session,
                    "replace_scheduled_workout",
                    {
                        "plan_id": moved_entry["plan_id"],
                        "id_in_plan": moved_entry["id_in_plan"],
                        "plan_program_id": moved_entry["plan_program_id"],
                        "workout_id": original_workout_id,
                        "happen_day": second_day,
                        "sort_no": 1,
                        "name": f"{base_name} Replacement",
                        "step_updates": [
                            {
                                "step_name": "Rep",
                                "target_distance_meters": 600,
                            }
                        ],
                    },
                )
                replacement_workout_id = replaced["new_workout_id"]
                created_workout_ids.add(replacement_workout_id)
                assert replaced["replaced"] is True

                replaced_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                replacement_entry = _find_scheduled_item(
                    replaced_window["scheduled_workouts"],
                    name=f"{base_name} Replacement",
                    happen_day=second_day,
                )
                assert replacement_entry["sport_type"] == 1
                assert not any(
                    item.get("workout_name") == base_name and item.get("happen_day") == second_day
                    for item in replaced_window["scheduled_workouts"]
                )
            finally:
                cleanup_errors = await _cleanup_named_artifacts(
                    session,
                    base_name=base_name,
                    created_workout_ids=created_workout_ids,
                    start_day=first_day,
                    end_day=second_day,
                )

    assert not cleanup_errors, f"Cleanup errors: {cleanup_errors}"


async def test_live_complex_run_workflow_supports_repeats_and_mixed_targets():
    _skip_unless_live_enabled()
    _skip_unless_destructive_live_enabled()

    _, params = _live_server_params()
    today = date.today()
    first_day = (today + timedelta(days=38)).strftime("%Y%m%d")
    second_day = (today + timedelta(days=39)).strftime("%Y%m%d")
    run_id = f"{int(time.time())}"
    base_name = f"MCP COMPLEX RUN {run_id}"
    created_workout_ids: set[str] = set()

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            try:
                created = await _call_tool(
                    session,
                    "create_run_workout",
                    {
                        "name": base_name,
                        "steps": [
                            {
                                "kind": "warmup",
                                "name": "Warm-up",
                                "target_type": "distance",
                                "target_distance_meters": 2000,
                            },
                            {
                                "repeat": 3,
                                "name": "Main Set",
                                "steps": [
                                    {
                                        "kind": "training",
                                        "name": "Fast Rep",
                                        "target_type": "distance",
                                        "target_distance_meters": 800,
                                        "intensity_type": 3,
                                        "intensity_value": 186411,
                                        "intensity_value_extend": 223694,
                                        "intensity_display_unit": 2,
                                    },
                                    {
                                        "kind": "rest",
                                        "name": "Float Recovery",
                                        "target_type": "time",
                                        "target_duration_seconds": 90,
                                    },
                                ],
                            },
                            {
                                "kind": "cooldown",
                                "name": "Cool-down",
                                "target_type": "time",
                                "target_duration_seconds": 600,
                            },
                        ],
                    },
                )
                original_workout_id = created["workout_id"]
                created_workout_ids.add(original_workout_id)
                assert created["estimated_distance_meters"] == 4400
                assert created["estimated_time_seconds"] == 870
                assert created["steps_count"] == 5

                fetched_original = await _call_tool(
                    session, "get_workout", {"workout_id": original_workout_id}
                )
                assert fetched_original["workout"]["exercise_count"] >= 4
                fast_rep = next(
                    ex
                    for ex in fetched_original["workout"]["exercises"]
                    if ex.get("name") == "Fast Rep"
                )
                float_recovery = next(
                    ex
                    for ex in fetched_original["workout"]["exercises"]
                    if ex.get("name") == "Float Recovery"
                )
                group_step = next(
                    (ex for ex in fetched_original["workout"]["exercises"] if ex.get("is_group")),
                    None,
                )
                if group_step is not None:
                    assert group_step["sets"] == 3
                else:
                    assert max(int(ex.get("sets", 1)) for ex in fetched_original["workout"]["exercises"]) >= 3
                assert fast_rep["target_type"] == 5
                assert fast_rep["target_value"] == 80000
                assert fast_rep["intensity_type"] == 3
                assert float_recovery["target_type"] == 2
                assert float_recovery["target_value"] == 90

                scheduled = await _call_tool(
                    session,
                    "schedule_workout",
                    {
                        "workout_id": original_workout_id,
                        "happen_day": first_day,
                        "sort_no": 1,
                    },
                )
                assert scheduled["scheduled"] is True

                scheduled_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                original_entry = _find_scheduled_item(
                    scheduled_window["scheduled_workouts"],
                    name=base_name,
                    happen_day=first_day,
                )

                moved = await _call_tool(
                    session,
                    "move_scheduled_workout",
                    {
                        "plan_id": original_entry["plan_id"],
                        "id_in_plan": original_entry["id_in_plan"],
                        "plan_program_id": original_entry["plan_program_id"],
                        "workout_id": original_workout_id,
                        "happen_day": second_day,
                        "sort_no": 1,
                    },
                )
                assert moved["moved"] is True

                moved_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                moved_entry = _find_scheduled_item(
                    moved_window["scheduled_workouts"],
                    name=base_name,
                    happen_day=second_day,
                )

                updated = await _call_tool(
                    session,
                    "update_run_workout",
                    {
                        "workout_id": original_workout_id,
                        "name": f"{base_name} Updated",
                        "step_updates": [
                            {
                                "step_name": "Fast Rep",
                                "target_type": "distance",
                                "target_distance_meters": 1000,
                            },
                            {
                                "step_name": "Float Recovery",
                                "target_type": "time",
                                "target_duration_seconds": 60,
                            },
                            {
                                "step_name": "Cool-down",
                                "target_type": "distance",
                                "target_distance_meters": 1000,
                            },
                        ],
                    },
                )
                updated_workout_id = updated["new_workout_id"]
                created_workout_ids.add(updated_workout_id)
                fetched_updated = await _call_tool(
                    session, "get_workout", {"workout_id": updated_workout_id}
                )
                updated_fast_rep = next(
                    ex
                    for ex in fetched_updated["workout"]["exercises"]
                    if ex.get("name") == "Fast Rep"
                )
                updated_recovery = next(
                    ex
                    for ex in fetched_updated["workout"]["exercises"]
                    if ex.get("name") == "Float Recovery"
                )
                updated_cooldown = next(
                    ex
                    for ex in fetched_updated["workout"]["exercises"]
                    if ex.get("name") == "Cool-down"
                )
                assert updated_fast_rep["target_value"] == 100000
                assert updated_recovery["target_value"] == 60
                assert updated_cooldown["target_type"] == 5
                assert updated_cooldown["target_value"] == 100000

                replaced = await _call_tool(
                    session,
                    "replace_scheduled_workout",
                    {
                        "plan_id": moved_entry["plan_id"],
                        "id_in_plan": moved_entry["id_in_plan"],
                        "plan_program_id": moved_entry["plan_program_id"],
                        "workout_id": original_workout_id,
                        "happen_day": second_day,
                        "sort_no": 1,
                        "name": f"{base_name} Replacement",
                        "step_updates": [
                            {
                                "step_name": "Fast Rep",
                                "target_distance_meters": 600,
                            },
                            {
                                "step_name": "Float Recovery",
                                "target_duration_seconds": 45,
                            },
                        ],
                    },
                )
                replacement_workout_id = replaced["new_workout_id"]
                created_workout_ids.add(replacement_workout_id)
                replacement_workout = await _call_tool(
                    session, "get_workout", {"workout_id": replacement_workout_id}
                )
                replacement_rep = next(
                    ex
                    for ex in replacement_workout["workout"]["exercises"]
                    if ex.get("name") == "Fast Rep"
                )
                replacement_recovery = next(
                    ex
                    for ex in replacement_workout["workout"]["exercises"]
                    if ex.get("name") == "Float Recovery"
                )
                assert replacement_rep["target_value"] == 60000
                assert replacement_recovery["target_value"] == 45

                replaced_window = await _call_tool(
                    session,
                    "list_scheduled_workouts",
                    {"start_day": first_day, "end_day": second_day},
                )
                replacement_entry = _find_scheduled_item(
                    replaced_window["scheduled_workouts"],
                    name=f"{base_name} Replacement",
                    happen_day=second_day,
                )
                assert replacement_entry["sport_type"] == 1
                assert not any(
                    item.get("workout_name") == base_name and item.get("happen_day") == second_day
                    for item in replaced_window["scheduled_workouts"]
                )
            finally:
                cleanup_errors = await _cleanup_named_artifacts(
                    session,
                    base_name=base_name,
                    created_workout_ids=created_workout_ids,
                    start_day=first_day,
                    end_day=second_day,
                )

    assert not cleanup_errors, f"Cleanup errors: {cleanup_errors}"
