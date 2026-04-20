"""
Coros Training Hub API client.

Auth mechanism: MD5-hashed password + accessToken header.
HRV data comes from /dashboard/query (last 7 days of nightly RMSSD).
Sleep phase data comes from the mobile API (/coros/data/statistic/daily on apieu.coros.com).
"""

import asyncio
import copy
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Optional

import httpx

from auth.storage import get_token, store_token
from models import ActivitySummary, DailyRecord, HRVRecord, SleepPhases, SleepRecord, StoredAuth

# ---------------------------------------------------------------------------
# Endpoint constants
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

MOBILE_LOGIN_ENDPOINT = "/coros/user/login"

# AES key hardcoded in libencrypt-lib.so (reverse-engineered from Coros APK)
_MOBILE_AES_IV = b"weloop3_2015_03#"

ENDPOINTS = {
    "login": "/account/login",
    "dashboard": "/dashboard/query",        # contains sleepHrvData (last 7 days)
    "analyse": "/analyse/query",            # summary + t7dayList (28 days, has VO2max/fitness)
    "analyse_detail": "/analyse/dayDetail/query",  # daily metrics with date range (up to 24 weeks)
    "sleep": "/coros/data/statistic/daily",  # mobile API (apieu.coros.com)
    "activity_list": "/activity/query",
    "activity_detail": "/activity/detail/query",
    "activity_download": "/activity/detail/download",
    "sport_types": "/activity/fit/getImportSportList",
    "workout_list": "/training/program/query",  # POST — list/fetch workout programs
    "workout_add": "/training/program/add",     # POST — create new structured workout
    "workout_delete": "/training/program/delete",  # POST — delete workout(s), body: ["id1", ...]
    "schedule_sum": "/training/schedule/querysum",  # GET — planned calendar aggregates
    "schedule": "/training/schedule/query",         # GET — planned calendar detail
    "schedule_update": "/training/schedule/update", # POST — add workout to calendar
    "exercises": "/training/exercise/query",        # GET — exercise catalogue by sport type
}

# Login works on teamapi.coros.com but tokens are only valid on the
# region-specific API host.  Always use the regional URL for all calls.
BASE_URLS = {
    "eu": "https://teameuapi.coros.com",
    "us": "https://teamapi.coros.com",
    "asia": "https://teamcnapi.coros.com",
    "cn": "https://teamcnapi.coros.com",
}

# Mobile app API — used for sleep data (different host from Training Hub web API)
MOBILE_BASE_URLS = {
    "eu": "https://apieu.coros.com",
    "us": "https://api.coros.com",
    "asia": "https://apicn.coros.com",
    "cn": "https://apicn.coros.com",
}

TOKEN_TTL_MS = 24 * 60 * 60 * 1000  # 24 hours in milliseconds


def _check_response(body: dict, context: str) -> None:
    """Raise ValueError if the Coros API response indicates an error."""
    if body.get("result") != "0000":
        raise ValueError(f"Coros {context} error: {body.get('message', 'unknown error')}")


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
# Mobile API encryption  (AES-128-CBC, key reverse-engineered from APK)
# ---------------------------------------------------------------------------

def _mobile_encrypt(plaintext: str, app_key: str) -> str:
    """
    Encrypt a string for the Coros mobile login API.

    Scheme reverse-engineered from libencrypt-lib.so in the Coros Android APK:
      1. XOR plaintext bytes with appKey bytes cyclically
      2. PKCS7-pad the XOR'd result to a 16-byte boundary
      3. AES-128-CBC encrypt: key = appKey bytes, IV = 'weloop3_2015_03#'
      4. Base64-encode the ciphertext
    """
    from Crypto.Cipher import AES
    import base64

    key = app_key.encode("ascii")
    data = plaintext.encode("utf-8")
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    pad_len = 16 - (len(xored) % 16)
    padded = xored + bytes([pad_len] * pad_len)
    cipher = AES.new(key, AES.MODE_CBC, _MOBILE_AES_IV)
    return base64.b64encode(cipher.encrypt(padded)).decode("ascii")


async def _mobile_login(email: str, password: str, region: str = "eu") -> tuple[str, dict]:
    """
    Authenticate against the Coros mobile API with encrypted credentials.

    Returns (access_token, login_payload_for_replay).
    The login_payload can be replayed to refresh the token without re-entering credentials.
    """
    mobile_base = MOBILE_BASE_URLS.get(region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + MOBILE_LOGIN_ENDPOINT
    app_key = str(random.randint(1_000_000_000_000_000, 9_999_999_999_999_999))
    payload = {
        "account": _mobile_encrypt(email, app_key) + "\n",
        "accountType": 2,
        "appKey": app_key,
        "clientType": 1,
        "hasHrCalibrated": 0,
        "kbValidity": 0,
        "pwd": _mobile_encrypt(_md5(password), app_key) + "\n",
        "region": "310|Europe/Berlin|US",
        "skipValidation": False,
    }
    yfheader = json.dumps({
        "appVersion": 1125917087236096,
        "clientType": 1,
        "language": "en-US",
        "mobileName": "sdk_gphone64_arm64,google,Google",
        "releaseType": 1,
        "systemVersion": "13",
        "timezone": 4,
        "versionCode": "404080400",
    }, separators=(",", ":"))
    headers = {
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.12.0",
        "request-time": str(int(time.time() * 1000)),
        "yfheader": yfheader,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "mobile login")

    token = body.get("data", {}).get("accessToken")
    if not token:
        raise ValueError("No accessToken in Coros mobile login response")

    return token, payload


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def _base_url(region: str) -> str:
    return BASE_URLS.get(region, BASE_URLS["eu"])


async def login(email: str, password: str, region: str = "eu", *, skip_mobile: bool = True) -> StoredAuth:
    """Authenticate against Coros API and persist the token."""
    pwd_hash = _md5(password)
    login_payload = {
        "account": email,
        "accountType": 2,
        "pwd": pwd_hash,
    }
    json_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=30) as client:
        # Training Hub token (teameuapi.coros.com)
        resp = await client.post(
            _base_url(region) + ENDPOINTS["login"],
            json=login_payload,
            headers=json_headers,
        )
        resp.raise_for_status()
        body = resp.json()

        _check_response(body, "login")

        data = body.get("data", {})

    # Mobile API token (apieu.coros.com) — needed for sleep data
    # Uses AES-encrypted credentials (key reverse-engineered from libencrypt-lib.so)
    mobile_token = None
    mobile_payload = None
    if not skip_mobile:
        try:
            mobile_token, mobile_payload = await _mobile_login(email, password, region)
        except Exception:
            pass  # mobile login is best-effort; sleep data will fail gracefully

    auth = StoredAuth(
        access_token=data["accessToken"],
        user_id=data["userId"],
        region=region,
        timestamp=int(time.time() * 1000),
        mobile_access_token=mobile_token,
        mobile_login_payload=mobile_payload,
    )
    _save_auth(auth)
    return auth


