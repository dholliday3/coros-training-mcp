from types import SimpleNamespace

import pytest

import server


@pytest.mark.anyio
async def test_get_run_workout_schema_returns_run_builder_contract():
    result = await server.get_run_workout_schema()

    assert "schema" in result
    assert "create_run_workout" in result["schema"]
    assert "update_run_workout" in result["schema"]
    assert "Pace" in result["schema"]["run_builder_labels"]["intensity_types"]


@pytest.mark.anyio
async def test_get_workout_builder_catalog_uses_filtered_loader(monkeypatch):
    monkeypatch.setattr(
        server,
        "load_catalog_for_sport",
        lambda sport: {"live_builder_catalog": {"sports": {"run": {"label": sport}}}},
    )

    result = await server.get_workout_builder_catalog("run")

    assert result == {"catalog": {"live_builder_catalog": {"sports": {"run": {"label": "run"}}}}}


@pytest.mark.anyio
async def test_get_workout_returns_wrapped_payload(monkeypatch):
    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_fetch_workout(workout_id):
        assert workout_id == "42"
        return {"id": "42", "name": "Tempo Run"}

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "fetch_workout", fake_fetch_workout)

    result = await server.get_workout("42")

    assert result == {"workout": {"id": "42", "name": "Tempo Run"}}


@pytest.mark.anyio
async def test_list_scheduled_workouts_returns_calendar_friendly_items(monkeypatch):
    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_fetch_scheduled_workouts(start_day, end_day):
        assert (start_day, end_day) == ("20260420", "20260427")
        return [{"plan_id": "plan-1", "happen_day": "20260422", "workout_name": "Track"}]

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "fetch_scheduled_workouts", fake_fetch_scheduled_workouts)

    result = await server.list_scheduled_workouts("20260420", "20260427")

    assert result["count"] == 1
    assert result["scheduled_workouts"][0]["workout_name"] == "Track"
    assert result["date_range"] == "20260420 – 20260427"


@pytest.mark.anyio
async def test_move_scheduled_workout_schedules_before_removing(monkeypatch):
    calls = []

    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_find_scheduled_entry(plan_id, id_in_plan, *, around_day=None):
        calls.append(("find", plan_id, id_in_plan, around_day))
        return {
            "entity": {"planId": plan_id, "idInPlan": id_in_plan, "planProgramId": "42", "happenDay": "20260423"},
            "program": {"id": "42", "name": "Track"},
            "plan_program_id": "42",
            "happen_day": "20260423",
        }

    async def fake_schedule_workout(workout_id, happen_day, sort_no, *, program=None):
        calls.append(("schedule", workout_id, happen_day, sort_no, program))

    async def fake_remove_scheduled_workout(plan_id, id_in_plan, plan_program_id=None):
        calls.append(("remove", plan_id, id_in_plan, plan_program_id))

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "find_scheduled_entry", fake_find_scheduled_entry)
    monkeypatch.setattr(server.coros_api, "schedule_workout", fake_schedule_workout)
    monkeypatch.setattr(server.coros_api, "remove_scheduled_workout", fake_remove_scheduled_workout)

    result = await server.move_scheduled_workout(
        plan_id="plan-1",
        id_in_plan="123",
        happen_day="20260425",
        workout_id="42",
        plan_program_id="42",
        sort_no=3,
    )

    assert result["moved"] is True
    assert result["source_happen_day"] == "20260423"
    assert calls == [
        ("find", "plan-1", "123", None),
        ("schedule", "42", "20260425", 3, {"id": "42", "name": "Track"}),
        ("remove", "plan-1", "123", "42"),
    ]


@pytest.mark.anyio
async def test_move_scheduled_workout_uses_plan_embedded_program(monkeypatch):
    """Plan-embedded programs (no library counterpart) must be movable."""
    calls = []

    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_find_scheduled_entry(plan_id, id_in_plan, *, around_day=None):
        calls.append(("find", plan_id, id_in_plan, around_day))
        return {
            "entity": {"planId": plan_id, "idInPlan": id_in_plan, "planProgramId": "5", "happenDay": "20260423"},
            "program": {"id": "476881223711637778", "name": "S5724", "exercises": [{"name": "Planks"}]},
            "plan_program_id": "5",
            "happen_day": "20260423",
        }

    async def fake_schedule_workout(workout_id, happen_day, sort_no, *, program=None):
        calls.append(("schedule", workout_id, happen_day, sort_no, program))

    async def fake_remove_scheduled_workout(plan_id, id_in_plan, plan_program_id=None):
        calls.append(("remove", plan_id, id_in_plan, plan_program_id))

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "find_scheduled_entry", fake_find_scheduled_entry)
    monkeypatch.setattr(server.coros_api, "schedule_workout", fake_schedule_workout)
    monkeypatch.setattr(server.coros_api, "remove_scheduled_workout", fake_remove_scheduled_workout)

    # Caller passes only plan_id + id_in_plan — no workout_id — simulating
    # the real-world scenario where the user moves a workout from a
    # subscribed training plan.
    result = await server.move_scheduled_workout(
        plan_id="plan-1",
        id_in_plan="5",
        happen_day="20260422",
        source_happen_day="20260423",
    )

    assert result["moved"] is True
    assert result["workout_id"] == "476881223711637778"
    assert calls[0] == ("find", "plan-1", "5", "20260423")
    # Critically: schedule_workout was called with the embedded program,
    # NOT a library workout lookup — and happened BEFORE remove.
    schedule_call = calls[1]
    assert schedule_call[0] == "schedule"
    assert schedule_call[4]["name"] == "S5724"
    assert calls[2] == ("remove", "plan-1", "5", "5")


