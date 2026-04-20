import coros_api
import pytest
from models import StoredAuth


def test_parse_workout_preserves_running_fields():
    raw = {
        "id": "42",
        "idInPlan": "99",
        "name": "Track 5x1k",
        "sportType": 100,
        "estimatedTime": 3600,
        "estimatedDistance": 12000,
        "estimatedType": 2,
        "distanceDisplayUnit": 1,
        "targetType": 1,
        "targetValue": 1000,
        "simple": False,
        "exerciseNum": 2,
        "exercises": [
            {
                "id": "1",
                "name": "Warm-up",
                "overview": "sid_run_warm_up_dist",
                "exerciseType": 2,
                "sportType": 100,
                "targetType": 1,
                "targetValue": 3000,
                "targetDisplayUnit": 1,
                "intensityType": 3,
                "intensityValue": 300,
                "intensityValueExtend": 330,
                "intensityDisplayUnit": 7,
                "restType": 0,
                "restValue": 0,
                "sets": 1,
                "groupId": "0",
                "isGroup": False,
                "originId": "0",
                "sortNo": 16777216,
            }
        ],
    }

    parsed = coros_api._parse_workout(raw)

    assert parsed["id"] == "42"
    assert parsed["id_in_plan"] == "99"
    assert parsed["sport_type"] == 100
    assert parsed["sport_name"] == "Running"
    assert parsed["estimated_distance"] == 12000
    assert parsed["estimated_type"] == 2
    assert parsed["target_type"] == 1
    assert parsed["target_value"] == 1000
    assert parsed["distance_display_unit"] == 1
    assert parsed["simple"] is False

    exercise = parsed["exercises"][0]
    assert exercise["overview"] == "Warm up dist"
    assert exercise["raw_overview"] == "sid_run_warm_up_dist"
    assert exercise["target_type"] == 1
    assert exercise["target_value"] == 3000
    assert exercise["intensity_type"] == 3
    assert exercise["intensity_value"] == 300
    assert exercise["intensity_value_extend"] == 330
    assert exercise["sort_no"] == 16777216


def test_normalize_scheduled_workouts_flattens_entities_and_programs():
    raw_schedule = {
        "entities": [
            {
                "planId": "plan-1",
                "idInPlan": "123",
                "planProgramId": "42",
                "happenDay": "20260422",
                "sortNoInSchedule": 2,
            }
        ],
        "programs": [
            {
                "id": "42",
                "idInPlan": "123",
                "name": "Tempo Run",
                "sportType": 100,
                "estimatedTime": 2700,
                "estimatedDistance": 8000,
                "exerciseNum": 1,
                "exercises": [],
            }
        ],
    }

    normalized = coros_api._normalize_scheduled_workouts(raw_schedule)

    assert len(normalized) == 1
    item = normalized[0]
    assert item["plan_id"] == "plan-1"
    assert item["id_in_plan"] == "123"
    assert item["plan_program_id"] == "42"
    assert item["happen_day"] == "20260422"
    assert item["sort_no"] == 2
    assert item["workout_id"] == "42"
    assert item["workout_name"] == "Tempo Run"
    assert item["sport_name"] == "Running"
    assert item["workout"]["estimated_distance"] == 8000


def test_build_run_workout_payload_supports_distance_steps_and_repeats():
    payload = coros_api.build_run_workout_payload(
        "Track Session",
        [
            {
                "kind": "warmup",
                "target_type": "distance",
                "target_distance_meters": 3000,
                "intensity_type": 2,
                "intensity_value": 130,
                "intensity_value_extend": 145,
            },
            {
                "repeat": 4,
                "steps": [
                    {
                        "kind": "training",
                        "target_type": "distance",
                        "target_distance_meters": 1000,
                        "intensity_type": 2,
                        "intensity_value": 160,
                        "intensity_value_extend": 170,
                    },
                    {
                        "kind": "rest",
                        "target_type": "time",
                        "target_duration_seconds": 120,
                    },
                ],
            },
            {
                "kind": "cooldown",
                "target_type": "distance",
                "target_distance_meters": 2000,
            },
        ],
    )

    assert payload["sportType"] == 1
    assert payload["targetType"] == 5
    assert payload["estimatedDistance"] == 900000
    assert payload["estimatedTime"] == 480
    assert payload["exerciseNum"] == 5
    assert payload["exercises"][0]["exerciseType"] == 1
    assert payload["exercises"][0]["overview"] == "sid_run_warm_up_dist"
    assert payload["exercises"][1]["isGroup"] is True
    assert payload["exercises"][2]["exerciseType"] == 2
    assert payload["exercises"][3]["exerciseType"] == 4
    assert payload["exercises"][4]["exerciseType"] == 3


