from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
ENUMS_DIR = REPO_ROOT / "docs" / "enums"
STATIC_ENUMS_PATH = ENUMS_DIR / "traininghub-static-enums.json"
LIVE_BUILDER_CATALOG_PATH = ENUMS_DIR / "traininghub-live-builder-catalog.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_workout_catalog() -> dict[str, Any]:
    return {
        "static_enums": _load_json(STATIC_ENUMS_PATH),
        "live_builder_catalog": _load_json(LIVE_BUILDER_CATALOG_PATH),
    }


def load_catalog_for_sport(sport: str) -> dict[str, Any]:
    catalog = load_workout_catalog()
    if not sport:
        return catalog

    normalized = sport.strip().lower()
    live_catalog = catalog.get("live_builder_catalog") or {}
    sports = live_catalog.get("sports") or {}

    matched_key = None
    for key in sports:
        sport_label = str((sports.get(key) or {}).get("label", ""))
        if key.lower() == normalized or sport_label.lower() == normalized:
            matched_key = key
            break

    filtered_live = None
    if matched_key is not None:
        filtered_live = dict(live_catalog)
        filtered_live["sports"] = {matched_key: sports[matched_key]}
        correlations = dict(live_catalog.get("correlations") or {})
        if matched_key in correlations:
            filtered_live["correlations"] = {matched_key: correlations[matched_key]}
        elif normalized in correlations:
            filtered_live["correlations"] = {normalized: correlations[normalized]}
        elif "correlations" in filtered_live:
            filtered_live["correlations"] = {}

    static_catalog = catalog.get("static_enums") or {}
    filtered_static = None
    if static_catalog:
        filtered_static = dict(static_catalog)
        enums = dict(static_catalog.get("enums") or {})
        sport_categories = enums.get("sport_category") or []
        sport_types = enums.get("sport_type") or []
        enums["sport_category"] = [
            item
            for item in sport_categories
            if str(item.get("name", "")).lower() == normalized
            or str(item.get("display", "")).lower() == normalized
        ]
        enums["sport_type"] = [
            item
            for item in sport_types
            if str(item.get("name", "")).lower() == normalized
            or str(item.get("display", "")).lower() == normalized
        ]
        filtered_static["enums"] = enums

    return {
        "static_enums": filtered_static,
        "live_builder_catalog": filtered_live,
    }
