from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


TRAINING_HUB_INDEX_URL = "https://training.coros.com/"
LOCALE_BUNDLE_PATTERN = re.compile(
    r"https://static\.coros\.com/locale/coros-traininghub-v2/[^\"']+\.js(?:\?[^\"']+)?"
)
MAIN_BUNDLE_PATTERN = re.compile(
    r"https://static\.coros\.com/coros-traininghub-v2/public/main-[^\"']+\.js"
)

INLINE_DISPLAY_OVERRIDES = {
    "手动结束": "Manual End",
    "时间": "Time",
    "次数": "Count",
    "心率": "Heart Rate",
    "距离": "Distance",
    "负荷": "Training Load",
    "心率恢复": "HR Recovery",
    "累计上升": "Cumulative Climb",
    "线路": "Routes",
    "不休息": "No Rest",
}

INTENSITY_BASE_DISPLAY = {
    "notSet": "Not Set",
    "weight": "Weight",
    "heart": "Heart Rate",
    "pace": "Pace",
    "speed": "Speed",
    "swimmingStyle": "Swimming Style",
    "power": "Power",
    "cadence": "Cadence",
    "adjustedPace": "Effort Pace",
    "ftp": "FTP",
    "gradeSystem": "Grade System",
}

KNOWN_DISPLAY_STRINGS = [
    "Run",
    "Trail Run",
    "Bike",
    "Swim",
    "Strength",
    "Indoor Climb",
    "Bouldering",
    "Warm Up",
    "Training",
    "Cool Down",
    "Rest",
    "Time",
    "Distance",
    "Count",
    "Heart Rate",
    "Training Load",
    "HR Recovery",
    "Cumulative Climb",
    "Routes",
    "Not Set",
    "Not set",
    "Pace",
    "Effort Pace",
    "% Effort Pace",
    "% Threshold Pace",
    "% Max HR",
    "% HR Reserve",
    "% Threshold HR",
    "Power",
    "Cadence",
    "Speed",
]


@dataclass
class TrainingHubAssets:
    index_url: str
    locale_url: str
    main_url: str
    locale_text: str
    main_text: str


def _http_get(url: str) -> str:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def fetch_traininghub_assets() -> TrainingHubAssets:
    index_text = _http_get(TRAINING_HUB_INDEX_URL)

    locale_match = LOCALE_BUNDLE_PATTERN.search(index_text)
    if locale_match is None:
        raise ValueError("Could not locate Training Hub locale bundle URL.")

    main_match = MAIN_BUNDLE_PATTERN.search(index_text)
    if main_match is None:
        raise ValueError("Could not locate Training Hub main bundle URL.")

    locale_url = locale_match.group(0)
    main_url = main_match.group(0)
    return TrainingHubAssets(
        index_url=TRAINING_HUB_INDEX_URL,
        locale_url=locale_url,
        main_url=main_url,
        locale_text=_http_get(locale_url),
        main_text=_http_get(main_url),
    )


def parse_locale_bundle(locale_text: str) -> dict[str, str]:
    return dict(re.findall(r'"([^"]+)":\s*"((?:\\.|[^"])*)"', locale_text))


def _extract_object_literal(script_text: str, marker: str) -> str:
    start = script_text.find(marker)
    if start == -1:
        raise ValueError(f"Could not find marker {marker!r} in script.")

    brace_start = script_text.find("{", start)
    if brace_start == -1:
        raise ValueError(f"Could not find opening brace for marker {marker!r}.")

    depth = 0
    in_string = False
    escaped = False
    quote = ""

    for index in range(brace_start, len(script_text)):
        char = script_text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            continue

        if char in ('"', "'"):
            in_string = True
            quote = char
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return script_text[brace_start : index + 1]

    raise ValueError(f"Unterminated object literal for marker {marker!r}.")


def _to_python_literal(js_object: str) -> str:
    converted = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', js_object)
    converted = converted.replace("true", "True").replace("false", "False").replace("null", "None")
    return converted


def parse_simple_object(script_text: str, marker: str) -> dict[Any, Any]:
    literal = _extract_object_literal(script_text, marker)
    return ast.literal_eval(_to_python_literal(literal))


def parse_sport_category(script_text: str) -> dict[str, dict[str, Any]]:
    literal = _extract_object_literal(script_text, "sportCategory=")
    pattern = re.compile(
        r'(\w+):\{i18n:"([^"]+)"[^}]*?exerciseTypes:\[([^\]]*)\][^}]*?sportType:"([^"]+)"'
    )
    sport_category: dict[str, dict[str, Any]] = {}
    for name, i18n_key, exercise_types_raw, icon_name in pattern.findall(literal):
        exercise_types = re.findall(r'"([^"]+)"', exercise_types_raw)
        sport_category[name] = {
            "name": name,
            "i18n_key": i18n_key,
            "exercise_types": exercise_types,
            "icon_name": icon_name,
        }
    if not sport_category:
        raise ValueError("Could not parse sportCategory object.")
    return sport_category


def _resolve_display_token(token: str, locale_map: dict[str, str]) -> str:
    if token in locale_map:
        return locale_map[token]
    return INLINE_DISPLAY_OVERRIDES.get(token, token)