@pytest.mark.anyio
async def test_move_scheduled_workout_fails_safely_when_entry_not_found(monkeypatch):
    """If the scheduled entry doesn't exist, no destructive call must run."""
    calls = []

    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_find_scheduled_entry(plan_id, id_in_plan, *, around_day=None):
        calls.append(("find", plan_id, id_in_plan, around_day))
        return None

    async def fake_schedule_workout(*args, **kwargs):
        calls.append(("schedule", args, kwargs))

    async def fake_remove_scheduled_workout(*args, **kwargs):
        calls.append(("remove", args, kwargs))

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "find_scheduled_entry", fake_find_scheduled_entry)
    monkeypatch.setattr(server.coros_api, "schedule_workout", fake_schedule_workout)
    monkeypatch.setattr(server.coros_api, "remove_scheduled_workout", fake_remove_scheduled_workout)

    result = await server.move_scheduled_workout(
        plan_id="plan-1",
        id_in_plan="nonexistent",
        happen_day="20260425",
        workout_id="hallucinated-id",
    )

    assert result["moved"] is False
    assert "No scheduled entry found" in result["error"]
    # Only the lookup ran; no schedule or remove.
    assert calls == [("find", "plan-1", "nonexistent", None)]


@pytest.mark.anyio
async def test_update_workout_clones_then_optionally_deletes(monkeypatch):
    calls = []

    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_clone_and_patch_workout(workout_id, **kwargs):
        calls.append(("clone", workout_id, kwargs))
        return {
            "old_workout_id": workout_id,
            "new_workout_id": "99",
            "workout": {"id": "99", "name": "Updated Run"},
        }

    async def fake_delete_workout(workout_id):
        calls.append(("delete", workout_id))

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "clone_and_patch_workout", fake_clone_and_patch_workout)
    monkeypatch.setattr(server.coros_api, "delete_workout", fake_delete_workout)

    result = await server.update_workout(
        workout_id="42",
        name="Updated Run",
        estimated_distance_meters=10000,
        step_updates=[{"step_index": 0, "target_distance_meters": 3000}],
        delete_original=True,
    )

    assert result["new_workout_id"] == "99"
    assert result["deleted_original"] is True
    assert calls[0][0] == "clone"
    assert calls[1] == ("delete", "42")


@pytest.mark.anyio
async def test_replace_scheduled_workout_clones_schedules_then_removes(monkeypatch):
    calls = []

    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_find_scheduled_entry(plan_id, id_in_plan, *, around_day=None):
        calls.append(("find", plan_id, id_in_plan))
        return {
            "entity": {"planId": plan_id, "idInPlan": id_in_plan, "planProgramId": "42", "happenDay": "20260425"},
            "program": {"id": "42", "name": "Tempo Run"},
            "plan_program_id": "42",
            "happen_day": "20260425",
        }

    async def fake_clone_and_patch_workout(workout_id, **kwargs):
        calls.append(("clone", workout_id, kwargs))
        return {
            "old_workout_id": workout_id,
            "new_workout_id": "99",
            "workout": {"id": "99", "name": "Updated Scheduled Run"},
        }

    async def fake_schedule_workout(workout_id, happen_day, sort_no, *, program=None):
        calls.append(("schedule", workout_id, happen_day, sort_no))

    async def fake_remove_scheduled_workout(plan_id, id_in_plan, plan_program_id=None):
        calls.append(("remove", plan_id, id_in_plan, plan_program_id))

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "find_scheduled_entry", fake_find_scheduled_entry)
    monkeypatch.setattr(server.coros_api, "clone_and_patch_workout", fake_clone_and_patch_workout)
    monkeypatch.setattr(server.coros_api, "schedule_workout", fake_schedule_workout)
    monkeypatch.setattr(server.coros_api, "remove_scheduled_workout", fake_remove_scheduled_workout)

    result = await server.replace_scheduled_workout(
        plan_id="plan-1",
        id_in_plan="123",
        happen_day="20260428",
        workout_id="42",
        plan_program_id="42",
        sort_no=2,
        step_updates=[{"step_index": 0, "target_distance_meters": 5000}],
    )

    assert result["replaced"] is True
    assert result["new_workout_id"] == "99"
    assert calls == [
        ("find", "plan-1", "123"),
        ("clone", "42", {
            "name": None,
            "estimated_distance_meters": None,
            "estimated_time_seconds": None,
            "step_updates": [{"step_index": 0, "target_distance_meters": 5000}],
            "source_program": {"id": "42", "name": "Tempo Run"},
        }),
        ("schedule", "99", "20260428", 2),
        ("remove", "plan-1", "123", "42"),
    ]