async def login_mobile(email: str, password: str, region: str = "eu") -> StoredAuth:
    """Authenticate against the Coros mobile API only and persist the token.

    If an existing StoredAuth exists, updates only the mobile fields.
    Otherwise creates a minimal StoredAuth with only mobile credentials.
    """
    mobile_token, mobile_payload = await _mobile_login(email, password, region)

    existing = _load_auth()
    if existing:
        existing = existing.model_copy(update={
            "mobile_access_token": mobile_token,
            "mobile_login_payload": mobile_payload,
        })
        _save_auth(existing)
        return existing

    auth = StoredAuth(
        access_token="",
        user_id="",
        region=region,
        timestamp=int(time.time() * 1000),
        mobile_access_token=mobile_token,
        mobile_login_payload=mobile_payload,
    )
    _save_auth(auth)
    return auth


def get_stored_auth() -> Optional[StoredAuth]:
    """Return stored auth if it exists and is not expired.
    
    When COROS_ACCESS_TOKEN env var is set, it takes precedence over
    stored keyring/encrypted-file auth (for MCP server use cases where
    keyring is not accessible in the subprocess).
    """
    # Prefer explicit env var token when provided
    access_token = os.environ.get("COROS_ACCESS_TOKEN")
    if access_token:
        region = os.environ.get("COROS_REGION", "eu")
        return StoredAuth(
            access_token=access_token,
            user_id="env",
            region=region,
            timestamp=int(time.time() * 1000),
            mobile_access_token=None,
            mobile_login_payload=None,
        )
    # Fall back to stored auth
    auth = _load_auth()
    if auth and _is_token_valid(auth):
        return auth
    return None


def get_env_credentials() -> Optional[tuple[str, str, str]]:
    """Return (email, password, region) from env vars, or None if not fully set."""
    email = os.environ.get("COROS_EMAIL")
    password = os.environ.get("COROS_PASSWORD")
    region = os.environ.get("COROS_REGION", "eu")
    if email and password:
        return email, password, region
    return None


async def try_auto_login() -> Optional[StoredAuth]:
    """Attempt login using COROS_EMAIL/PASSWORD env vars. Returns None on failure.

    Always skips mobile login — the mobile token is obtained lazily on the first
    call to fetch_sleep(), so the Coros mobile app session is never disrupted by
    routine web-token refreshes.
    """
    creds = get_env_credentials()
    if creds is None:
        return None
    email, password, region = creds
    try:
        return await login(email, password, region)  # skip_mobile=True by default
    except Exception:
        return None


# ---------------------------------------------------------------------------
# API headers
# ---------------------------------------------------------------------------

def _auth_headers(auth: StoredAuth) -> dict:
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
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

    _check_response(body, "dashboard")

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
        detail_resp, analyse_resp = await asyncio.gather(
            client.get(
                base + ENDPOINTS["analyse_detail"],
                params={"startDay": start_day, "endDay": end_day},
                headers=headers,
            ),
            client.get(
                base + ENDPOINTS["analyse"],
                headers=headers,
            ),
        )
    detail_resp.raise_for_status()
    detail_body = detail_resp.json()
    analyse_resp.raise_for_status()
    analyse_body = analyse_resp.json()

    _check_response(detail_body, "analyse")

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

ACTIVITY_EXPORT_FILE_TYPES: dict[str, int] = {
    "csv": 0,
    "gpx": 1,
    "kml": 2,
    "tcx": 3,
    "fit": 4,
}

ACTIVITY_EXPORT_FILE_TYPE_NAMES = {
    value: key for key, value in ACTIVITY_EXPORT_FILE_TYPES.items()
}


