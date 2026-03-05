"""
Coros Training Hub API client.

Auth mechanism: MD5-hashed password + accessToken header.
HRV data comes from /dashboard/query (last 7 days of nightly RMSSD).
Sleep phase data is NOT available through the Training Hub web API.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

import httpx

from auth.storage import get_token, store_token
from models import ActivitySummary, DailyRecord, HRVRecord, SleepPhases, SleepRecord, StoredAuth

# ---------------------------------------------------------------------------
# Endpoint constants
# ---------------------------------------------------------------------------

ENDPOINTS = {
    "login": "/account/login",
    "dashboard": "/dashboard/query",        # contains sleepHrvData (last 7 days)
    "analyse": "/analyse/query",            # summary + t7dayList (28 days, has VO2max/fitness)
    "analyse_detail": "/analyse/dayDetail/query",  # daily metrics with date range (up to 24 weeks)
    "sleep": "/sleep/query",                # NOT available on Training Hub API
    "activity_list": "/activity/query",
    "activity_detail": "/activity/detail/query",
    "sport_types": "/activity/fit/getImportSportList",
    "workout_list": "/training/program/query",  # POST — list/fetch workout programs
    "workout_add": "/training/program/add",     # POST — create new structured workout
}

# Login works on teamapi.coros.com but tokens are only valid on the
# region-specific API host.  Always use the regional URL for all calls.
BASE_URLS = {
    "eu": "https://teameuapi.coros.com",
    "us": "https://teamapi.coros.com",
}

TOKEN_TTL_MS = 24 * 60 * 60 * 1000  # 24 hours in milliseconds


# ---------------------------------------------------------------------------
# Token storage  (keyring → encrypted file, managed by auth.storage)
# ---------------------------------------------------------------------------

def _save_auth(auth: StoredAuth) -> None:
    store_token(auth.model_dump_json())


def _load_auth() -> Optional[StoredAuth]:
    result = get_token()
    if not result.success or not result.token:
        return None
    try:
        data = json.loads(result.token)
        return StoredAuth(**data)
    except Exception:
        return None


def _is_token_valid(auth: StoredAuth) -> bool:
    now_ms = int(time.time() * 1000)
    return (now_ms - auth.timestamp) < TOKEN_TTL_MS


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def _base_url(region: str) -> str:
    return BASE_URLS.get(region, BASE_URLS["eu"])


async def login(email: str, password: str, region: str = "eu") -> StoredAuth:
    """Authenticate against Coros API and persist the token."""
    url = _base_url(region) + ENDPOINTS["login"]
    payload = {
        "account": email,
        "accountType": 2,
        "pwd": _md5(password),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        body = resp.json()

    if body.get("result") != "0000":
        raise ValueError(f"Coros login failed: {body.get('message', 'unknown error')}")

    data = body.get("data", {})
    auth = StoredAuth(
        access_token=data["accessToken"],
        user_id=data["userId"],
        region=region,
        timestamp=int(time.time() * 1000),
    )
    _save_auth(auth)
    return auth


def get_stored_auth() -> Optional[StoredAuth]:
    """Return stored auth if it exists and is not expired."""
    auth = _load_auth()
    if auth and _is_token_valid(auth):
        return auth
    return None


# ---------------------------------------------------------------------------
# API headers
# ---------------------------------------------------------------------------

def _auth_headers(auth: StoredAuth) -> dict:
    return {
        "Content-Type": "application/json",
        "accessToken": auth.access_token,
        "yfheader": json.dumps({"userId": auth.user_id}),
    }


# ---------------------------------------------------------------------------
# HRV data  (confirmed: /dashboard/query → data.summaryInfo.sleepHrvData)
# ---------------------------------------------------------------------------

async def fetch_hrv(auth: StoredAuth) -> list[HRVRecord]:
    """
    Fetch nightly HRV data from the Coros dashboard endpoint.

    Returns the last ~7 days of data (whatever the API provides).
    There is no date-range parameter — the dashboard always returns recent data.
    """
    url = _base_url(auth.region) + ENDPOINTS["dashboard"]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_auth_headers(auth))
        resp.raise_for_status()
        body = resp.json()

    if body.get("result") != "0000":
        raise ValueError(f"Coros dashboard API error: {body.get('message', 'unknown error')}")

    hrv_data = body.get("data", {}).get("summaryInfo", {}).get("sleepHrvData", {})
    records: list[HRVRecord] = []

    for item in hrv_data.get("sleepHrvList", []):
        records.append(HRVRecord(
            date=str(item.get("happenDay", "")),
            avg_sleep_hrv=item.get("avgSleepHrv"),
            baseline=item.get("sleepHrvBase"),
            standard_deviation=item.get("sleepHrvSd"),
            interval_list=item.get("sleepHrvIntervalList"),
        ))

    # Also include today's summary if available and not already in the list
    today_day = hrv_data.get("happenDay")
    if today_day and not any(r.date == str(today_day) for r in records):
        records.append(HRVRecord(
            date=str(today_day),
            avg_sleep_hrv=hrv_data.get("avgSleepHrv"),
            baseline=hrv_data.get("sleepHrvBase"),
            standard_deviation=hrv_data.get("sleepHrvSd"),
            interval_list=hrv_data.get("sleepHrvAllIntervalList"),
        ))

    return sorted(records, key=lambda r: r.date)


# ---------------------------------------------------------------------------
# Daily analysis data  (/analyse/dayDetail/query — up to 24 weeks)
# ---------------------------------------------------------------------------

def _parse_daily_record(item: dict) -> DailyRecord:
    """Parse a single day record from either endpoint."""
    return DailyRecord(
        date=str(item.get("happenDay", "")),
        avg_sleep_hrv=item.get("avgSleepHrv"),
        baseline=item.get("sleepHrvBase"),
        interval_list=item.get("sleepHrvIntervalList"),
        rhr=item.get("rhr"),
        training_load=item.get("trainingLoad"),
        training_load_ratio=item.get("trainingLoadRatio"),
        tired_rate=item.get("tiredRateNew"),
        ati=item.get("ati"),
        cti=item.get("cti"),
        performance=item.get("performance"),
        distance=item.get("distance"),
        duration=item.get("duration"),
        vo2max=item.get("vo2max"),
        lthr=item.get("lthr"),
        ltsp=item.get("ltsp"),
        stamina_level=item.get("staminaLevel"),
        stamina_level_7d=item.get("staminaLevel7d"),
    )


async def fetch_daily_records(
    auth: StoredAuth, start_day: str, end_day: str
) -> list[DailyRecord]:
    """
    Fetch daily metrics (HRV, RHR, training load, VO2max, etc.) for a date range.

    Merges data from two endpoints:
    - /analyse/dayDetail/query: supports up to ~24 weeks (no VO2max/fitness)
    - /analyse/query: last ~28 days with VO2max, LTHR, stamina (merged in)
    """
    headers = _auth_headers(auth)
    base = _base_url(auth.region)

    async with httpx.AsyncClient(timeout=30) as client:
        detail_resp = await client.get(
            base + ENDPOINTS["analyse_detail"],
            params={"startDay": start_day, "endDay": end_day},
            headers=headers,
        )
        detail_resp.raise_for_status()
        detail_body = detail_resp.json()

        analyse_resp = await client.get(
            base + ENDPOINTS["analyse"],
            headers=headers,
        )
        analyse_resp.raise_for_status()
        analyse_body = analyse_resp.json()

    if detail_body.get("result") != "0000":
        raise ValueError(
            f"Coros analyse API error: {detail_body.get('message', 'unknown error')}"
        )

    # Build records from dayDetail (long range)
    records_by_date: dict[str, DailyRecord] = {}
    for item in detail_body.get("data", {}).get("dayList", []):
        rec = _parse_daily_record(item)
        records_by_date[rec.date] = rec

    # Merge VO2max/fitness fields from t7dayList (last ~28 days)
    if analyse_body.get("result") == "0000":
        for item in analyse_body.get("data", {}).get("t7dayList", []):
            date = str(item.get("happenDay", ""))
            if date in records_by_date:
                rec = records_by_date[date]
                rec.vo2max = item.get("vo2max") or rec.vo2max
                rec.lthr = item.get("lthr") or rec.lthr
                rec.ltsp = item.get("ltsp") or rec.ltsp
                rec.stamina_level = item.get("staminaLevel") or rec.stamina_level
                rec.stamina_level_7d = item.get("staminaLevel7d") or rec.stamina_level_7d

    return sorted(records_by_date.values(), key=lambda r: r.date)


# ---------------------------------------------------------------------------
# Activity data
# ---------------------------------------------------------------------------

SPORT_NAMES: dict[int, str] = {
    100: "Running", 102: "Trail Running", 103: "Track Running", 104: "Hiking",
    200: "Road Bike", 201: "Indoor Cycling", 203: "Gravel Bike", 204: "MTB",
    400: "Cardio", 402: "Strength", 403: "Yoga",
    900: "Walking", 9807: "Bike Commute",
}


def _parse_activity(item: dict) -> ActivitySummary:
    sport_type = item.get("sportType")
    return ActivitySummary(
        activity_id=str(item.get("labelId", "")),
        name=item.get("name") or item.get("remark"),
        sport_type=sport_type,
        sport_name=SPORT_NAMES.get(sport_type, f"Sport {sport_type}") if sport_type else None,
        start_time=str(item.get("startTime", "")) or None,
        end_time=str(item.get("endTime", "")) or None,
        duration_seconds=item.get("totalTime"),
        distance_meters=item.get("totalDistance"),
        avg_hr=item.get("avgHr"),
        max_hr=item.get("maxHr"),
        calories=item.get("calorie") or item.get("totalCalorie"),
        training_load=item.get("trainingLoad"),
        avg_power=item.get("avgPower"),
        normalized_power=item.get("np"),
        elevation_gain=item.get("totalAscent") or item.get("elevationGain"),
    )


async def fetch_activities(
    auth: StoredAuth,
    start_day: str,
    end_day: str,
    page: int = 1,
    size: int = 30,
    mode_list: Optional[list[int]] = None,
) -> tuple[list[ActivitySummary], int]:
    """
    Fetch activity list for a date range.
    Returns (activities, total_count).
    """
    params: dict = {
        "startDay": start_day,
        "endDay": end_day,
        "pageNumber": page,
        "size": size,
    }
    if mode_list:
        params["modeList"] = ",".join(str(m) for m in mode_list)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["activity_list"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    if body.get("result") != "0000":
        raise ValueError(f"Coros activity API error: {body.get('message', 'unknown error')}")

    data = body.get("data", {})
    items = data.get("dataList", data.get("list", []))
    total = data.get("totalCount", len(items))
    return [_parse_activity(i) for i in items], total


async def fetch_activity_detail(auth: StoredAuth, activity_id: str, sport_type: int = 0) -> dict:
    """
    Fetch full activity detail including laps, HR zones, and metrics.
    Returns raw API data dict.
    Requires sport_type (e.g. 200=Road Bike, 201=Indoor Cycling, 100=Running).
    """
    headers = {k: v for k, v in _auth_headers(auth).items() if k != "Content-Type"}
    url = _base_url(auth.region) + ENDPOINTS["activity_detail"]
    form_data = {"labelId": activity_id, "userId": auth.user_id, "sportType": str(sport_type)}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, data=form_data, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    if body.get("result") != "0000":
        raise ValueError(f"Coros activity detail API error: {body.get('message', 'unknown error')}")

    data = body.get("data", {})
    # Strip large time-series arrays that bloat the response
    for key in ("graphList", "frequencyList", "gpsLightDuration"):
        data.pop(key, None)
    return data


# ---------------------------------------------------------------------------
# Workout programs  (/training/program/query + /training/program/add)
# ---------------------------------------------------------------------------

# sportType=2 = Indoor Cycling (Rollen); intensityType=6 = power in watts
# targetType=2 = time-based (seconds); exerciseType=2 = cycling block

WORKOUT_SPORT_NAMES: dict[int, str] = {
    2: "Indoor Cycling",
    4: "Strength",
    100: "Running",
    200: "Road Bike",
    201: "Indoor Cycling (alt)",
}


def _parse_workout(item: dict) -> dict:
    exercises = []
    for ex in item.get("exercises", []):
        exercises.append({
            "name": ex.get("name"),
            "duration_seconds": ex.get("targetValue"),
            "power_low_w": ex.get("intensityValue"),
            "power_high_w": ex.get("intensityValueExtend"),
            "sets": ex.get("sets", 1),
        })
    sport = item.get("sportType")
    return {
        "id": str(item.get("id", "")),
        "name": item.get("name"),
        "sport_type": sport,
        "sport_name": WORKOUT_SPORT_NAMES.get(sport, f"Sport {sport}"),
        "estimated_time_seconds": item.get("estimatedTime"),
        "exercise_count": item.get("exerciseNum", len(exercises)),
        "exercises": exercises,
    }


async def fetch_workouts(auth: StoredAuth) -> list[dict]:
    """List all user workout programs."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_list"],
            json={},
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    if body.get("result") != "0000":
        raise ValueError(f"Coros workout API error: {body.get('message', 'unknown error')}")

    return [_parse_workout(w) for w in body.get("data", [])]