@pytest.mark.anyio
async def test_create_run_workout_uses_running_builder(monkeypatch):
    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_create_run_workout(name, steps):
        assert name == "Track Session"
        assert steps[0]["kind"] == "warmup"
        return "run-42"

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "create_run_workout", fake_create_run_workout)

    result = await server.create_run_workout(
        name="Track Session",
        steps=[
            {"kind": "warmup", "target_type": "distance", "target_distance_meters": 3000},
            {"kind": "cooldown", "target_type": "time", "target_duration_seconds": 600},
        ],
    )

    assert result["workout_id"] == "run-42"
    assert result["sport_type"] == 1
    assert result["estimated_distance_meters"] == 3000


@pytest.mark.anyio
async def test_create_run_workout_normalizes_intensity_label(monkeypatch):
    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_create_run_workout(name, steps):
        assert steps[0]["intensity_label"] == "Pace"
        assert steps[0]["intensity_type"] == 3
        assert steps[0]["is_intensity_percent"] is False
        assert steps[0]["hr_type"] == 0
        return "run-43"

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "create_run_workout", fake_create_run_workout)

    result = await server.create_run_workout(
        name="Pace Session",
        steps=[
            {
                "kind": "training",
                "target_type": "distance",
                "target_distance_meters": 1000,
                "intensity_label": "Pace",
            }
        ],
    )

    assert result["workout_id"] == "run-43"


@pytest.mark.anyio
async def test_export_activity_file_wraps_coros_export(monkeypatch):
    async def fake_get_auth():
        return SimpleNamespace(user_id="tester")

    async def fake_run_with_auth(fn, auth, *args, **kwargs):
        return await fn(*args, **kwargs)

    async def fake_export_activity_file(activity_id, sport_type, file_type, output_path):
        assert activity_id == "act-1"
        assert sport_type == 100
        assert file_type == "gpx"
        assert output_path == "/tmp/run.gpx"
        return {
            "activity_id": activity_id,
            "sport_type": sport_type,
            "file_type": file_type,
            "file_url": "https://example.com/run.gpx",
            "output_path": output_path,
            "downloaded": True,
        }

    monkeypatch.setattr(server, "_get_auth", fake_get_auth)
    monkeypatch.setattr(server, "_run_with_auth", fake_run_with_auth)
    monkeypatch.setattr(server.coros_api, "export_activity_file", fake_export_activity_file)

    result = await server.export_activity_file(
        activity_id="act-1",
        sport_type=100,
        file_type="gpx",
        output_path="/tmp/run.gpx",
    )

    assert result["downloaded"] is True
    assert result["output_path"] == "/tmp/run.gpx"


@pytest.mark.anyio
async def test_update_run_workout_normalizes_target_type_aliases(monkeypatch):
    captured = {}

    async def fake_update_workout(**kwargs):
        captured.update(kwargs)
        return {"new_workout_id": "99"}

    monkeypatch.setattr(server, "update_workout", fake_update_workout)

    result = await server.update_run_workout(
        workout_id="42",
        step_updates=[
            {"step_name": "Rep", "target_type": "distance", "target_distance_meters": 1000},
            {"step_name": "Recovery", "target_type": "time", "target_duration_seconds": 120},
        ],
    )

    assert result["new_workout_id"] == "99"
    assert captured["step_updates"][0]["target_type"] == "distance"
    assert captured["step_updates"][1]["target_type"] == "time"


@pytest.mark.anyio
async def test_update_run_workout_forwards_delete_original(monkeypatch):
    captured = {}

    async def fake_update_workout(**kwargs):
        captured.update(kwargs)
        return {"new_workout_id": "101"}

    monkeypatch.setattr(server, "update_workout", fake_update_workout)

    result = await server.update_run_workout(
        workout_id="42",
        name="Updated Track",
        delete_original=True,
        step_updates=[{"step_name": "Rep", "target_type": "distance", "target_distance_meters": 800}],
    )

    assert result["new_workout_id"] == "101"
    assert captured["delete_original"] is True
    assert captured["name"] == "Updated Track"
    assert captured["step_updates"][0]["target_type"] == "distance"


@pytest.mark.anyio
async def test_update_run_workout_normalizes_intensity_label(monkeypatch):
    captured = {}

    async def fake_update_workout(**kwargs):
        captured.update(kwargs)
        return {"new_workout_id": "101"}

    monkeypatch.setattr(server, "update_workout", fake_update_workout)

    result = await server.update_run_workout(
        workout_id="42",
        step_updates=[
            {
                "step_name": "Rep",
                "target_type": "distance",
                "target_distance_meters": 1000,
                "intensity_label": "% Max Heart Rate",
            }
        ],
    )

    assert result["new_workout_id"] == "101"
    assert captured["step_updates"][0]["intensity_type"] == 2
    assert captured["step_updates"][0]["hr_type"] == 1
    assert captured["step_updates"][0]["is_intensity_percent"] is True
