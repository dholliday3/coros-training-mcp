import traininghub_live_builder_catalog as extractor


def test_normalize_sport_key_handles_spaces_and_case():
    assert extractor.normalize_sport_key("Trail Run") == "trail_run"
    assert extractor.normalize_sport_key("Indoor Climb") == "indoor_climb"


def test_extract_first_exercise_returns_selected_keys():
    payload = {
        "exercises": [
            {
                "exerciseType": 2,
                "targetType": 5,
                "targetValue": 100000,
                "intensityType": 3,
                "overview": "sid_run_training",
            }
        ]
    }

    extracted = extractor.extract_first_exercise(payload, ["exerciseType", "targetType", "overview"])

    assert extracted == {
        "exerciseType": 2,
        "targetType": 5,
        "overview": "sid_run_training",
    }