def _parse_activity(item: dict) -> ActivitySummary:
    sport_type = item.get("sportType")
    return ActivitySummary(
        activity_id=str(item.get("labelId", "")),
        name=item.get("name") or item.get("remark"),
        sport_type=sport_type,
        sport_name=SPORT_NAMES.get(sport_type, f"Sport {sport_type}") if sport_type else None,
        start_time=str(item["startTime"]) if item.get("startTime") else None,
        end_time=str(item["endTime"]) if item.get("endTime") else None,
        duration_seconds=item.get("totalTime"),
        distance_meters=item.get("distance") or item.get("totalDistance"),
        avg_hr=item.get("avgHr"),
        max_hr=item.get("maxHr"),
        calories=round((item.get("calorie") or item.get("totalCalorie") or 0) / 1000) or None,
        training_load=item.get("trainingLoad"),
        avg_power=item.get("avgPower"),
        normalized_power=item.get("np"),
        elevation_gain=item.get("ascent") or item.get("totalAscent") or item.get("elevationGain"),
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

    _check_response(body, "activity list")

    data = body.get("data", {})
    items = data.get("dataList", data.get("list", []))
    total = data.get("totalCount") or data.get("count") or len(items)
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

    _check_response(body, "activity detail")

    data = body.get("data", {})
    # Strip large time-series arrays that bloat the response
    for key in ("graphList", "frequencyList", "gpsLightDuration"):
        data.pop(key, None)
    return data


def _normalize_activity_export_file_type(file_type: str | int) -> int:
    """Return the COROS fileType enum for an activity export request."""
    if isinstance(file_type, int):
        if file_type not in ACTIVITY_EXPORT_FILE_TYPE_NAMES:
            raise ValueError(f"Unsupported activity export file type: {file_type}")
        return file_type

    normalized = str(file_type).strip().lower()
    if normalized not in ACTIVITY_EXPORT_FILE_TYPES:
        supported = ", ".join(sorted(ACTIVITY_EXPORT_FILE_TYPES))
        raise ValueError(
            f"Unsupported activity export file type '{file_type}'. Supported types: {supported}"
        )
    return ACTIVITY_EXPORT_FILE_TYPES[normalized]


def _activity_export_extension(file_type: int) -> str:
    """Return the file extension for a COROS activity export file type."""
    return ACTIVITY_EXPORT_FILE_TYPE_NAMES[file_type]


def _activity_export_output_path(
    activity_id: str,
    file_type: int,
    output_path: str | None = None,
    file_url: str | None = None,
) -> Path:
    """Resolve the local output path for a downloaded activity export."""
    if output_path:
        return Path(output_path).expanduser().resolve()

    if file_url:
        filename = Path(file_url.split("?", 1)[0]).name
        if filename:
            return (Path.cwd() / filename).resolve()

    suffix = _activity_export_extension(file_type)
    return (Path.cwd() / f"coros-activity-{activity_id}.{suffix}").resolve()


async def fetch_activity_export_url(
    auth: StoredAuth,
    activity_id: str,
    sport_type: int,
    file_type: str | int = "gpx",
) -> dict:
    """
    Request an export URL for a completed activity file.

    The Training Hub web app uses POST /activity/detail/download with
    query params labelId, sportType, and fileType.
    """
    file_type_enum = _normalize_activity_export_file_type(file_type)
    params = {
        "labelId": activity_id,
        "sportType": int(sport_type),
        "fileType": file_type_enum,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["activity_download"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "activity export")

    data = body.get("data", {})
    file_url = data.get("fileUrl")
    if not file_url:
        raise ValueError("Coros activity export did not return a file URL.")

    return {
        "activity_id": activity_id,
        "sport_type": int(sport_type),
        "file_type": _activity_export_extension(file_type_enum),
        "file_type_enum": file_type_enum,
        "file_url": file_url,
    }


async def export_activity_file(
    auth: StoredAuth,
    activity_id: str,
    sport_type: int,
    file_type: str | int = "gpx",
    output_path: str | None = None,
) -> dict:
    """Export a completed activity file and save it locally."""
    export_info = await fetch_activity_export_url(auth, activity_id, sport_type, file_type)
    destination = _activity_export_output_path(
        activity_id,
        export_info["file_type_enum"],
        output_path=output_path,
        file_url=export_info["file_url"],
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(export_info["file_url"])
        resp.raise_for_status()
        destination.write_bytes(resp.content)

    export_info["output_path"] = str(destination)
    export_info["downloaded"] = True
    export_info.pop("file_type_enum", None)
    return export_info


# ---------------------------------------------------------------------------
# Workout programs  (/training/program/query + /training/program/add)
# ---------------------------------------------------------------------------

# sportType=2 = Indoor Cycling (Rollen); intensityType=6 = power in watts
# targetType=2 = time-based (seconds); exerciseType=2 = cycling block

WORKOUT_SPORT_NAMES: dict[int, str] = {
    1: "Running",
    2: "Indoor Cycling",
    4: "Strength",
    100: "Running",
    200: "Road Bike",
    201: "Indoor Cycling (alt)",
}

DISTANCE_TARGET_TYPES = {5}
TIME_TARGET_TYPES = {2}
RUN_STEP_KIND_TO_EXERCISE_TYPE = {
    "warmup": 1,
    "training": 2,
    "interval": 2,
    "cooldown": 3,
    "rest": 4,
}
RUN_TARGET_TYPE_ALIASES = {
    "time": 2,
    "distance": 5,
}


def _parse_workout(item: dict) -> dict:
    exercises = []
    for ex in item.get("exercises", []):
        overview = ex.get("overview")
        exercises.append({
            "id": str(ex.get("id", "")),
            "name": ex.get("name"),
            "overview": _readable_overview(overview) if overview else None,
            "raw_overview": overview,
            "exercise_type": ex.get("exerciseType"),
            "sport_type": ex.get("sportType"),
            "target_type": ex.get("targetType"),
            "target_value": ex.get("targetValue"),
            "target_display_unit": ex.get("targetDisplayUnit"),
            "duration_seconds": ex.get("targetValue"),
            "intensity_type": ex.get("intensityType"),
            "intensity_value": ex.get("intensityValue"),
            "intensity_value_extend": ex.get("intensityValueExtend"),
            "intensity_display_unit": ex.get("intensityDisplayUnit"),
            "power_low_w": ex.get("intensityValue"),
            "power_high_w": ex.get("intensityValueExtend"),
            "rest_type": ex.get("restType"),
            "rest_value": ex.get("restValue"),
            "sets": ex.get("sets", 1),
            "group_id": str(ex.get("groupId", "")),
            "is_group": bool(ex.get("isGroup")),
            "origin_id": str(ex.get("originId", "")),
            "sort_no": ex.get("sortNo"),
        })
    sport = item.get("sportType")
    return {
        "id": str(item.get("id", "")),
        "id_in_plan": str(item.get("idInPlan", "")),
        "name": item.get("name"),
        "sport_type": sport,
        "sport_name": WORKOUT_SPORT_NAMES.get(sport, f"Sport {sport}"),
        "estimated_time_seconds": item.get("estimatedTime"),
        "estimated_distance": item.get("estimatedDistance"),
        "estimated_type": item.get("estimatedType"),
        "distance_display_unit": item.get("distanceDisplayUnit"),
        "target_type": item.get("targetType"),
        "target_value": item.get("targetValue"),
        "strength_type": item.get("strengthType"),
        "simple": item.get("simple"),
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

    _check_response(body, "workout list")

    return [_parse_workout(w) for w in body.get("data", [])]


async def fetch_workout(auth: StoredAuth, workout_id: str) -> dict:
    """Fetch a single workout program by ID."""
    workout = await _fetch_raw_workout(auth, workout_id)
    if workout is None:
        raise ValueError(f"Workout {workout_id} not found.")
    return _parse_workout(workout)


def _meters_to_coros_distance_value(meters: float) -> int:
    """Convert meters to the distance unit used in running workout payloads."""
    return int(round(meters * 100))


def _coros_distance_value_to_meters(value: int | float) -> float:
    """Convert the running distance unit back to meters."""
    return float(value) / 100.0


def _reset_program_for_create(workout: dict) -> dict:
    """Prepare a raw workout payload for program/add by clearing identity fields."""
    payload = copy.deepcopy(workout)
    payload.pop("exerciseBarChart", None)
    payload.pop("officalConfig", None)
    payload["id"] = "0"
    payload["idInPlan"] = "0"
    payload["authorId"] = "0"
    payload["userId"] = "0"
    payload["createTimestamp"] = 0
    payload["deleted"] = 0
    payload["status"] = 1
    payload["version"] = 0
    payload["star"] = 0
    payload["nickname"] = ""

    id_map: dict[str, str] = {}
    for index, ex in enumerate(payload.get("exercises", []), start=1):
        old_id = str(ex.get("id", index))
        new_id = str(index)
        id_map[old_id] = new_id
        ex["id"] = new_id
        ex["programId"] = "0"
        ex["userId"] = 0
        ex["createTimestamp"] = 0
        ex["deleted"] = 0
        ex["status"] = 1
        ex["defaultOrder"] = index - 1
    for ex in payload.get("exercises", []):
        group_id = str(ex.get("groupId", "0"))
        ex["groupId"] = id_map.get(group_id, group_id)
    return payload


def _recalculate_workout_summary(workout: dict) -> None:
    """Best-effort refresh of summary fields after exercise edits."""
    exercises = workout.get("exercises", [])
    workout["exerciseNum"] = len(exercises)
    workout["totalSets"] = len(exercises)

    estimated_distance = sum(
        int(ex.get("targetValue") or 0)
        for ex in exercises
        if ex.get("targetType") in DISTANCE_TARGET_TYPES and not ex.get("isGroup")
    )
    estimated_time = sum(
        int(ex.get("targetValue") or 0)
        for ex in exercises
        if ex.get("targetType") in TIME_TARGET_TYPES and not ex.get("isGroup")
    )

    if estimated_distance:
        workout["estimatedDistance"] = estimated_distance
        if workout.get("targetType") in DISTANCE_TARGET_TYPES:
            workout["targetValue"] = estimated_distance
    if estimated_time:
        workout["estimatedTime"] = estimated_time
        if workout.get("targetType") in TIME_TARGET_TYPES:
            workout["targetValue"] = estimated_time


def _apply_top_level_workout_patch(
    workout: dict,
    *,
    name: Optional[str] = None,
    estimated_distance_meters: Optional[float] = None,
    estimated_time_seconds: Optional[int] = None,
) -> None:
    if name:
        workout["name"] = name
    if estimated_distance_meters is not None:
        value = _meters_to_coros_distance_value(estimated_distance_meters)
        workout["estimatedDistance"] = value
        if workout.get("targetType") in DISTANCE_TARGET_TYPES:
            workout["targetValue"] = value
    if estimated_time_seconds is not None:
        workout["estimatedTime"] = int(estimated_time_seconds)
        if workout.get("targetType") in TIME_TARGET_TYPES:
            workout["targetValue"] = int(estimated_time_seconds)


def _find_exercise_for_patch(exercises: list[dict], patch: dict) -> tuple[int, dict]:
    if "step_index" in patch:
        index = int(patch["step_index"])
        if index < 0 or index >= len(exercises):
            raise ValueError(f"step_index {index} is out of range.")
        return index, exercises[index]

    step_id = patch.get("step_id")
    if step_id is not None:
        for index, ex in enumerate(exercises):
            if str(ex.get("id", "")) == str(step_id):
                return index, ex
        raise ValueError(f"step_id {step_id} not found.")

    step_name = patch.get("step_name")
    if step_name is not None:
        for index, ex in enumerate(exercises):
            if ex.get("name") == step_name:
                return index, ex
        raise ValueError(f"step_name {step_name!r} not found.")

    raise ValueError("Each step update must include one of: step_index, step_id, step_name.")


def _apply_step_updates(workout: dict, step_updates: list[dict]) -> None:
    exercises = workout.get("exercises", [])
    for patch in step_updates:
        _, ex = _find_exercise_for_patch(exercises, patch)

        if "kind" in patch:
            kind = str(patch["kind"]).strip().lower()
            if kind not in RUN_STEP_KIND_TO_EXERCISE_TYPE:
                raise ValueError(f"Unsupported run step kind: {patch['kind']!r}")
            ex["exerciseType"] = RUN_STEP_KIND_TO_EXERCISE_TYPE[kind]
        if "name" in patch:
            ex["name"] = patch["name"]
        if "overview" in patch:
            ex["overview"] = patch["overview"]
        if "target_type" in patch:
            target_type = patch["target_type"]
            if isinstance(target_type, str):
                normalized_target = target_type.strip().lower()
                if normalized_target not in RUN_TARGET_TYPE_ALIASES:
                    raise ValueError(f"Unsupported run target_type: {target_type!r}")
                ex["targetType"] = RUN_TARGET_TYPE_ALIASES[normalized_target]
            else:
                ex["targetType"] = target_type
        if "target_value" in patch:
            ex["targetValue"] = int(patch["target_value"])
        if "target_distance_meters" in patch:
            ex["targetType"] = 5
            ex["targetValue"] = _meters_to_coros_distance_value(float(patch["target_distance_meters"]))
        if "target_duration_seconds" in patch:
            ex["targetType"] = 2
            ex["targetValue"] = int(patch["target_duration_seconds"])
        if "target_display_unit" in patch:
            ex["targetDisplayUnit"] = patch["target_display_unit"]
        if "intensity_type" in patch:
            ex["intensityType"] = patch["intensity_type"]
        if "hr_type" in patch:
            ex["hrType"] = int(patch["hr_type"])
        if "is_intensity_percent" in patch:
            ex["isIntensityPercent"] = bool(patch["is_intensity_percent"])
        if "intensity_percent" in patch:
            ex["intensityPercent"] = patch["intensity_percent"]
        if "intensity_percent_extend" in patch:
            ex["intensityPercentExtend"] = patch["intensity_percent_extend"]
        if "intensity_value" in patch:
            ex["intensityValue"] = int(patch["intensity_value"])
        if "intensity_value_extend" in patch:
            ex["intensityValueExtend"] = int(patch["intensity_value_extend"])
        if "intensity_display_unit" in patch:
            ex["intensityDisplayUnit"] = patch["intensity_display_unit"]
        if "rest_type" in patch:
            ex["restType"] = patch["rest_type"]
        if "rest_value" in patch:
            ex["restValue"] = int(patch["rest_value"])
        if "sets" in patch:
            ex["sets"] = int(patch["sets"])

    _recalculate_workout_summary(workout)


async def create_workout_from_raw(auth: StoredAuth, workout: dict) -> str:
    """Create a new workout program from a patched raw workout payload."""
    payload = _reset_program_for_create(workout)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_add"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()
    _check_response(body, "workout create from raw")
    return str(body.get("data", ""))


def _resolve_run_target(step: dict) -> tuple[int, int, int]:
    """Return (target_type, target_value, target_display_unit) for a run step."""
    raw_target_type = step.get("target_type")
    if raw_target_type is None:
        if "target_distance_meters" in step:
            raw_target_type = "distance"
        else:
            raw_target_type = "time"

    if isinstance(raw_target_type, str):
        normalized = raw_target_type.strip().lower()
        if normalized not in RUN_TARGET_TYPE_ALIASES:
            raise ValueError(f"Unsupported run target_type: {raw_target_type!r}")
        target_type = RUN_TARGET_TYPE_ALIASES[normalized]
    else:
        target_type = int(raw_target_type)

    if target_type in DISTANCE_TARGET_TYPES:
        if "target_distance_meters" in step:
            target_value = _meters_to_coros_distance_value(float(step["target_distance_meters"]))
        elif "target_value" in step:
            target_value = int(step["target_value"])
        else:
            raise ValueError("Distance run steps require target_distance_meters or target_value.")
        target_display_unit = int(step.get("target_display_unit", 3))
    elif target_type in TIME_TARGET_TYPES:
        if "target_duration_seconds" in step:
            target_value = int(step["target_duration_seconds"])
        elif "target_value" in step:
            target_value = int(step["target_value"])
        else:
            raise ValueError("Time run steps require target_duration_seconds or target_value.")
        target_display_unit = int(step.get("target_display_unit", 0))
    else:
        raise ValueError(f"Unsupported run target_type value: {target_type}")

    return target_type, target_value, target_display_unit


def _default_run_overview(kind: str, target_type: int) -> str:
    kind = kind.lower()
    if kind == "warmup":
        return "sid_run_warm_up_dist" if target_type in DISTANCE_TARGET_TYPES else "sid_run_warm_up"
    if kind == "cooldown":
        return "sid_run_cool_down_dist" if target_type in DISTANCE_TARGET_TYPES else "sid_run_cool_down"
    if kind == "rest":
        return "sid_run_rest_dist" if target_type in DISTANCE_TARGET_TYPES else "sid_run_rest"
    return "sid_run_training"


def _build_run_exercise(step: dict, *, ex_id: int, sort_no: int, group_id: str = "0") -> tuple[dict, int, int]:
    """Build a single run exercise and return (exercise, distance_sum, time_sum)."""
    kind = str(step.get("kind", "training")).strip().lower()
    if kind not in RUN_STEP_KIND_TO_EXERCISE_TYPE:
        raise ValueError(f"Unsupported run step kind: {kind!r}")

    target_type, target_value, target_display_unit = _resolve_run_target(step)
    intensity_type = int(step.get("intensity_type", 0))
    intensity_value = int(step.get("intensity_value", 0))
    intensity_value_extend = int(step.get("intensity_value_extend", 0))
    exercise = {
        "id": ex_id,
        "name": step.get("name") or kind.replace("warmup", "Warm-up").replace("cooldown", "Cool-down").title(),
        "exerciseType": RUN_STEP_KIND_TO_EXERCISE_TYPE[kind],
        "sportType": 1,
        "intensityType": intensity_type,
        "intensityValue": intensity_value,
        "intensityValueExtend": intensity_value_extend,
        "targetType": target_type,
        "targetValue": target_value,
        "targetDisplayUnit": target_display_unit,
        "intensityDisplayUnit": int(step.get("intensity_display_unit", 0)),
        "sets": int(step.get("sets", 1)),
        "sortNo": sort_no,
        "restType": int(step.get("rest_type", 3)),
        "restValue": int(step.get("rest_value", 0)),
        "groupId": group_id,
        "isGroup": False,
        "originId": str(step.get("origin_id", "0")),
        "overview": step.get("overview") or _default_run_overview(kind, target_type),
        "hrType": int(step.get("hr_type", 3)),
        "isIntensityPercent": bool(step.get("is_intensity_percent", False)),
    }
    distance_sum = target_value if target_type in DISTANCE_TARGET_TYPES else 0
    time_sum = target_value if target_type in TIME_TARGET_TYPES else 0
    return exercise, distance_sum, time_sum


def build_run_workout_payload(name: str, steps: list[dict]) -> dict:
    """Build a raw COROS run workout payload from explicit run steps."""
    exercises = []
    top_index = 0
    ex_id = 0
    total_distance = 0
    total_time = 0

    for step in steps:
        if "repeat" in step:
            top_index += 1
            ex_id += 1
            group_sort = 16777216 * top_index
            group_id = ex_id
            repeat_count = int(step["repeat"])
            sub_steps = step.get("steps") or []
            group_distance = 0
            group_time = 0
            built_sub_steps = []
            for j, sub in enumerate(sub_steps):
                ex_id += 1
                built, sub_distance, sub_time = _build_run_exercise(
                    sub,
                    ex_id=ex_id,
                    sort_no=group_sort + 65536 * (j + 1),
                    group_id=str(group_id),
                )
                built_sub_steps.append(built)
                group_distance += sub_distance
                group_time += sub_time
            group_target_type = 5 if group_distance else 2
            group_target_value = group_distance if group_distance else group_time
            exercises.append({
                "id": group_id,
                "name": step.get("name", "Interval Group"),
                "exerciseType": 0,
                "sportType": 1,
                "intensityType": 0,
                "intensityValue": 0,
                "targetType": group_target_type,
                "targetValue": group_target_value,
                "targetDisplayUnit": 3 if group_target_type in DISTANCE_TARGET_TYPES else 0,
                "sets": repeat_count,
                "sortNo": group_sort,
                "restType": int(step.get("rest_type", 3)),
                "restValue": int(step.get("rest_value", 0)),
                "groupId": "0",
                "isGroup": True,
                "originId": "0",
                "overview": step.get("overview", "sid_run_training"),
            })
            exercises.extend(built_sub_steps)
            total_distance += group_distance * repeat_count
            total_time += group_time * repeat_count
        else:
            top_index += 1
            ex_id += 1
            built, step_distance, step_time = _build_run_exercise(
                step,
                ex_id=ex_id,
                sort_no=16777216 * top_index,
            )
            exercises.append(built)
            total_distance += step_distance
            total_time += step_time

    payload = {
        "name": name,
        "sportType": 1,
        "estimatedTime": total_time,
        "estimatedDistance": total_distance,
        "distanceDisplayUnit": 3,
        "estimatedType": 6 if total_distance else 0,
        "targetType": 5 if total_distance else 2,
        "targetValue": total_distance if total_distance else total_time,
        "simple": False,
        "access": 1,
        "exerciseNum": len(exercises),
        "totalSets": len(exercises),
        "exercises": exercises,
    }
    return payload


async def create_run_workout(auth: StoredAuth, name: str, steps: list[dict]) -> str:
    """Create a running workout with explicit run-step semantics."""
    payload = build_run_workout_payload(name, steps)
    return await create_workout_from_raw(auth, payload)


async def clone_and_patch_workout(
    auth: StoredAuth,
    workout_id: str,
    *,
    name: Optional[str] = None,
    estimated_distance_meters: Optional[float] = None,
    estimated_time_seconds: Optional[int] = None,
    step_updates: Optional[list[dict]] = None,
) -> dict:
    """Clone a workout, apply patches, create a replacement, and return both IDs."""
    raw = await _fetch_raw_workout(auth, workout_id)
    if raw is None:
        raise ValueError(f"Workout {workout_id} not found.")

    patched = copy.deepcopy(raw)
    _apply_top_level_workout_patch(
        patched,
        name=name,
        estimated_distance_meters=estimated_distance_meters,
        estimated_time_seconds=estimated_time_seconds,
    )
    _apply_step_updates(patched, step_updates or [])
    new_workout_id = await create_workout_from_raw(auth, patched)
    return {
        "old_workout_id": str(workout_id),
        "new_workout_id": new_workout_id,
        "workout": _parse_workout(patched),
    }


async def create_workout(
    auth: StoredAuth,
    name: str,
    steps: list[dict],
    sport_type: int = 2,
) -> str:
    """
    Create a new structured workout program.

    steps: list of dicts — either plain steps or repeat groups.

    Plain step:
      - name: str — step label (e.g. "10:00 Einfahren")
      - duration_minutes: float — step duration in minutes
      - power_low_w: int — lower power target in watts
      - power_high_w: int — upper power target in watts (0 = open-ended)

    Repeat group:
      - repeat: int — number of repetitions
      - steps: list[dict] — sub-steps (same format as plain steps)

    Returns the new workout ID.
    """
    exercises = []
    top_index = 0  # counts top-level positions for sortNo
    total_seconds = 0
    ex_id = 0  # sequential exercise IDs (API uses these to link groups)

    for step in steps:
        if "repeat" in step:
            # --- Repeat group ---
            top_index += 1
            ex_id += 1
            group_sort = 16777216 * top_index
            group_id = ex_id

            sub_steps = step["steps"]
            iteration_seconds = sum(
                int(s["duration_minutes"] * 60) for s in sub_steps
            )
            total_seconds += iteration_seconds * step["repeat"]

            # Group header exercise
            exercises.append({
                "id": group_id,
                "name": "Group",
                "exerciseType": 0,
                "sportType": sport_type,
                "intensityType": 0,
                "intensityValue": 0,
                "targetType": 2,
                "targetValue": iteration_seconds,
                "sets": step["repeat"],
                "sortNo": group_sort,
                "restType": 3,
                "restValue": 0,
                "groupId": "0",
                "isGroup": True,
                "originId": "0",
            })

            # Sub-step exercises
            for j, sub in enumerate(sub_steps):
                ex_id += 1
                sub_duration = int(sub["duration_minutes"] * 60)
                exercises.append({
                    "id": ex_id,
                    "name": sub["name"],
                    "exerciseType": 2,
                    "sportType": sport_type,
                    "intensityType": 6,
                    "intensityValue": sub["power_low_w"],
                    "intensityValueExtend": sub.get("power_high_w", 0),
                    "targetType": 2,
                    "targetValue": sub_duration,
                    "sets": 1,
                    "sortNo": group_sort + 65536 * (j + 1),
                    "restType": 3,
                    "restValue": 0,
                    "groupId": str(group_id),
                    "isGroup": False,
                    "originId": "0",
                })
        else:
            # --- Plain step ---
            top_index += 1
            ex_id += 1
            duration_s = int(step["duration_minutes"] * 60)
            total_seconds += duration_s
            exercises.append({
                "id": ex_id,
                "name": step["name"],
                "exerciseType": 2,
                "sportType": sport_type,
                "intensityType": 6,
                "intensityValue": step["power_low_w"],
                "intensityValueExtend": step.get("power_high_w", 0),
                "targetType": 2,
                "targetValue": duration_s,
                "sets": 1,
                "sortNo": 16777216 * top_index,
                "restType": 3,
                "restValue": 0,
                "groupId": "0",
                "isGroup": False,
                "originId": "0",
            })

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

    _check_response(body, "workout create")

    return str(body.get("data", ""))


async def delete_workout(auth: StoredAuth, workout_id: str) -> None:
    """Delete a workout program by ID."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_delete"],
            json=[workout_id],
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "workout delete")


# ---------------------------------------------------------------------------
# Planned activities (training schedule calendar)
# ---------------------------------------------------------------------------

async def fetch_schedule(
    auth: StoredAuth, start_day: str, end_day: str
) -> list[dict]:
    """
    Fetch planned activities from the Coros training calendar.

    Uses GET /training/schedule/querysum with startDate/endDate params.
    start_day / end_day: YYYYMMDD strings.
    Returns the raw list of scheduled items.
    """
    params = {
        "startDate": start_day,
        "endDate": end_day,
        "supportRestExercise": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["schedule"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule")

    return _strip_schedule(body.get("data") or {})


async def fetch_schedule_raw(auth: StoredAuth, start_day: str, end_day: str) -> dict:
    """Fetch the raw schedule payload for a date range."""
    params = {
        "startDate": start_day,
        "endDate": end_day,
        "supportRestExercise": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["schedule"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule")

    return body.get("data") or {}


_EXERCISE_DROP = frozenset({
    "videoInfos", "videoUrl", "videoUrlArrStr", "coverUrlArrStr",
    "thumbnailUrl", "sourceUrl", "animationId",
    "access", "deleted", "defaultOrder", "status", "createTimestamp",
    "userId", "muscle", "muscleRelevance", "part", "equipment",
    "isDefaultAdd", "intensityCustom",
})

_PROGRAM_DROP = frozenset({
    "exerciseBarChart", "headPic", "profile", "sex", "star", "nickname",
    "essence", "originEssence", "access", "authorId", "deleted", "pbVersion",
    "version", "status", "createTimestamp", "thirdPartyId",
    "isTargetTypeConsistent", "pitch", "unit",
    "elevGain",
    "planId", "planIdIndex", "userId",
})

_ENTITY_DROP = frozenset({
    "exerciseBarChart", "completeRate", "score", "standardRate",
    "dayNo", "operateUserId", "thirdParty", "thirdPartyId",
    "sortNo", "userId", "planIdIndex",
})

_TOP_DROP = frozenset({
    "sportDatasInPlan", "sportDatasNotInPlan", "likeTpIds", "starTimestamp",
    "score", "sourceUrl", "inSchedule", "pauseInApp", "access", "authorId",
    "category", "pbVersion", "version", "thirdPartyId", "maxIdInPlan",
    "maxPlanProgramId", "weekStages", "subPlans", "userInfos",
    "type", "unit", "totalDay", "status", "startDay", "createTime",
    "updateTimestamp", "userId",
})


def _drop_keys(d: dict, keys: frozenset) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def _readable_overview(overview: str) -> str:
    """Convert 'sid_strength_squats' → 'Squats', 'sid_run_warm_up_dist' → 'Run warm up dist'."""
    for prefix in ("sid_strength_", "sid_run_", "sid_"):
        if overview.startswith(prefix):
            overview = overview[len(prefix):]
            break
    return overview.replace("_", " ").capitalize()


def _strip_exercise(ex: dict) -> dict:
    out = _drop_keys(ex, _EXERCISE_DROP)
    if "overview" in out:
        out["overview"] = _readable_overview(out["overview"])
    return out


def _strip_program(prog: dict) -> dict:
    out = _drop_keys(prog, _PROGRAM_DROP)
    if "exercises" in out:
        out["exercises"] = [_strip_exercise(e) for e in out["exercises"]]
    return out


def _strip_schedule(data: dict) -> dict:
    out = _drop_keys(data, _TOP_DROP)
    if "entities" in out:
        out["entities"] = [_drop_keys(e, _ENTITY_DROP) for e in out["entities"]]
    if "programs" in out:
        out["programs"] = [_strip_program(p) for p in out["programs"]]
    return out


def _normalize_scheduled_workouts(data: dict) -> list[dict]:
    """Flatten the schedule payload into one entry per scheduled workout."""
    entities = data.get("entities") or []
    programs = data.get("programs") or []

    programs_by_id_in_plan = {}
    programs_by_id = {}
    for program in programs:
        if program.get("idInPlan") is not None:
            programs_by_id_in_plan[str(program.get("idInPlan"))] = program
        if program.get("id") is not None:
            programs_by_id[str(program.get("id"))] = program

    normalized = []
    for idx, entity in enumerate(entities):
        id_in_plan = str(entity.get("idInPlan", ""))
        plan_program_id = str(entity.get("planProgramId", "") or "")

        program = None
        if id_in_plan and id_in_plan in programs_by_id_in_plan:
            program = programs_by_id_in_plan[id_in_plan]
        elif plan_program_id and plan_program_id in programs_by_id:
            program = programs_by_id[plan_program_id]
        elif idx < len(programs):
            program = programs[idx]

        parsed_program = _parse_workout(program) if program else None
        normalized.append({
            "plan_id": str(entity.get("planId", "")),
            "id_in_plan": id_in_plan,
            "plan_program_id": plan_program_id,
            "happen_day": str(entity.get("happenDay", "")),
            "sort_no": entity.get("sortNoInSchedule"),
            "workout_id": parsed_program["id"] if parsed_program else plan_program_id,
            "workout_name": parsed_program["name"] if parsed_program else None,
            "sport_type": parsed_program["sport_type"] if parsed_program else None,
            "sport_name": parsed_program["sport_name"] if parsed_program else None,
            "entity": _drop_keys(entity, frozenset({"userId", "planIdIndex"})),
            "workout": parsed_program,
        })
    return normalized


async def fetch_scheduled_workouts(
    auth: StoredAuth, start_day: str, end_day: str
) -> list[dict]:
    """Return a flattened calendar-friendly view of scheduled workouts."""
    data = await fetch_schedule_raw(auth, start_day, end_day)
    return _normalize_scheduled_workouts(data)


async def create_strength_workout(
    auth: StoredAuth,
    name: str,
    exercises: list[dict],
    sets: int = 1,
) -> str:
    """
    Create a new structured strength workout program.

    exercises: list of dicts with keys:
      - origin_id: str  — exercise catalogue ID (from list_exercises)
      - name: str       — T-code name (e.g. "T1061")
      - overview: str   — sid_ key (e.g. "sid_strength_squats")
      - target_type: int — 2=time (seconds), 3=reps
      - target_value: int — seconds or reps
      - rest_seconds: int — rest after this exercise

    sets: number of circuit repetitions.

    Returns the new workout ID.
    """
    built = []
    total_duration = 0
    for i, ex in enumerate(exercises):
        target_value = ex["target_value"]
        rest = ex.get("rest_seconds", 60)
        total_duration += (target_value if ex["target_type"] == 2 else 0) + rest
        built.append({
            "access": 0,
            "createTimestamp": 0,
            "defaultOrder": i,
            "exerciseType": 2,
            "id": i + 1,
            "intensityCustom": 0,
            "intensityDisplayUnit": "6",
            "intensityMultiplier": 0,
            "intensityPercent": 0,
            "intensityPercentExtend": 0,
            "intensityType": 1,
            "intensityValue": 0,
            "intensityValueExtend": 0,
            "isDefaultAdd": 0,
            "isGroup": False,
            "isIntensityPercent": False,
            "hrType": 0,
            "name": ex.get("name", ""),
            "originId": ex["origin_id"],
            "overview": ex.get("overview", "sid_strength_training"),
            "part": [0],
            "groupId": "",
            "restType": 1,
            "restValue": rest,
            "sets": 1,
            "sortNo": i,
            "sourceUrl": "",
            "sportType": 4,
            "status": 1,
            "targetDisplayUnit": 0,
            "targetType": ex["target_type"],
            "targetValue": target_value,
            "userId": 0,
            "videoInfos": [],
            "videoUrl": "",
        })

    total_duration *= sets
    payload = {
        "access": 1,
        "authorId": "0",
        "createTimestamp": 0,
        "distance": "0",
        "duration": total_duration,
        "essence": 0,
        "estimatedType": 0,
        "estimatedValue": 0,
        "exerciseNum": len(exercises),
        "exercises": built,
        "headPic": "",
        "id": "0",
        "idInPlan": "0",
        "name": name,
        "nickname": "",
        "originEssence": 0,
        "overview": "",
        "pbVersion": 2,
        "pitch": 0,
        "planIdIndex": 0,
        "poolLength": 2500,
        "poolLengthId": 1,
        "poolLengthUnit": 2,
        "profile": "",
        "referExercise": {"intensityType": 1, "hrType": 0, "valueType": 1},
        "sex": 0,
        "sets": sets,
        "shareUrl": "",
        "simple": False,
        "sourceId": "425868113867882496",
        "sourceUrl": "",
        "sportType": 4,
        "star": 0,
        "subType": 65535,
        "targetType": 0,
        "targetValue": 0,
        "thirdPartyId": 0,
        "totalSets": sets,
        "trainingLoad": 0,
        "type": 0,
        "unit": 0,
        "userId": "0",
        "version": 0,
        "videoCoverUrl": "",
        "videoUrl": "",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_add"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "strength workout create")

    return str(body.get("data", ""))


async def _fetch_raw_workout(auth: StoredAuth, workout_id: str) -> Optional[dict]:
    """Return the raw workout object for a given ID from the workout list."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["workout_list"],
            json={},
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()
    for w in body.get("data", []):
        if str(w.get("id", "")) == str(workout_id):
            return w
    return None


async def schedule_workout(
    auth: StoredAuth,
    workout_id: str,
    happen_day: str,
    sort_no: int = 1,
) -> None:
    """
    Add an existing workout to the Coros training calendar.

    happen_day: YYYYMMDD string.
    sort_no: order within the day (1 = first workout).
    """
    # Get raw workout object
    program = await _fetch_raw_workout(auth, workout_id)
    if program is None:
        raise ValueError(f"Workout {workout_id} not found in library.")

    # Fetch schedule to get maxIdInPlan (raw, not stripped)
    params = {
        "startDate": happen_day,
        "endDate": happen_day,
        "supportRestExercise": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["schedule"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        schedule_body = resp.json()

    raw_data = schedule_body.get("data") or {}
    try:
        id_in_plan = int(raw_data.get("maxIdInPlan", 0)) + 1
    except (TypeError, ValueError):
        id_in_plan = 1

    program["idInPlan"] = id_in_plan

    payload = {
        "entities": [{
            "happenDay": happen_day,
            "idInPlan": id_in_plan,
            "sortNoInSchedule": sort_no,
        }],
        "programs": [program],
        "versionObjects": [{"id": id_in_plan, "status": 1}],
        "pbVersion": 2,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["schedule_update"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule update")


async def remove_scheduled_workout(
    auth: StoredAuth,
    plan_id: str,
    id_in_plan: str,
    plan_program_id: Optional[str] = None,
) -> None:
    """
    Remove a scheduled workout from the Coros training calendar.

    plan_id: top-level plan ID (the 'id' field from list_planned_activities).
    id_in_plan: entity's idInPlan value.
    plan_program_id: entity's planProgramId (defaults to id_in_plan if omitted).
    """
    payload = {
        "versionObjects": [{
            "id": id_in_plan,
            "planProgramId": plan_program_id or id_in_plan,
            "planId": plan_id,
            "status": 3,  # 3 = delete
        }],
        "pbVersion": 2,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _base_url(auth.region) + ENDPOINTS["schedule_update"],
            json=payload,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "schedule delete")


async def fetch_exercises(auth: StoredAuth, sport_type: int) -> list[dict]:
    """
    Fetch the exercise catalogue for a given sport type.

    Used to look up strength/conditioning exercises (e.g. sport_type=4 for
    strength) that appear in planned workouts but have no inline detail.
    Returns the raw list of exercise definitions.
    """
    params = {"userId": auth.user_id, "sportType": sport_type}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _base_url(auth.region) + ENDPOINTS["exercises"],
            params=params,
            headers=_auth_headers(auth),
        )
        resp.raise_for_status()
        body = resp.json()

    _check_response(body, "exercise list")

    return body.get("data", []) or []


# ---------------------------------------------------------------------------
# Mobile token auto-refresh
# ---------------------------------------------------------------------------

async def _refresh_mobile_token(auth: StoredAuth) -> bool:
    """
    Refresh the mobile API token by replaying the stored login payload.

    The stored payload contains AES-encrypted credentials generated during
    coros-mcp auth.  The server accepts replay of the same encrypted payload
    — no nonce or anti-replay protection.

    Returns True and updates auth.mobile_access_token in-place on success.
    """
    if not auth.mobile_login_payload:
        return False

    mobile_base = MOBILE_BASE_URLS.get(auth.region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + MOBILE_LOGIN_ENDPOINT
    headers: dict[str, str] = {
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.12.0",
        "request-time": str(int(time.time() * 1000)),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=auth.mobile_login_payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()

        if body.get("result") != "0000":
            return False

        token = body.get("data", {}).get("accessToken")
        if not token:
            return False

        auth.mobile_access_token = token
        _save_auth(auth)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Mobile token — lazy acquisition and refresh
# ---------------------------------------------------------------------------

async def _ensure_mobile_token(auth: StoredAuth) -> bool:
    """Ensure auth has a valid mobile access token, acquiring one on-demand if needed.

    Resolution order:
    1. Token already present — nothing to do.
    2. Replay payload stored — try refresh (re-sends the encrypted login payload).
    3. Env credentials available — perform a fresh mobile login.

    Mobile login is deferred until the first call to fetch_sleep() so that
    normal web-token refreshes never disrupt the Coros mobile app session.
    """
    if auth.mobile_access_token:
        return True

    # Try refreshing via the stored encrypted payload (avoids re-entering creds)
    if auth.mobile_login_payload:
        if await _refresh_mobile_token(auth):
            return True

    # Fall back to a fresh mobile login using env credentials
    creds = get_env_credentials()
    if creds is None:
        return False
    email, password, region = creds
    try:
        mobile_token, mobile_payload = await _mobile_login(email, password, region)
        auth.mobile_access_token = mobile_token
        auth.mobile_login_payload = mobile_payload
        _save_auth(auth)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sleep data  (mobile API: apieu.coros.com/coros/data/statistic/daily)
# ---------------------------------------------------------------------------

async def fetch_sleep(auth: StoredAuth, start_day: str, end_day: str) -> list[SleepRecord]:
    """
    Fetch sleep stage data for a date range from the Coros mobile API.

    Uses POST /coros/data/statistic/daily on apieu.coros.com (not the Training
    Hub web API).  Returns per-night records with deep/light/REM/awake minutes
    and sleep heart rate.

    start_day / end_day: YYYYMMDD strings.
    """
    if not await _ensure_mobile_token(auth):
        raise ValueError(
            "No mobile API token available. Set COROS_EMAIL and COROS_PASSWORD in .env "
            "for automatic acquisition, or run: coros-mcp auth-mobile"
        )

    mobile_base = MOBILE_BASE_URLS.get(auth.region, MOBILE_BASE_URLS["eu"])
    url = mobile_base + ENDPOINTS["sleep"]
    sleep_payload = {
        "allDeviceSleep": 1,
        "dataType": [5],
        "dataVersion": 0,
        "startTime": int(start_day),
        "endTime": int(end_day),
        "statisticType": 1,
    }

    async def _do_request(token: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                params={"accessToken": token},
                json=sleep_payload,
                headers={"Content-Type": "application/json", "accesstoken": token},
            )
            resp.raise_for_status()
            return resp.json()

    body = await _do_request(auth.mobile_access_token)

    if body.get("result") == "1019":  # token expired — auto-refresh once
        if await _refresh_mobile_token(auth):
            body = await _do_request(auth.mobile_access_token)

    if body.get("result") != "0000":
        raise ValueError(f"Coros sleep API error: {body.get('message', 'unknown error')}")

    records: list[SleepRecord] = []
    for item in body.get("data", {}).get("statisticData", {}).get("dayDataList", []):
        sd = item.get("sleepData", {})
        quality = item.get("performance")
        records.append(SleepRecord(
            date=str(item.get("happenDay", "")),
            total_duration_minutes=sd.get("totalSleepTime"),
            phases=SleepPhases(
                deep_minutes=sd.get("deepTime"),
                light_minutes=sd.get("lightTime"),
                rem_minutes=sd.get("eyeTime"),
                awake_minutes=sd.get("wakeTime"),
                nap_minutes=sd.get("shortSleepTime") or None,
            ),
            avg_hr=sd.get("avgHeartRate"),
            min_hr=sd.get("minHeartRate"),
            max_hr=sd.get("maxHeartRate"),
            quality_score=quality if quality != -1 else None,
        ))
    return sorted(records, key=lambda r: r.date)
