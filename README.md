# coros-training-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for COROS with **first-class running workout authoring and editing** — pace-based intervals, distance targets, repeat groups, and clone-and-swap edits of scheduled runs — on top of the standard COROS training data, scheduling, strength, and activity export tools.

This project is built on top of [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp) and keeps that repository as an upstream reference.

### Why this fork

Upstream is a solid read-oriented COROS MCP, but its authoring story is shaped around time-and-power workouts (cycling, strength). This fork is the one to pick when an agent needs to **build or edit running workouts** end-to-end:

- **Sport-specific run tools** — `create_run_workout` and `update_run_workout` speak distance/pace/HR targets natively, not just duration/power.
- **Shared run-step schema** — `get_run_workout_schema` exposes the exact contract so agents don't guess which fields are valid on create vs. update.
- **Clone-and-swap edits** — change a scheduled run's distance, pace band, or rep count without destroying the calendar entry.
- **Live builder catalog** — enum values (step kinds, target types, intensity types) are extracted from the Training Hub builder itself, not hand-maintained.
- **Workout taxonomy docs** — explicit disambiguation of library workouts, scheduled entries, and plan containers, so agents stop confusing `list_workouts` with the calendar.
- **Broader automated test suite** covering the running-edit paths.

**No API key required.** This server authenticates directly with your Coros Training Hub credentials. Your token is stored securely in your system keyring (or an encrypted local file as fallback), never transmitted anywhere except to Coros.

For the distinction between library workouts, scheduled calendar entries, and plan containers, see [docs/workout-taxonomy.md](./docs/workout-taxonomy.md).

## What You Can Do

Ask your AI assistant questions like:

**Running workouts (the fork's focus):**

- "Create a 5×1km threshold workout at 4:05–4:15/km with 2-minute jog recovery"
- "Change my Tuesday VO2 workout to 6 reps instead of 5"
- "Build a 90-minute long run with 4×8min at marathon pace in the middle"
- "Move Thursday's tempo run to Friday"
- "Replace my scheduled Sunday long run with a 16km progression at easy→steady pace"

**Training data & recovery:**

- "How much deep sleep and REM did I get last week?"
- "What was my HRV trend over the last 4 weeks?"
- "Show me my resting heart rate and training load for last week"
- "How many steps did I average per day this month?"

**Activities, calendar, and other sports:**

- "List my rides from last month"
- "Show me the details of my last long ride"
- "Create a 90-minute sweet spot workout for me"
- "What's on my training calendar next week?"
- "Schedule my VO2 workout for Thursday"
- "Create a 20-minute strength circuit with squats, lunges, and planks"

## Features

| Tool | Description |
|------|-------------|
| `authenticate_coros` | Log in with email and password — token stored securely in keyring |
| `authenticate_coros_mobile` | Log in to the mobile API only (useful for sleep data troubleshooting) |
| `check_coros_auth` | Check whether a valid auth token is present |
| `get_daily_metrics` | Fetch daily metrics (HRV, resting HR, training load, VO2max, stamina, and more) for n weeks (default: 4) |
| `get_sleep_data` | Fetch nightly sleep stages (deep, light, REM, awake) and sleep HR for n weeks (default: 4) |
| `list_activities` | List activities for a date range with summary metrics |
| `get_activity_detail` | Fetch full detail for a single activity (laps, HR zones, power zones) |
| `export_activity_file` | Export a completed activity file in GPX, FIT, TCX, KML, or CSV and save it locally |
| `list_workouts` | List all saved structured workout programs |
| `get_workout_builder_catalog` | Return the checked-in enum registry and live builder catalog for workout construction |
| `get_run_workout_schema` | Return the shared run-step schema used by both `create_run_workout` and `update_run_workout` |
| `create_run_workout` | Create a running workout with explicit run-step kinds and run targets |
| `update_run_workout` | Clone and edit a running workout using run-specific step updates |
| `create_workout` | Create a new structured workout with named steps and power targets |
| `delete_workout` | Delete a workout program from the library |
| `list_planned_activities` | List planned workouts from the Coros training calendar |
| `schedule_workout` | Schedule an existing workout on a calendar day |
| `remove_scheduled_workout` | Remove a scheduled workout from the calendar |
| `create_strength_workout` | Create a structured strength workout with sets, reps, or timed exercises |
| `list_exercises` | Browse the Coros exercise catalogue, especially for strength workouts |

## Workout Taxonomy

Three distinct objects, often confused:

- **library workout** — reusable program in your account. Queried by `list_workouts`.
- **scheduled entry** — a calendar occurrence of a library workout on a specific day. Queried by `list_planned_activities`. May have different IDs than its source workout.
- **plan container** — the higher-level COROS schedule/plan that owns scheduled entries.

GPX/FIT/TCX/KML export applies to completed activities only — structured library workouts use a separate share flow in the app. The MCP writes to COROS server state; device sync is still handled by the COROS app/watch.

See [docs/workout-taxonomy.md](./docs/workout-taxonomy.md) for full detail, and [docs/enum-extraction.md](./docs/enum-extraction.md) for how enum values are discovered from the live Training Hub builder.

---

## Setup

Requires Python ≥ 3.11 and a COROS Training Hub account.

### 1. Install

```bash
git clone https://github.com/dholliday3/coros-training-mcp.git
cd coros-training-mcp
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .                                     # or: uv pip install -e .
```

### 2. Configure credentials

**macOS (recommended): Keychain + wrapper script.** No plaintext credentials in MCP config, auto-loaded at process start.

```bash
security add-generic-password -U -a "$USER" -s "coros-mcp-email"    -w "you@example.com"
security add-generic-password -U -a "$USER" -s "coros-mcp-password" -w "your-password"
./run-coros-mcp.zsh auth-status    # verify
```

**Linux / Windows / anywhere else: `.env` file** in your project directory (or equivalent MCP-scoped env vars):

```
COROS_EMAIL=you@example.com
COROS_PASSWORD=yourpassword
COROS_REGION=eu    # or us, asia
```

The server authenticates on the first request and refreshes tokens transparently. Tokens are stored in your system keyring (or an encrypted local file fallback), never transmitted anywhere except to COROS.

### 3. Register with your MCP client

```bash
# macOS + wrapper (recommended):
claude mcp add coros -- /path/to/coros-training-mcp/run-coros-mcp.zsh

# Raw binary (any platform):
claude mcp add coros -- /path/to/coros-training-mcp/.venv/bin/coros-mcp serve

# Scope to one project only:
claude mcp add --scope project coros -- /path/to/coros-training-mcp/run-coros-mcp.zsh
```

Swap `claude mcp add` for `codex mcp add` if you're on Codex. For Claude Desktop, add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{ "mcpServers": { "coros": { "command": "/path/to/coros-training-mcp/run-coros-mcp.zsh" } } }
```

### CLI commands

```bash
coros-mcp serve         # start the MCP server (used by MCP clients)
coros-mcp auth          # interactive login — stores web + mobile tokens
coros-mcp auth-web      # web token only (skips mobile login; sleep data lazy-loads)
coros-mcp auth-mobile   # mobile token only (used for sleep data)
coros-mcp auth-status   # check authentication state
coros-mcp auth-clear    # remove stored tokens
```

> The mobile login (`apieu.coros.com`) logs you out of the COROS mobile app on your phone. Use `auth-web` to avoid this — the mobile token is obtained automatically on the first sleep-data request.

---

## Tool Reference

### Auth — `authenticate_coros`, `authenticate_coros_mobile`, `check_coros_auth`

You normally don't call these directly — credentials from Keychain or `.env` are picked up automatically. They exist for explicit login/reauth (`{ "email", "password", "region" }`) and status checks (`check_coros_auth` returns `authenticated`, `expires_in_hours`, `mobile_authenticated`, `mobile_token_status`). `authenticate_coros_mobile` is useful for restoring sleep-data access without redoing web auth.

### `get_daily_metrics`

Fetch daily metrics for a configurable number of weeks (default: 4).

```json
{ "weeks": 4 }
```

Returns: `records` (list), `count`, `date_range`

Each record includes:

| Field | Source | Description |
|-------|--------|-------------|
| `date` | — | Date (YYYYMMDD) |
| `avg_sleep_hrv` | dayDetail | Nightly HRV (RMSSD ms) |
| `baseline` | dayDetail | HRV rolling baseline |
| `rhr` | dayDetail | Resting heart rate (bpm) |
| `training_load` | dayDetail | Daily training load |
| `training_load_ratio` | dayDetail | Acute/chronic training load ratio |
| `tired_rate` | dayDetail | Fatigue rate |
| `ati` / `cti` | dayDetail | Acute / chronic training index |
| `distance` / `duration` | dayDetail | Distance (m) / duration (s) |
| `vo2max` | analyse (merge) | VO2 Max (last ~28 days) |
| `lthr` | analyse (merge) | Lactate threshold heart rate (bpm) |
| `ltsp` | analyse (merge) | Lactate threshold pace (s/km) |
| `stamina_level` | analyse (merge) | Base fitness level |
| `stamina_level_7d` | analyse (merge) | 7-day fitness trend |

### `get_sleep_data`

Fetch nightly sleep stage data for a configurable number of weeks (default: 4).

```json
{ "weeks": 4 }
```

Returns: `records` (list), `count`, `date_range`

Each record includes:

| Field | Description |
|-------|-------------|
| `date` | Date (YYYYMMDD) — the morning after the sleep |
| `total_duration_minutes` | Total sleep in minutes |
| `phases.deep_minutes` | Deep sleep |
| `phases.light_minutes` | Light sleep |
| `phases.rem_minutes` | REM sleep |
| `phases.awake_minutes` | Time awake during the night |
| `phases.nap_minutes` | Daytime nap time (null if none) |
| `avg_hr` | Average heart rate during sleep |
| `min_hr` | Minimum heart rate during sleep |
| `max_hr` | Maximum heart rate during sleep |
| `quality_score` | Sleep quality score (null if not computed) |

> **Note:** Sleep data is fetched from the Coros mobile API (`apieu.coros.com`), which uses a separate token from the Training Hub web API. `coros-mcp auth` obtains both tokens, but doing so logs you out of the Coros mobile app. Use `coros-mcp auth-web` to skip mobile login — the mobile token is then obtained automatically on the first sleep data request. The token expires after ~1 hour but **refreshes automatically** on subsequent requests.

### `list_activities`

List activities for a date range.

```json
{ "start_day": "20260101", "end_day": "20260305", "page": 1, "size": 30 }
```

Returns: `activities` (list), `total_count`, `page`

Each activity includes: `activity_id`, `name`, `sport_type`, `sport_name`, `start_time`, `end_time`, `duration_seconds`, `distance_meters`, `avg_hr`, `max_hr`, `calories`, `training_load`, `avg_power`, `normalized_power`, `elevation_gain`

### `get_activity_detail`

Fetch full detail for a single activity. Requires the `sport_type` from `list_activities`.

```json
{ "activity_id": "469901014965714948", "sport_type": 200 }
```

Returns full activity data including laps, HR zones, power zones, and all sport-specific metrics.

> **Note:** Large time-series arrays (`graphList`, `frequencyList`, `gpsLightDuration`) are stripped from the response to keep it manageable.

### `export_activity_file`

Export a completed activity file and save it locally.

```json
{
  "activity_id": "469901014965714948",
  "sport_type": 100,
  "file_type": "gpx",
  "output_path": "/tmp/morning-run.gpx"
}
```

`file_type`: `gpx`, `fit`, `tcx`, `kml`, or `csv`

Returns: `activity_id`, `sport_type`, `file_type`, `file_url`, `output_path`, `downloaded`

### `list_workouts`

List all saved structured workout programs.

```json
{}
```

Returns: `workouts` (list), `count`

Each workout includes: `id`, `name`, `sport_type`, `sport_name`, `estimated_time_seconds`, `exercise_count`, `exercises` (list of steps with `name`, `duration_seconds`, `power_low_w`, `power_high_w`)

### `create_run_workout`

Create a running workout with run-native step kinds (`warmup`, `training`, `rest`, `cooldown`), distance or time targets, and optional pace / HR intensity ranges. Supports repeat groups for intervals.

**5×1km threshold with jog recovery:**

```json
{
  "name": "Tuesday Threshold",
  "steps": [
    {"kind": "warmup",   "name": "Warm-up",  "target_type": "distance", "target_distance_meters": 2000},
    {"repeat": 5, "name": "Main Set", "steps": [
      {"kind": "training", "name": "Rep",      "target_type": "distance", "target_distance_meters": 1000,
       "intensity_type": 3, "intensity_value": 245, "intensity_value_extend": 255, "intensity_display_unit": 2},
      {"kind": "rest",     "name": "Recovery", "target_type": "time",     "target_duration_seconds": 120}
    ]},
    {"kind": "cooldown", "name": "Cool-down", "target_type": "distance", "target_distance_meters": 1500}
  ]
}
```

Pace targets use `intensity_type: 3` with `intensity_value` / `intensity_value_extend` as seconds-per-km and `intensity_display_unit: 2`. For the full field vocabulary (HR zones, percent-of-LT, named intensity presets), call `get_run_workout_schema` or see [run_workout_schema.py](./run_workout_schema.py).

Returns: `workout_id`, `sport_type`, `estimated_time_seconds`, `estimated_distance_meters`, `steps_count`, `message`

### `update_run_workout`

Clone-and-edit an existing running workout. Select each step to change by `step_name`, `step_id`, or `step_index`, and patch it with any run-step field used by `create_run_workout`. The original workout is preserved; a new workout ID is returned. If the original was scheduled, re-schedule the replacement with `schedule_workout`.

```json
{
  "workout_id": "476023839273435149",
  "name": "Tuesday Threshold (6×1km)",
  "step_updates": [
    {"step_name": "Main Set", "repeat": 6},
    {"step_name": "Rep", "target_distance_meters": 1000, "intensity_value": 240, "intensity_value_extend": 250}
  ]
}
```

Returns: `new_workout_id`, `original_workout_id`, `name`, `steps_count`, `message`

### `get_run_workout_schema`

Return the shared run-step schema used by both `create_run_workout` and `update_run_workout`, including allowed step kinds, target types, intensity presets pulled from the live Training Hub builder, and required vs. optional fields. Call this before authoring to avoid guessing which fields are valid.

```json
{}
```

### `create_workout`

Generic time-and-power workout builder (primarily cycling). For running, prefer `create_run_workout`. Supports plain steps and nested `repeat` groups for intervals.

```json
{
  "name": "3×10min Sweet Spot",
  "sport_type": 2,
  "steps": [
    {"name": "Warmup",   "duration_minutes": 10, "power_low_w": 150, "power_high_w": 200},
    {"repeat": 3, "steps": [
      {"name": "Sweet Spot", "duration_minutes": 10, "power_low_w": 265, "power_high_w": 285},
      {"name": "Recovery",   "duration_minutes":  3, "power_low_w": 150, "power_high_w": 175}
    ]},
    {"name": "Cooldown", "duration_minutes": 11, "power_low_w": 150, "power_high_w": 200}
  ]
}
```

`sport_type`: `2` = Indoor Cycling (default), `200` = Road Bike. Returns: `workout_id`, `name`, `total_minutes`, `steps_count`, `message`.

### `delete_workout`

Delete a workout program from the Coros account.

```json
{ "workout_id": "476023839273435149" }
```

The `workout_id` comes from `list_workouts`.

Returns: `deleted`, `workout_id`, `message`

### `list_planned_activities`

List planned activities from the Coros training calendar.

```json
{ "start_day": "20260309", "end_day": "20260316" }
```

Returns: `activities` (list), `count`, `date_range`

### `schedule_workout`

Add an existing workout from your library to the Coros training calendar.

```json
{ "workout_id": "1234567890", "happen_day": "20260312", "sort_no": 1 }
```

Returns: `scheduled`, `workout_id`, `happen_day`

### `remove_scheduled_workout`

Remove a scheduled workout from the Coros training calendar.

```json
{
  "plan_id": "987654321",
  "id_in_plan": "1234567890",
  "plan_program_id": "1234567890"
}
```

`plan_id`, `id_in_plan`, and `plan_program_id` come from `list_planned_activities`. If `plan_program_id` is missing, you can usually reuse `id_in_plan`.

Returns: `removed`, `plan_id`, `id_in_plan`

### `create_strength_workout`

Create a structured strength workout with repeated sets. Exercises must come from the Coros exercise catalogue.

```json
{
  "name": "Leg Circuit",
  "sets": 3,
  "exercises": [
    {
      "origin_id": "54",
      "name": "T1061",
      "overview": "sid_strength_squats",
      "target_type": 3,
      "target_value": 12,
      "rest_seconds": 45
    },
    {
      "origin_id": "130",
      "name": "T1176",
      "overview": "sid_strength_plank",
      "target_type": 2,
      "target_value": 60,
      "rest_seconds": 30
    }
  ]
}
```

`target_type`: `2` = time in seconds, `3` = reps

Returns: `workout_id`, `name`, `sets`, `exercise_count`

### `list_exercises`

List the Coros exercise catalogue for a sport type. Default `sport_type=4` returns strength exercises.

```json
{ "sport_type": 4 }
```

Returns: `exercises` (list), `count`, `sport_type`

---

## Disclaimer

This project uses the **unofficial** COROS Training Hub API. The API may change at any time without notice. Use at your own risk.
