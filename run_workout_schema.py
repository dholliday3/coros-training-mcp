from __future__ import annotations

from typing import Any

from pace_parser import parse_pace
from workout_catalog import load_catalog_for_sport


RUN_KIND_ALIASES = {
    "warmup": "warmup",
    "warm-up": "warmup",
    "warm up": "warmup",
    "training": "training",
    "train": "training",
    "interval": "interval",
    "interval training": "interval",
    "rest": "rest",
    "cooldown": "cooldown",
    "cool-down": "cooldown",
    "cool down": "cooldown",
}

RUN_TARGET_TYPE_ALIASES = {
    "time": "time",
    "distance": "distance",
}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    return int(value)


def _load_run_catalog() -> dict[str, Any]:
    try:
        catalog = load_catalog_for_sport("run")
    except Exception:
        return {}
    return ((catalog.get("live_builder_catalog") or {}).get("correlations") or {}).get("run") or {}


def _intensity_presets() -> dict[str, dict[str, Any]]:
    run_catalog = _load_run_catalog()
    presets: dict[str, dict[str, Any]] = {}
    for item in run_catalog.get("intensity_type_details") or []:
        label = str(item.get("label", "")).strip()
        payload = dict(item.get("payload") or {})
        if not label or not payload:
            continue
        preset: dict[str, Any] = {}
        field_map = {
            "intensityType": "intensity_type",
            "hrType": "hr_type",
            "isIntensityPercent": "is_intensity_percent",
            "intensityPercent": "intensity_percent",
            "intensityPercentExtend": "intensity_percent_extend",
            "intensityValue": "intensity_value",
            "intensityValueExtend": "intensity_value_extend",
            "intensityDisplayUnit": "intensity_display_unit",
        }
        for source, target in field_map.items():
            if source not in payload:
                continue
            value = payload[source]
            if target == "is_intensity_percent":
                preset[target] = _coerce_bool(value)
            elif target == "intensity_display_unit":
                preset[target] = _int_or_none(value)
            elif target in {"intensity_type", "hr_type", "intensity_value", "intensity_value_extend"}:
                preset[target] = _int_or_none(value)
            else:
                preset[target] = value
        presets[label] = preset
    return presets


RUN_INTENSITY_PRESETS = _intensity_presets()


def normalize_run_step_fields(step: dict[str, Any], *, allow_selectors: bool) -> dict[str, Any]:
    normalized = dict(step)

    raw_kind = normalized.get("kind")
    if raw_kind is not None:
        kind_key = str(raw_kind).strip().lower()
        if kind_key not in RUN_KIND_ALIASES:
            raise ValueError(f"Unsupported run step kind: {raw_kind!r}")
        normalized["kind"] = RUN_KIND_ALIASES[kind_key]

    raw_target_type = normalized.get("target_type")
    if isinstance(raw_target_type, str):
        target_key = raw_target_type.strip().lower()
        if target_key in RUN_TARGET_TYPE_ALIASES:
            normalized["target_type"] = RUN_TARGET_TYPE_ALIASES[target_key]

    intensity_label = normalized.pop("intensity_label", None)
    if intensity_label is not None:
        label = str(intensity_label).strip()
        preset = RUN_INTENSITY_PRESETS.get(label)
        if preset is None:
            supported = ", ".join(sorted(RUN_INTENSITY_PRESETS))
            raise ValueError(f"Unsupported run intensity_label: {label!r}. Supported labels: {supported}")
        for key, value in preset.items():
            normalized.setdefault(key, value)
        normalized["intensity_label"] = label

    pace_input = normalized.pop("pace", None)
    if pace_input is not None and pace_input != "":
        pace_fields = parse_pace(pace_input)
        for key, value in pace_fields.items():
            # Explicit raw fields win over pace parsing if both are given.
            normalized.setdefault(key, value)

    for key in (
        "target_duration_seconds",
        "target_distance_meters",
        "target_value",
        "target_display_unit",
        "intensity_type",
        "hr_type",
        "intensity_value",
        "intensity_value_extend",
        "intensity_display_unit",
        "rest_type",
        "rest_value",
        "sets",
    ):
        if key in normalized and normalized[key] not in (None, ""):
            normalized[key] = _int_or_none(normalized[key])

    for key in ("intensity_percent", "intensity_percent_extend"):
        if key in normalized and normalized[key] not in (None, ""):
            normalized[key] = float(normalized[key])

    if "is_intensity_percent" in normalized:
        normalized["is_intensity_percent"] = _coerce_bool(normalized["is_intensity_percent"])

    if allow_selectors:
        selector_keys = {"step_index", "step_id", "step_name"}
        if not selector_keys.intersection(normalized):
            raise ValueError("Run step updates require one of: step_index, step_id, step_name.")

    return normalized