def _resolve_name_token(token: str, locale_map: dict[str, str]) -> str:
    return locale_map.get(token, token.replace("_", " "))


def _sorted_numeric_items(mapping: dict[Any, Any]) -> list[tuple[int, Any]]:
    items: list[tuple[int, Any]] = []
    for key, value in mapping.items():
        if isinstance(key, (int, float)):
            items.append((int(key), value))
        else:
            items.append((int(str(key)), value))
    items.sort(key=lambda item: item[0])
    return items


def build_registry(assets: TrainingHubAssets) -> dict[str, Any]:
    locale_map = parse_locale_bundle(assets.locale_text)

    target_type_name = parse_simple_object(assets.main_text, "targetTypeName=")
    target_type = parse_simple_object(assets.main_text, "targetType=")
    intensity_type_name = parse_simple_object(assets.main_text, "intensityTypeName=")
    intensity_unit_name = parse_simple_object(assets.main_text, "intensityUnitName=")
    rest_type_name = parse_simple_object(assets.main_text, "restTypeName=")
    rest_type = parse_simple_object(assets.main_text, "restType=")
    exercise_type_name = parse_simple_object(assets.main_text, "exerciseTypeName=")
    exercise_type_options = parse_simple_object(assets.main_text, "exerciseTypeOptions=")
    sport_type_name = parse_simple_object(assets.main_text, "sportTypeName=")
    sport_category = parse_sport_category(assets.main_text)

    registry = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "index_url": assets.index_url,
            "locale_url": assets.locale_url,
            "main_url": assets.main_url,
        },
        "enums": {
            "target_type": [],
            "intensity_type": [],
            "intensity_unit": [],
            "rest_type": [],
            "exercise_type": [],
            "sport_category": [],
            "sport_type": [],
        },
        "known_display_strings": {},
        "notes": [
            "This registry is extracted from public Training Hub frontend assets, not from the private COROS API payloads.",
            "Target/rest display labels sometimes appear inline in the main bundle as non-English literals and are normalized with a small override table.",
            "Intensity display is partially composite in COROS. intensityType is a base category; final UI labels may also depend on fields like hrType or percent flags that are not fully extracted here yet.",
        ],
    }

    for enum_id, enum_name in _sorted_numeric_items(target_type_name):
        meta = target_type.get(enum_name, {})
        registry["enums"]["target_type"].append(
            {
                "id": enum_id,
                "name": enum_name,
                "display_key": meta.get("i18n"),
                "display": _resolve_display_token(str(meta.get("i18n", enum_name)), locale_map),
            }
        )

    for enum_id, enum_name in _sorted_numeric_items(intensity_type_name):
        registry["enums"]["intensity_type"].append(
            {
                "id": enum_id,
                "name": enum_name,
                "display": INTENSITY_BASE_DISPLAY.get(str(enum_name), str(enum_name)),
                "source": "traininghub-main-bundle-base-category",
            }
        )

    for enum_id, unit_name in _sorted_numeric_items(intensity_unit_name):
        registry["enums"]["intensity_unit"].append(
            {
                "id": enum_id,
                "name": str(unit_name),
                "display": str(unit_name),
            }
        )

    for enum_id, enum_name in _sorted_numeric_items(rest_type_name):
        meta = rest_type.get(enum_name, {})
        registry["enums"]["rest_type"].append(
            {
                "id": enum_id,
                "name": enum_name,
                "display_key": meta.get("i18n"),
                "display": _resolve_display_token(str(meta.get("i18n", enum_name)), locale_map),
            }
        )

    for enum_id, enum_name in _sorted_numeric_items(exercise_type_name):
        meta = exercise_type_options.get(enum_name, {})
        registry["enums"]["exercise_type"].append(
            {
                "id": enum_id,
                "name": enum_name,
                "display_key": meta.get("i18n"),
                "display": _resolve_display_token(str(meta.get("i18n", enum_name)), locale_map),
                "color": meta.get("color"),
            }
        )

    for category_name, category in sorted(sport_category.items()):
        registry["enums"]["sport_category"].append(
            {
                "name": category_name,
                "display_key": category["i18n_key"],
                "display": _resolve_display_token(category["i18n_key"], locale_map),
                "exercise_types": category["exercise_types"],
                "icon_name": category["icon_name"],
            }
        )

    for enum_id, enum_name in _sorted_numeric_items(sport_type_name):
        registry["enums"]["sport_type"].append(
            {
                "id": enum_id,
                "name": str(enum_name),
                "display": _resolve_name_token(str(enum_name), locale_map),
            }
        )

    for label in KNOWN_DISPLAY_STRINGS:
        keys = sorted(key for key, value in locale_map.items() if value == label)
        if keys:
            registry["known_display_strings"][label] = keys

    return registry


def write_registry(output_path: Path) -> Path:
    assets = fetch_traininghub_assets()
    registry = build_registry(assets)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract COROS Training Hub enum metadata from public frontend assets."
    )
    parser.add_argument(
        "--output",
        default="docs/enums/traininghub-static-enums.json",
        help="Output JSON path relative to the repo root.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    written = write_registry(output_path)
    print(written)


if __name__ == "__main__":
    main()
