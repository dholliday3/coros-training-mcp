"""
Coros MCP Server — Sleep, HRV, and training data via the unofficial Coros API.

Usage:
    python server.py

MCP config (Claude Code):
    claude mcp add coros \\
      -e COROS_EMAIL=you@example.com \\
      -e COROS_PASSWORD=yourpass \\
      -e COROS_REGION=eu \\
      -- python /path/to/coros-mcp/server.py

Alternatively, create a .env file in the project directory with the same
variables. If COROS_EMAIL and COROS_PASSWORD are set (via env or .env), the
server authenticates automatically on the first request and re-authenticates
transparently whenever the stored token is expired or rejected.
"""

import os
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastmcp import FastMCP

import coros_api
from coros_api import TOKEN_TTL_MS
from run_workout_schema import get_run_workout_schema as build_run_workout_schema, normalize_run_step_fields
from workout_catalog import load_catalog_for_sport, load_workout_catalog

load_dotenv()

mcp = FastMCP("coros-mcp")


async def _get_auth():
    """Return stored auth, auto-logging in from env vars if the token is missing/expired."""
    auth = coros_api.get_stored_auth()
    if auth is None:
        auth = await coros_api.try_auto_login()
    return auth


async def _run_with_auth(fn, auth, *args, **kwargs):
    """Call fn(auth, …). On exception, re-login from env vars and retry once."""
    try:
        return await fn(auth, *args, **kwargs)
    except Exception:
        new_auth = await coros_api.try_auto_login()
        if new_auth is None:
            raise
        return await fn(new_auth, *args, **kwargs)


def _summarize_steps(steps: list[dict]) -> tuple[float, int]:
    """Return (total_minutes, steps_count) for a workout step list."""
    total_minutes = 0.0
    steps_count = 0
    for s in steps:
        if "repeat" in s:
            sub_mins = sum(sub["duration_minutes"] for sub in s["steps"])
            total_minutes += sub_mins * s["repeat"]
            steps_count += 1 + len(s["steps"])
        else:
            total_minutes += s["duration_minutes"]
            steps_count += 1
    return total_minutes, steps_count


def _summarize_run_steps(steps: list[dict]) -> tuple[float, float, int]:
    """Return (distance_meters, duration_seconds, steps_count) for run steps."""
    total_distance = 0.0
    total_time = 0.0
    steps_count = 0
    for step in steps:
        if "repeat" in step:
            repeat = int(step["repeat"])
            sub_distance, sub_time, sub_steps = _summarize_run_steps(step.get("steps") or [])
            total_distance += sub_distance * repeat
            total_time += sub_time * repeat
            steps_count += 1 + sub_steps
        else:
            if "target_distance_meters" in step:
                total_distance += float(step["target_distance_meters"])
            if "target_duration_seconds" in step:
                total_time += float(step["target_duration_seconds"])
            elif str(step.get("target_type", "")).lower() == "time" and "target_value" in step:
                total_time += float(step["target_value"])
            elif str(step.get("target_type", "")).lower() == "distance" and "target_value" in step:
                total_distance += float(step["target_value"])
            steps_count += 1
    return total_distance, total_time, steps_count


# ---------------------------------------------------------------------------
# Tool: authenticate_coros
# ---------------------------------------------------------------------------