def get_run_workout_schema() -> dict[str, Any]:
    run_catalog = _load_run_catalog()
    create_step_fields = [
        {"name": "kind", "required": True, "description": "Run step kind.", "allowed_values": ["warmup", "training", "rest", "cooldown", "interval"]},
        {"name": "name", "required": False, "description": "Step label."},
        {"name": "overview", "required": False, "description": "Raw COROS overview key. Usually omit this and use the default for the chosen kind/target type."},
        {"name": "target_type", "required": True, "description": "Step target type.", "allowed_values": ["time", "distance"]},
        {"name": "target_duration_seconds", "required": False, "description": "Required for time targets."},
        {"name": "target_distance_meters", "required": False, "description": "Required for distance targets."},
        {"name": "target_value", "required": False, "description": "Raw COROS target value alternative to the friendly time/distance fields."},
        {"name": "target_display_unit", "required": False, "description": "Raw COROS target display unit."},
        {"name": "intensity_label", "required": False, "description": "Friendly run intensity label from the live Training Hub builder.", "allowed_values": list(RUN_INTENSITY_PRESETS)},
        {"name": "pace", "required": False, "description": "Human pace string, e.g. '4:05/km', '4:05-4:15/km', '5:30/mi', '5:30-5:45/mi'. Expands to intensity_type=3 plus ms/km intensity_value / intensity_value_extend. Omitted if explicit intensity_value fields are provided."},
        {"name": "intensity_type", "required": False, "description": "Raw COROS intensity type."},
        {"name": "hr_type", "required": False, "description": "Raw COROS HR subtype used by heart-rate intensity labels."},
        {"name": "is_intensity_percent", "required": False, "description": "Whether intensity is expressed as a percent-based range."},
        {"name": "intensity_percent", "required": False, "description": "Raw COROS lower percent bound."},
        {"name": "intensity_percent_extend", "required": False, "description": "Raw COROS upper percent bound."},
        {"name": "intensity_value", "required": False, "description": "Raw COROS lower intensity value."},
        {"name": "intensity_value_extend", "required": False, "description": "Raw COROS upper intensity value."},
        {"name": "intensity_display_unit", "required": False, "description": "Raw COROS intensity display unit."},
        {"name": "rest_type", "required": False, "description": "Raw COROS rest type."},
        {"name": "rest_value", "required": False, "description": "Raw COROS rest value."},
        {"name": "sets", "required": False, "description": "COROS set count for the step."},
    ]
    repeat_group_fields = [
        {"name": "repeat", "required": True, "description": "Repeat count."},
        {"name": "name", "required": False, "description": "Optional group label."},
        {"name": "overview", "required": False, "description": "Optional raw COROS overview key for the group header."},
        {"name": "rest_type", "required": False, "description": "Raw COROS group rest type."},
        {"name": "rest_value", "required": False, "description": "Raw COROS group rest value."},
        {"name": "steps", "required": True, "description": "Nested plain run steps using the same plain-step schema."},
    ]
    update_selector_fields = [
        {"name": "step_index", "required": False, "description": "Zero-based step index in the fetched workout."},
        {"name": "step_id", "required": False, "description": "Existing COROS step ID."},
        {"name": "step_name", "required": False, "description": "Existing step name."},
    ]
    return {
        "notes": [
            "create_run_workout plain steps and update_run_workout step_updates now share the same run-step field vocabulary.",
            "update_run_workout requires a selector field plus any create-style run-step fields you want to change.",
            "For intensity_label values, the MCP uses checked-in live Training Hub correlations to fill the raw COROS fields.",
        ],
        "create_run_workout": {
            "plain_step_fields": create_step_fields,
            "repeat_group_fields": repeat_group_fields,
        },
        "update_run_workout": {
            "selector_fields": update_selector_fields,
            "patch_fields": create_step_fields,
        },
        "run_builder_labels": {
            "exercise_types": [item.get("label") for item in run_catalog.get("exercise_type_details") or []],
            "target_types": [item.get("label") for item in run_catalog.get("target_type_details") or []],
            "intensity_types": [item.get("label") for item in run_catalog.get("intensity_type_details") or []],
        },
        "run_intensity_presets": RUN_INTENSITY_PRESETS,
    }
