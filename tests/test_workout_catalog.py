import json

import workout_catalog


def test_load_workout_catalog_reads_static_and_live_files(tmp_path, monkeypatch):
    static_path = tmp_path / "static.json"
    live_path = tmp_path / "live.json"
    static_path.write_text(json.dumps({"enums": {"sport_type": [{"name": "run", "display": "Run"}]}}), encoding="utf-8")
    live_path.write_text(json.dumps({"sports": {"run": {"label": "Run"}}}), encoding="utf-8")

    monkeypatch.setattr(workout_catalog, "STATIC_ENUMS_PATH", static_path)
    monkeypatch.setattr(workout_catalog, "LIVE_BUILDER_CATALOG_PATH", live_path)

    catalog = workout_catalog.load_workout_catalog()

    assert catalog["static_enums"]["enums"]["sport_type"][0]["display"] == "Run"
    assert catalog["live_builder_catalog"]["sports"]["run"]["label"] == "Run"


def test_load_catalog_for_sport_filters_live_and_static_entries(tmp_path, monkeypatch):
    static_path = tmp_path / "static.json"
    live_path = tmp_path / "live.json"
    static_path.write_text(
        json.dumps(
            {
                "enums": {
                    "sport_category": [
                        {"name": "run", "display": "Run"},
                        {"name": "bike", "display": "Bike"},
                    ],
                    "sport_type": [
                        {"name": "Run", "display": "Run"},
                        {"name": "Bike", "display": "Bike"},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    live_path.write_text(
        json.dumps(
            {
                "sports": {
                    "run": {"label": "Run"},
                    "bike": {"label": "Bike"},
                },
                "correlations": {
                    "run": {"intensity_type_details": [{"label": "Pace"}]},
                    "bike": {"intensity_type_details": [{"label": "Power"}]},
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workout_catalog, "STATIC_ENUMS_PATH", static_path)
    monkeypatch.setattr(workout_catalog, "LIVE_BUILDER_CATALOG_PATH", live_path)

    catalog = workout_catalog.load_catalog_for_sport("Run")

    assert list(catalog["live_builder_catalog"]["sports"]) == ["run"]
    assert list(catalog["live_builder_catalog"]["correlations"]) == ["run"]
    assert catalog["static_enums"]["enums"]["sport_category"] == [{"name": "run", "display": "Run"}]
    assert catalog["static_enums"]["enums"]["sport_type"] == [{"name": "Run", "display": "Run"}]