@mcp.tool()
async def authenticate_coros(
    email: str,
    password: str,
    region: str = "eu",
) -> dict:
    """
    Authenticate with the Coros Training Hub API and store the access token.

    Parameters
    ----------
    email : str
        Coros account email address.
    password : str
        Coros account password (plain text — hashed with MD5 before sending).
    region : str
        "eu" (default) or "us".  EU users must use "eu" — tokens are
        region-bound (EU tokens only work on teameuapi.coros.com).

    Returns
    -------
    dict with keys: authenticated, user_id, region, message
    """
    try:
        auth = await coros_api.login(email, password, region, skip_mobile=True)
        return {
            "authenticated": True,
            "user_id": auth.user_id,
            "region": auth.region,
            "message": "Token stored securely (keyring or encrypted file)",
        }
    except Exception as exc:
        return {
            "authenticated": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Tool: authenticate_coros_mobile
# ---------------------------------------------------------------------------

@mcp.tool()
async def authenticate_coros_mobile(
    email: str,
    password: str,
    region: str = "eu",
) -> dict:
    """
    Authenticate with the Coros mobile API only and store the mobile token.

    This is needed for sleep data (deep/light/REM/awake phases) which is
    only available through the mobile API (apieu.coros.com), not the
    Training Hub web API.

    Parameters
    ----------
    email : str
        Coros account email address.
    password : str
        Coros account password (plain text — encrypted before sending).
    region : str
        "eu" (default) or "us".

    Returns
    -------
    dict with keys: authenticated, region, message
    """
    try:
        auth = await coros_api.login_mobile(email, password, region)
        return {
            "authenticated": True,
            "user_id": auth.user_id or "(web auth required for user_id)",
            "region": auth.region,
            "message": "Mobile token stored. Sleep data is now available.",
        }
    except Exception as exc:
        return {
            "authenticated": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Tool: check_coros_auth
# ---------------------------------------------------------------------------

@mcp.tool()
async def check_coros_auth() -> dict:
    """
    Check whether valid Coros access tokens are stored locally.

    Returns
    -------
    dict with keys: authenticated, user_id, region, expires_in_hours,
    mobile_authenticated, mobile_token_status
    """
    auth = coros_api.get_stored_auth()
    if auth is None:
        return {
            "authenticated": False,
            "mobile_authenticated": False,
            "message": "No valid token found. Call authenticate_coros first.",
        }

    age_ms = int(time.time() * 1000) - auth.timestamp
    remaining_ms = TOKEN_TTL_MS - age_ms
    remaining_hours = round(remaining_ms / 3_600_000, 1)

    has_mobile = bool(auth.mobile_access_token)
    if has_mobile:
        mobile_status = "present (refresh via stored payload)"
    elif auth.mobile_login_payload:
        mobile_status = "expired (can auto-refresh)"
    else:
        mobile_status = "missing (run auth or auth-mobile)"

    return {
        "authenticated": bool(auth.access_token),
        "user_id": auth.user_id,
        "region": auth.region,
        "expires_in_hours": remaining_hours,
        "mobile_authenticated": has_mobile,
        "mobile_token_status": mobile_status,
    }


# ---------------------------------------------------------------------------
# Tool: get_daily_metrics
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_daily_metrics(weeks: int = 4) -> dict:
    """
    Retrieve nightly HRV and daily metrics from Coros for a configurable
    time range (up to 24 weeks).

    Uses the /analyse/dayDetail/query endpoint which returns daily records
    including HRV, resting heart rate, training load, and fatigue rate.

    Parameters
    ----------
    weeks : int
        Number of weeks to fetch (1–24). Default: 4.

    Returns
    -------
    dict with keys: records (list of daily records), count, date_range
    Each record contains:
      - date: YYYYMMDD
      - avg_sleep_hrv: average nightly RMSSD in ms
      - baseline: rolling baseline RMSSD
      - rhr: resting heart rate (bpm)
      - training_load: daily training load
      - training_load_ratio: acute/chronic training load ratio
      - tired_rate: fatigue rate
      - ati: acute training index
      - cti: chronic training index
      - distance: daily distance in meters
      - duration: daily duration in seconds
      - vo2max: VO2 Max (only available for last ~28 days)
      - lthr: lactate threshold heart rate (bpm)
      - ltsp: lactate threshold pace (s/km)
      - stamina_level: base fitness level
      - stamina_level_7d: 7-day fitness trend
    """
    auth = await _get_auth()
    if auth is None:
        return {
            "error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.",
            "records": [],
        }

    weeks = max(1, min(weeks, 24))
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(weeks=weeks)
    start_day = start_dt.strftime("%Y%m%d")
    end_day = end_dt.strftime("%Y%m%d")

    try:
        records = await _run_with_auth(coros_api.fetch_daily_records, auth, start_day, end_day)
        return {
            "records": [r.model_dump() for r in records],
            "count": len(records),
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return {"error": str(exc), "records": []}


# ---------------------------------------------------------------------------
# Tool: get_sleep_data
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_sleep_data(weeks: int = 4) -> dict:
    """
    Fetch nightly sleep data from Coros for a configurable time range.

    Returns per-night sleep stage breakdown (deep, light, REM, awake) and
    sleep heart rate for each night.  Data comes from the Coros mobile API
    (apieu.coros.com) which is separate from the Training Hub web API.

    Parameters
    ----------
    weeks : int
        Number of weeks to fetch (1–52). Default: 4.

    Returns
    -------
    dict with keys: records (list of nightly records), count, date_range
    Each record contains:
      - date: YYYYMMDD (the morning date — sleep started the night before)
      - total_duration_minutes: total sleep in minutes
      - phases.deep_minutes: deep sleep
      - phases.light_minutes: light sleep
      - phases.rem_minutes: REM sleep
      - phases.awake_minutes: time awake during the night
      - phases.nap_minutes: daytime nap time (if any)
      - avg_hr: average heart rate during sleep
      - min_hr: minimum heart rate during sleep
      - max_hr: maximum heart rate during sleep
      - quality_score: sleep quality score (null if not computed)
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "records": []}

    weeks = max(1, min(weeks, 52))
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(weeks=weeks)
    start_day = start_dt.strftime("%Y%m%d")
    end_day = end_dt.strftime("%Y%m%d")

    try:
        records = await _run_with_auth(coros_api.fetch_sleep, auth, start_day, end_day)
        return {
            "records": [r.model_dump() for r in records],
            "count": len(records),
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return {"error": str(exc), "records": []}


# ---------------------------------------------------------------------------
# Tool: list_activities
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_activities(
    start_day: str,
    end_day: str,
    page: int = 1,
    size: int = 30,
) -> dict:
    """
    List Coros activities for a date range.

    Parameters
    ----------
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.
    page : int
        Page number (default 1).
    size : int
        Results per page (default 30, max 100).

    Returns
    -------
    dict with keys: activities (list), total_count, page
    Each activity contains: activity_id, name, sport_type, sport_name,
    start_time, end_time, duration_seconds, distance_meters, avg_hr, max_hr,
    calories, training_load, avg_power, normalized_power, elevation_gain
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "activities": []}
    try:
        activities, total = await _run_with_auth(coros_api.fetch_activities, auth, start_day, end_day, page, size)
        return {
            "activities": [a.model_dump() for a in activities],
            "total_count": total,
            "page": page,
        }
    except Exception as exc:
        return {"error": str(exc), "activities": []}


# ---------------------------------------------------------------------------
# Tool: get_activity_detail
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_activity_detail(activity_id: str, sport_type: int = 0) -> dict:
    """
    Fetch full detail for a single Coros activity.

    Parameters
    ----------
    activity_id : str
        The activity ID (labelId) from list_activities.
    sport_type : int
        Sport type ID from list_activities (e.g. 200=Road Bike, 201=Indoor Cycling,
        100=Running). Required for the API call to succeed.

    Returns
    -------
    dict with full activity data including laps, HR zones, power metrics,
    elevation, and all available sport-specific fields.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _run_with_auth(coros_api.fetch_activity_detail, auth, activity_id, sport_type)
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: export_activity_file
# ---------------------------------------------------------------------------

@mcp.tool()
async def export_activity_file(
    activity_id: str,
    sport_type: int,
    file_type: str = "gpx",
    output_path: str | None = None,
) -> dict:
    """
    Export a completed Coros activity file and save it locally.

    Parameters
    ----------
    activity_id : str
        The activity ID (labelId) from list_activities.
    sport_type : int
        Sport type ID from list_activities (for example 100=Running, 200=Road Bike).
    file_type : str
        Export format: gpx, fit, tcx, kml, or csv. Default: gpx.
    output_path : str | None
        Optional local destination path. When omitted, the server saves the file
        in the current working directory using the exported filename.

    Returns
    -------
    dict with keys: activity_id, sport_type, file_type, file_url, output_path, downloaded
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        return await _run_with_auth(
            coros_api.export_activity_file,
            auth,
            activity_id,
            sport_type,
            file_type,
            output_path,
        )
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: list_workouts
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_workouts() -> dict:
    """
    List all saved library workout programs in the Coros account.

    Returns
    -------
    dict with keys: workouts (list), count
    Each workout contains: id, name, sport_type, sport_name,
    estimated_time_seconds, exercise_count, exercises (list of steps with
    name, duration_seconds, power_low_w, power_high_w)
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "workouts": []}
    try:
        workouts = await _run_with_auth(coros_api.fetch_workouts, auth)
        return {"workouts": workouts, "count": len(workouts)}
    except Exception as exc:
        return {"error": str(exc), "workouts": []}


# ---------------------------------------------------------------------------
# Tool: get_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_workout(workout_id: str) -> dict:
    """
    Fetch one saved workout program in detail.

    Parameters
    ----------
    workout_id : str
        Workout ID from list_workouts or a scheduled workout entry.

    Returns
    -------
    dict with key: workout
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        workout = await _run_with_auth(coros_api.fetch_workout, auth, workout_id)
        return {"workout": workout}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: get_workout_builder_catalog
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_workout_builder_catalog(sport: str = "") -> dict:
    """
    Return the checked-in workout builder catalog and enum registry.

    The catalog combines:
    - static Training Hub enum extraction from public frontend bundles
    - live builder correlations captured from Training Hub draft calculate payloads

    Parameters
    ----------
    sport : str
        Optional sport filter such as `run`, `bike`, `strength`, `trail run`,
        `swim`, `indoor climb`, or `bouldering`.

    Returns
    -------
    dict with key: catalog
    """
    try:
        catalog = load_catalog_for_sport(sport) if sport else load_workout_catalog()
        return {"catalog": catalog}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: get_run_workout_schema
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_run_workout_schema() -> dict:
    """
    Return the shared run-step contract used by create_run_workout and update_run_workout.

    This includes:
    - the plain-step fields accepted by create_run_workout
    - the selector + patch fields accepted by update_run_workout
    - the checked-in live Training Hub intensity labels and their raw COROS presets
    """
    try:
        return {"schema": build_run_workout_schema()}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: create_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_workout(
    name: str,
    steps: list[dict],
    sport_type: int = 2,
) -> dict:
    """
    Create a new structured workout in the Coros account.

    The workout appears in the Coros app under Workouts and can be synced
    to the watch for guided execution.

    Parameters
    ----------
    name : str
        Workout name (e.g. "Z2 Erholung 60min").
    steps : list[dict]
        List of workout steps. Each step is either a plain step or a repeat group.

        Plain step:
          - name (str): step label, e.g. "10:00 Einfahren"
          - duration_minutes (float): step duration in minutes
          - power_low_w (int): lower power target in watts
          - power_high_w (int): upper power target in watts

        Repeat group (for intervals):
          - repeat (int): number of repetitions
          - steps (list[dict]): sub-steps (same format as plain steps)

        Example:
          [
            {"name": "Warm-up", "duration_minutes": 10, "power_low_w": 148, "power_high_w": 192},
            {"repeat": 3, "steps": [
              {"name": "Sweetspot", "duration_minutes": 10, "power_low_w": 265, "power_high_w": 285},
              {"name": "Recovery", "duration_minutes": 3, "power_low_w": 150, "power_high_w": 175},
            ]},
            {"name": "Cool-down", "duration_minutes": 10, "power_low_w": 100, "power_high_w": 165},
          ]
    sport_type : int
        Sport type ID. Default 2 = Indoor Cycling (Rollen).
        Use 200 for Road Bike (outdoor), 201 for Indoor Cycling (alt).

    Returns
    -------
    dict with keys: workout_id, name, total_minutes, steps_count, message
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        workout_id = await _run_with_auth(coros_api.create_workout, auth, name, steps, sport_type)
        total_minutes, steps_count = _summarize_steps(steps)
        return {
            "workout_id": workout_id,
            "name": name,
            "total_minutes": total_minutes,
            "steps_count": steps_count,
            "message": "Workout created. Open Coros app → Workouts to sync to watch.",
        }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: create_run_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_run_workout(
    name: str,
    steps: list[dict],
) -> dict:
    """
    Create a running workout with explicit run-step semantics.

    Use `get_run_workout_schema` for the exact accepted fields.

    Each plain step uses the shared run-step contract:
    - `kind`: `warmup`, `training`, `rest`, `cooldown`, `interval`
    - `target_type`: `time` or `distance`
    - `target_duration_seconds` or `target_distance_meters`

    Optional fields include:
    - `name`
    - `overview`
    - `intensity_label`
    - raw intensity fields like `intensity_type`, `hr_type`,
      `is_intensity_percent`, `intensity_percent`,
      `intensity_percent_extend`, `intensity_value`,
      `intensity_value_extend`, `intensity_display_unit`
    - `rest_type`
    - `rest_value`
    - `sets`

    Repeat groups use:
    - `repeat`
    - `steps`

    Repeat groups use:
    - `repeat`
    - `steps`

    Notes:
    - `intensity_label` can now use the checked-in live Training Hub labels such as
      `Pace`, `% Threshold Pace`, `Heart Rate`, or `% Max Heart Rate`.
    - The tool sets COROS running `sportType = 1`.
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        normalized_steps = [
            {
                **normalize_run_step_fields(step, allow_selectors=False),
                "steps": [normalize_run_step_fields(sub, allow_selectors=False) for sub in (step.get("steps") or [])],
            }
            if "repeat" in step
            else normalize_run_step_fields(step, allow_selectors=False)
            for step in steps
        ]
        workout_id = await _run_with_auth(coros_api.create_run_workout, auth, name, normalized_steps)
        distance_meters, duration_seconds, steps_count = _summarize_run_steps(normalized_steps)
        return {
            "workout_id": workout_id,
            "name": name,
            "sport_type": 1,
            "sport_name": "Running",
            "estimated_distance_meters": distance_meters or None,
            "estimated_time_seconds": duration_seconds or None,
            "steps_count": steps_count,
            "message": "Run workout created. Open Coros app → Workouts to sync to watch.",
        }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: update_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def update_workout(
    workout_id: str,
    name: str = "",
    estimated_distance_meters: float | None = None,
    estimated_time_seconds: int | None = None,
    step_updates: list[dict] | None = None,
    delete_original: bool = False,
) -> dict:
    """
    Clone an existing workout, apply edits, and create a replacement workout.

    This does not mutate the original workout in place. The replacement workout
    is created in the library, and the caller can optionally delete the old
    workout afterward.

    Parameters
    ----------
    workout_id : str
        Existing workout ID from list_workouts.
    name : str
        Optional replacement workout name.
    estimated_distance_meters : float | None
        Optional top-level estimated distance in meters.
    estimated_time_seconds : int | None
        Optional top-level estimated time in seconds.
    step_updates : list[dict] | None
        Per-step patches identified by one of:
        - step_index
        - step_id
        - step_name

        Supported update keys:
        - name
        - overview
        - target_type
        - target_value
        - target_distance_meters
        - target_duration_seconds
        - target_display_unit
        - intensity_type
        - intensity_value
        - intensity_value_extend
        - intensity_display_unit
        - rest_type
        - rest_value
        - sets
    delete_original : bool
        Whether to delete the original workout after the replacement is created.

    Returns
    -------
    dict with keys: old_workout_id, new_workout_id, workout
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    try:
        result = await _run_with_auth(
            coros_api.clone_and_patch_workout,
            auth,
            workout_id,
            name=name or None,
            estimated_distance_meters=estimated_distance_meters,
            estimated_time_seconds=estimated_time_seconds,
            step_updates=step_updates or [],
        )
    except Exception as exc:
        return {"error": str(exc)}

    deleted_original = False
    if delete_original:
        try:
            await _run_with_auth(coros_api.delete_workout, auth, workout_id)
            deleted_original = True
        except Exception as exc:
            result["warning"] = f"Replacement was created, but deleting the original workout failed: {exc}"

    result["deleted_original"] = deleted_original
    return result


# ---------------------------------------------------------------------------
# Tool: update_run_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def update_run_workout(
    workout_id: str,
    name: str = "",
    estimated_distance_meters: float | None = None,
    estimated_time_seconds: int | None = None,
    step_updates: list[dict] | None = None,
    delete_original: bool = False,
) -> dict:
    """
    Clone a running workout, apply run-specific edits, and create a replacement.

    Use `get_run_workout_schema` for the exact accepted fields.

    Each update item requires one selector:
    - `step_index`
    - `step_id`
    - `step_name`

    After that, it accepts the same run-step fields as create_run_workout,
    including `kind`, `target_type`, `target_duration_seconds`,
    `target_distance_meters`, `intensity_label`, and the raw COROS intensity fields.
    """
    normalized_updates = [normalize_run_step_fields(p, allow_selectors=True) for p in (step_updates or [])]
    return await update_workout(
        workout_id=workout_id,
        name=name,
        estimated_distance_meters=estimated_distance_meters,
        estimated_time_seconds=estimated_time_seconds,
        step_updates=normalized_updates,
        delete_original=delete_original,
    )


# ---------------------------------------------------------------------------
# Tool: delete_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def delete_workout(
    workout_id: str,
) -> dict:
    """
    Delete a workout program from the Coros account.

    Parameters
    ----------
    workout_id : str
        The workout ID to delete (from list_workouts).

    Returns
    -------
    dict with keys: deleted, workout_id, message
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        await _run_with_auth(coros_api.delete_workout, auth, workout_id)
        return {
            "deleted": True,
            "workout_id": workout_id,
            "message": "Workout deleted.",
        }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: list_planned_activities
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_planned_activities(
    start_day: str,
    end_day: str,
) -> dict:
    """
    List planned (scheduled) activities from the Coros training calendar.

    Parameters
    ----------
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.

    Returns
    -------
    dict with keys: activities (list of raw scheduled items), count, date_range
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "activities": []}
    try:
        items = await _run_with_auth(coros_api.fetch_schedule, auth, start_day, end_day)
        return {
            "activities": items,
            "count": len(items),
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return {"error": str(exc), "activities": []}


# ---------------------------------------------------------------------------
# Tool: list_scheduled_workouts
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_scheduled_workouts(
    start_day: str,
    end_day: str,
) -> dict:
    """
    List scheduled workout entries in a calendar-friendly format.

    These are calendar occurrences, not just library workouts. Each scheduled
    item carries plan-specific identifiers needed for move/remove/replace flows.

    Parameters
    ----------
    start_day : str
        Start date in YYYYMMDD format.
    end_day : str
        End date in YYYYMMDD format.

    Returns
    -------
    dict with keys: scheduled_workouts, count, date_range
    """
    auth = await _get_auth()
    if auth is None:
        return {
            "error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.",
            "scheduled_workouts": [],
        }
    try:
        items = await _run_with_auth(coros_api.fetch_scheduled_workouts, auth, start_day, end_day)
        return {
            "scheduled_workouts": items,
            "count": len(items),
            "date_range": f"{start_day} – {end_day}",
        }
    except Exception as exc:
        return {"error": str(exc), "scheduled_workouts": []}


# ---------------------------------------------------------------------------
# Tool: schedule_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def schedule_workout(
    workout_id: str,
    happen_day: str,
    sort_no: int = 1,
) -> dict:
    """
    Add an existing workout from the library to the Coros training calendar.

    Parameters
    ----------
    workout_id : str
        ID of the workout to schedule (from list_workouts or create_workout).
    happen_day : str
        Date in YYYYMMDD format.
    sort_no : int
        Order within the day if multiple workouts are scheduled (default 1).

    Returns
    -------
    dict with keys: scheduled, workout_id, happen_day
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        await _run_with_auth(coros_api.schedule_workout, auth, workout_id, happen_day, sort_no)
        return {"scheduled": True, "workout_id": workout_id, "happen_day": happen_day}
    except Exception as exc:
        return {"error": str(exc), "scheduled": False}


# ---------------------------------------------------------------------------
# Tool: remove_scheduled_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def remove_scheduled_workout(
    plan_id: str,
    id_in_plan: str,
    plan_program_id: str = "",
) -> dict:
    """
    Remove a scheduled workout from the Coros training calendar.

    Parameters
    ----------
    plan_id : str
        Top-level plan ID — the 'id' field returned by list_planned_activities.
    id_in_plan : str
        The entity's idInPlan value from list_planned_activities.
    plan_program_id : str
        The entity's planProgramId (leave empty to use id_in_plan).

    Returns
    -------
    dict with keys: removed, plan_id, id_in_plan
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        await _run_with_auth(
            coros_api.remove_scheduled_workout, auth, plan_id, id_in_plan, plan_program_id or None
        )
        return {"removed": True, "plan_id": plan_id, "id_in_plan": id_in_plan}
    except Exception as exc:
        return {"error": str(exc), "removed": False}


# ---------------------------------------------------------------------------
# Tool: move_scheduled_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def move_scheduled_workout(
    plan_id: str,
    id_in_plan: str,
    happen_day: str,
    workout_id: str = "",
    plan_program_id: str = "",
    sort_no: int = 1,
) -> dict:
    """
    Move a scheduled workout to a new day.

    This is implemented as schedule-new-then-remove-old so failures are biased
    toward leaving a duplicate instead of losing the workout entirely.

    Parameters
    ----------
    plan_id : str
        Top-level schedule plan ID from list_scheduled_workouts.
    id_in_plan : str
        Scheduled entity ID from list_scheduled_workouts.
    happen_day : str
        New target date in YYYYMMDD format.
    workout_id : str
        Library workout ID. Preferred when available.
    plan_program_id : str
        Fallback program ID from the scheduled item when workout_id is not known.
    sort_no : int
        Order within the new day if multiple workouts exist.

    Returns
    -------
    dict with keys: moved, workout_id, happen_day
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    resolved_workout_id = workout_id or plan_program_id or id_in_plan
    try:
        await _run_with_auth(coros_api.fetch_workout, auth, resolved_workout_id)
    except Exception as exc:
        return {
            "error": f"Unable to resolve workout for scheduled item {id_in_plan}: {exc}",
            "moved": False,
        }

    try:
        await _run_with_auth(coros_api.schedule_workout, auth, resolved_workout_id, happen_day, sort_no)
    except Exception as exc:
        return {
            "error": f"Failed to create new scheduled entry before move: {exc}",
            "moved": False,
            "workout_id": resolved_workout_id,
            "happen_day": happen_day,
        }

    try:
        await _run_with_auth(
            coros_api.remove_scheduled_workout, auth, plan_id, id_in_plan, plan_program_id or None
        )
    except Exception as exc:
        return {
            "error": (
                f"Scheduled new workout on {happen_day}, but failed to remove the old entry: {exc}. "
                "You may need to delete the original scheduled workout manually."
            ),
            "moved": False,
            "workout_id": resolved_workout_id,
            "happen_day": happen_day,
            "duplicate_created": True,
        }

    return {
        "moved": True,
        "workout_id": resolved_workout_id,
        "happen_day": happen_day,
        "removed_plan_id": plan_id,
        "removed_id_in_plan": id_in_plan,
    }


# ---------------------------------------------------------------------------
# Tool: replace_scheduled_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def replace_scheduled_workout(
    plan_id: str,
    id_in_plan: str,
    happen_day: str,
    workout_id: str = "",
    plan_program_id: str = "",
    sort_no: int = 1,
    name: str = "",
    estimated_distance_meters: float | None = None,
    estimated_time_seconds: int | None = None,
    step_updates: list[dict] | None = None,
    delete_original_workout: bool = False,
) -> dict:
    """
    Replace a scheduled workout by cloning the library workout, applying edits,
    scheduling the replacement, and removing the old scheduled entry.

    Parameters
    ----------
    plan_id : str
        Existing scheduled plan ID from list_scheduled_workouts.
    id_in_plan : str
        Existing scheduled entity ID from list_scheduled_workouts.
    happen_day : str
        Day to schedule the replacement workout on, in YYYYMMDD format.
    workout_id : str
        Existing library workout ID.
    plan_program_id : str
        Fallback program ID when workout_id is not known.
    sort_no : int
        Order in the schedule for the replacement workout.
    name : str
        Optional replacement workout name.
    estimated_distance_meters : float | None
        Optional replacement top-level distance in meters.
    estimated_time_seconds : int | None
        Optional replacement top-level time in seconds.
    step_updates : list[dict] | None
        Same step patch format as update_workout.
    delete_original_workout : bool
        Whether to delete the original library workout after replacement.

    Returns
    -------
    dict with keys: replaced, old_workout_id, new_workout_id, happen_day
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}

    source_workout_id = workout_id or plan_program_id or id_in_plan
    try:
        result = await _run_with_auth(
            coros_api.clone_and_patch_workout,
            auth,
            source_workout_id,
            name=name or None,
            estimated_distance_meters=estimated_distance_meters,
            estimated_time_seconds=estimated_time_seconds,
            step_updates=step_updates or [],
        )
    except Exception as exc:
        return {"error": f"Failed to build replacement workout: {exc}", "replaced": False}

    new_workout_id = result["new_workout_id"]
    try:
        await _run_with_auth(coros_api.schedule_workout, auth, new_workout_id, happen_day, sort_no)
    except Exception as exc:
        return {
            "error": f"Created replacement workout {new_workout_id}, but failed to schedule it: {exc}",
            "replaced": False,
            "new_workout_id": new_workout_id,
        }

    try:
        await _run_with_auth(
            coros_api.remove_scheduled_workout, auth, plan_id, id_in_plan, plan_program_id or None
        )
    except Exception as exc:
        return {
            "error": (
                f"Replacement workout {new_workout_id} was scheduled, but removing the old scheduled entry failed: {exc}. "
                "You may need to delete the original scheduled workout manually."
            ),
            "replaced": False,
            "new_workout_id": new_workout_id,
            "duplicate_created": True,
        }

    deleted_original_workout = False
    warning = None
    if delete_original_workout:
        try:
            await _run_with_auth(coros_api.delete_workout, auth, source_workout_id)
            deleted_original_workout = True
        except Exception as exc:
            warning = f"Replacement succeeded, but deleting the original workout failed: {exc}"

    return {
        "replaced": True,
        "old_workout_id": source_workout_id,
        "new_workout_id": new_workout_id,
        "happen_day": happen_day,
        "sort_no": sort_no,
        "deleted_original_workout": deleted_original_workout,
        "warning": warning,
        "workout": result["workout"],
    }


# ---------------------------------------------------------------------------
# Tool: create_strength_workout
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_strength_workout(
    name: str,
    exercises: list[dict],
    sets: int = 1,
) -> dict:
    """
    Create a new structured strength workout program.

    Parameters
    ----------
    name : str
        Workout name.
    exercises : list of dicts, each with:
        - origin_id (str): exercise catalogue ID from list_exercises
        - name (str): T-code name (e.g. "T1061")
        - overview (str): sid_ key (e.g. "sid_strength_squats")
        - target_type (int): 2=time in seconds, 3=reps
        - target_value (int): number of seconds or reps
        - rest_seconds (int): rest after this exercise (default 60)
    sets : int
        Number of circuit repetitions (default 1).

    Returns
    -------
    dict with keys: workout_id, name, sets, exercise_count
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros."}
    try:
        workout_id = await _run_with_auth(coros_api.create_strength_workout, auth, name, exercises, sets)
        return {
            "workout_id": workout_id,
            "name": name,
            "sets": sets,
            "exercise_count": len(exercises),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool: list_exercises
# ---------------------------------------------------------------------------

@mcp.tool()
async def list_exercises(sport_type: int = 4) -> dict:
    """
    List the exercise catalogue for a given sport type.

    Useful for resolving strength/conditioning exercises (sport_type=4)
    that appear in planned workouts by name and ID.

    Parameters
    ----------
    sport_type : int
        Sport type ID. Default 4 = Strength.

    Returns
    -------
    dict with keys: exercises (list), count, sport_type
    """
    auth = await _get_auth()
    if auth is None:
        return {"error": "Not authenticated. Set COROS_EMAIL and COROS_PASSWORD in .env or call authenticate_coros.", "exercises": []}
    try:
        items = await _run_with_auth(coros_api.fetch_exercises, auth, sport_type)
        return {"exercises": items, "count": len(items), "sport_type": sport_type}
    except Exception as exc:
        return {"error": str(exc), "exercises": []}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