def test_apply_step_updates_recalculates_distance_summary():
    workout = {
        "name": "Track Session",
        "targetType": 5,
        "targetValue": 600000,
        "estimatedDistance": 600000,
        "estimatedTime": 0,
        "exercises": [
            {
                "id": "1",
                "name": "Warm-up",
                "targetType": 5,
                "targetValue": 200000,
                "isGroup": False,
            },
            {
                "id": "2",
                "name": "Rep",
                "targetType": 5,
                "targetValue": 100000,
                "isGroup": False,
            },
            {
                "id": "3",
                "name": "Cool-down",
                "targetType": 5,
                "targetValue": 300000,
                "isGroup": False,
            },
        ],
    }

    coros_api._apply_step_updates(
        workout,
        [{"step_name": "Rep", "target_distance_meters": 800}],
    )

    assert workout["exercises"][1]["targetType"] == 5
    assert workout["exercises"][1]["targetValue"] == 80000
    assert workout["estimatedDistance"] == 580000
    assert workout["targetValue"] == 580000


def test_build_run_workout_payload_rejects_unknown_step_kind():
    try:
        coros_api.build_run_workout_payload(
            "Broken Session",
            [{"kind": "swizzle", "target_type": "time", "target_duration_seconds": 60}],
        )
    except ValueError as exc:
        assert "Unsupported run step kind" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError for unsupported run step kind")


def test_normalize_activity_export_file_type_supports_names_and_enums():
    assert coros_api._normalize_activity_export_file_type("gpx") == 1
    assert coros_api._normalize_activity_export_file_type(" FIT ") == 4
    assert coros_api._normalize_activity_export_file_type(3) == 3

    with pytest.raises(ValueError):
        coros_api._normalize_activity_export_file_type("zip")


@pytest.mark.anyio
async def test_fetch_activity_export_url_uses_download_endpoint_params(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": "0000", "data": {"fileUrl": "https://example.com/run.gpx"}}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, params=None, headers=None):
            calls.append(("post", url, params, headers))
            return FakeResponse()

    auth = StoredAuth(
        access_token="token-1",
        user_id="user-1",
        region="us",
        timestamp=0,
        mobile_access_token=None,
        mobile_login_payload=None,
    )

    monkeypatch.setattr(coros_api.httpx, "AsyncClient", FakeAsyncClient)

    result = await coros_api.fetch_activity_export_url(auth, "abc123", 100, "gpx")

    assert result["file_type"] == "gpx"
    assert result["file_url"] == "https://example.com/run.gpx"
    assert calls == [
        (
            "post",
            "https://teamapi.coros.com/activity/detail/download",
            {"labelId": "abc123", "sportType": 100, "fileType": 1},
            coros_api._auth_headers(auth),
        )
    ]


@pytest.mark.anyio
async def test_export_activity_file_downloads_returned_file_url(monkeypatch, tmp_path):
    calls = []

    class FakeResponse:
        def __init__(self, *, json_body=None, content=b""):
            self._json_body = json_body
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._json_body

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, params=None, headers=None):
            calls.append(("post", url, params))
            return FakeResponse(
                json_body={"result": "0000", "data": {"fileUrl": "https://example.com/exported-file.gpx"}}
            )

        async def get(self, url):
            calls.append(("get", url))
            return FakeResponse(content=b"<gpx>example</gpx>")

    auth = StoredAuth(
        access_token="token-1",
        user_id="user-1",
        region="eu",
        timestamp=0,
        mobile_access_token=None,
        mobile_login_payload=None,
    )
    output_path = tmp_path / "session.gpx"

    monkeypatch.setattr(coros_api.httpx, "AsyncClient", FakeAsyncClient)

    result = await coros_api.export_activity_file(
        auth,
        "run-1",
        100,
        "gpx",
        str(output_path),
    )

    assert output_path.read_bytes() == b"<gpx>example</gpx>"
    assert result["downloaded"] is True
    assert result["output_path"] == str(output_path.resolve())
    assert calls == [
        (
            "post",
            "https://teameuapi.coros.com/activity/detail/download",
            {"labelId": "run-1", "sportType": 100, "fileType": 1},
        ),
        ("get", "https://example.com/exported-file.gpx"),
    ]