async def create_workout(
    auth: StoredAuth,
    name: str,
    steps: list[dict],
    sport_type: int = 2,
) -> str:
    """
    Create a new structured workout program.

    steps: list of dicts with keys:
      - name: str — step label (e.g. "10:00 Einfahren")
      - duration_minutes: float — step duration in minutes
      - power_low_w: int — lower power target in watts
      - power_high_w: int — upper power target in watts (0 = open-ended)

    Returns the new workout ID.
    """
    exercises = []
    for i, step in enumerate(steps):
        duration_s = int(step["duration_minutes"] * 60)
        exercises.append({
            "name": step["name"],
            "exerciseType": 2,
            "sportType": sport_type,
            "intensityType": 6,           # power in watts
            "intensityValue": step["power_low_w"],
            "intensityValueExtend": step.get("power_high_w", 0),
            "targetType": 2,              # time-based
            "targetValue": duration_s,
            "sets": 1,
            "sortNo": 16777216 * (i + 1),
            "restType": 3,
            "restValue": 0,
            "groupId": "0",
            "isGroup": False,
            "originId": "0",
        })

    total_seconds = sum(int(s["duration_minutes"] * 60) for s in steps)
    payload = {
        "name": name,
        "sportType": sport_type,
        "estimatedTime": total_seconds,
        "access": 1,
        "exercises": exercises,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_add"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    if body.get("result") != "0000":
        raise ValueError(f"Coros workout create error: {body.get('message', 'unknown error')}")

    return str(body.get("data", ""))


# ---------------------------------------------------------------------------
# Sleep data  (NOT available through Training Hub web API)
# ---------------------------------------------------------------------------

async def fetch_sleep(auth: StoredAuth, start_day: str, end_day: str) -> list[SleepRecord]:
    """
    Fetch sleep data for a date range.

    WARNING: Sleep phase data (deep/light/REM/awake) is NOT available through
    the Coros Training Hub web API.  This endpoint is a placeholder for when
    the correct mobile-app API endpoint is discovered.
    """
    url = _base_url(auth.region) + ENDPOINTS["sleep"]
    params = {
        "userId": auth.user_id,
        "startDay": start_day,
        "endDay": end_day,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=_auth_headers(auth))
        resp.raise_for_status()
        body = resp.json()

    if body.get("result") != "0000":
        raise ValueError(f"Coros sleep API error: {body.get('message', 'unknown error')}")

    records: list[SleepRecord] = []
    for item in body.get("data", {}).get("list", []):
        phases = SleepPhases(
            deep_minutes=item.get("deepSleepMinutes"),
            light_minutes=item.get("lightSleepMinutes"),
            rem_minutes=item.get("remSleepMinutes"),
            awake_minutes=item.get("awakeSleepMinutes"),
        )
        records.append(SleepRecord(
            date=str(item.get("date", "")),
            total_duration_minutes=item.get("totalSleepMinutes"),
            phases=phases,
            sleep_start=item.get("sleepStartTime"),
            sleep_end=item.get("sleepEndTime"),
            quality_score=item.get("sleepScore"),
        ))
    return records
