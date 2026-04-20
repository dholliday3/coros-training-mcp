import os

import pytest

import traininghub_live_builder_catalog


pytestmark = pytest.mark.anyio


def _skip_unless_builder_live_enabled():
    if os.environ.get("COROS_MCP_LIVE_BUILDER") != "1":
        pytest.skip("Set COROS_MCP_LIVE_BUILDER=1 to run live Training Hub builder catalog tests.")


async def test_live_builder_catalog_captures_all_supported_sports_and_run_correlations():
    _skip_unless_builder_live_enabled()

    catalog = await traininghub_live_builder_catalog.build_catalog(headless=True)

    assert catalog["available_sports"] == [
        "Run",
        "Trail Run",
        "Bike",
        "Swim",
        "Strength",
        "Indoor Climb",
        "Bouldering",
    ]
    assert sorted(catalog["sports"]) == [
        "bike",
        "bouldering",
        "indoor_climb",
        "run",
        "strength",
        "swim",
        "trail_run",
    ]
    assert catalog["sports"]["run"]["exercise_options"] == ["Warm Up", "Training", "Rest", "Cool Down"]
    assert catalog["sports"]["trail_run"]["selected_sport_label"] == "Trail Run"
    assert catalog["sports"]["bike"]["selected_sport_label"] == "Bike"
    assert catalog["sports"]["swim"]["selected_sport_label"] == "Swim"
    assert catalog["sports"]["strength"]["selected_sport_label"] == "Strength"
    assert catalog["sports"]["indoor_climb"]["selected_sport_label"] == "Indoor Climb"
    assert catalog["sports"]["bouldering"]["selected_sport_label"] == "Bouldering"

    run_labels = [row["label"] for row in catalog["correlations"]["run"]["intensity_type_details"]]
    assert run_labels == [
        "% Max Heart Rate",
        "% Heart Rate Reserve",
        "% Lactate Threshold HR",
        "Heart Rate",
        "% Threshold Pace",
        "Pace",
        "% Effort Pace",
        "Effort Pace",
        "Power",
        "Cadence",
        "Not set",
    ]
