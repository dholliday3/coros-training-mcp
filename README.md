# coros-training-mcp

**Running-first [MCP](https://modelcontextprotocol.io/) server for COROS.** Author, edit, and schedule running workouts — pace-based intervals, distance targets, repeat groups, clone-and-swap edits — plus sleep, HRV, training load, and activity exports.

Runs locally as a stdio subprocess of your AI assistant. No API key required, no public endpoint. Credentials live in your OS keyring; traffic is outbound only, directly to COROS.

Landing page & screenshots: <https://dholliday3.github.io/coros-training-mcp/>

## Install

```bash
uv tool install coros-training-mcp
coros-mcp setup
```

(`pipx install coros-training-mcp` works too.) The wizard asks for your COROS email, password, and region, verifies them against the API, stores them in your system keyring, detects which AI assistants you have installed (Claude Code, Claude Desktop, Codex CLI, Cursor), writes the MCP entry for each one you pick (preserving any existing entries), and runs a smoke test.

**Requirements:** Python ≥ 3.11 (`uv tool install` fetches it automatically), a COROS Training Hub account, macOS / Linux / Windows.

**Lifecycle:**

```bash
coros-mcp setup --reconfigure   # change credentials or add more assistants
coros-mcp uninstall             # remove from assistants, optionally clear keyring
coros-mcp auth-status           # check stored tokens
uv tool upgrade coros-training-mcp
```

## What you can ask

**Running workouts** (the focus):

- "Create a 5×1km threshold workout at 4:05–4:15/km with 2-minute jog recovery"
- "Change my Tuesday VO2 workout to 6 reps instead of 5"
- "Build a 90-minute long run with 4×8min at marathon pace in the middle"
- "Move Thursday's tempo run to Friday"
- "Replace my scheduled Sunday long run with a 16km progression at easy→steady"

**Recovery & training data:**

- "How much deep sleep and REM did I get last week?"
- "What was my HRV trend over the last 4 weeks?"
- "Show me resting HR and training load for last week"

**Activities, schedule, and other sports:**

- "List my rides from last month"
- "Export my Saturday long run to GPX"
- "What's on my training calendar next week?"
- "Create a 90-minute sweet spot workout"
- "Create a 20-minute strength circuit with squats, lunges, and planks"

## Tools

| Tool | Description |
|------|-------------|
| `create_run_workout` | Create a run with pace/HR/distance targets, repeat groups |
| `update_run_workout` | Clone-and-edit a running workout using run-specific step patches |
| `get_run_workout_schema` | Shared run-step schema used by create + update |
| `create_strength_workout` | Build a strength circuit from the COROS exercise catalog |
| `get_strength_workout_schema` | Strength-step schema (reps, time, rest, exercise swap) |
| `update_workout` | Generic clone-and-patch primitive (strength & cycling) |
| `create_workout` | Generic time-and-power builder (cycling) |
| `list_workouts` / `get_workout` / `delete_workout` | Manage the library |
| `list_scheduled_workouts` / `schedule_workout` | Calendar read & add |
| `move_scheduled_workout` | Move a scheduled entry to another day |
| `replace_scheduled_workout` | Swap a scheduled entry for a different workout |
| `remove_scheduled_workout` | Remove a scheduled entry |
| `get_daily_metrics` | HRV, resting HR, training load, VO₂max, stamina (n weeks) |
| `get_sleep_data` | Deep / light / REM / awake minutes, sleep HR (n weeks) |
| `list_activities` / `get_activity_detail` | Completed activity listing + detail |
| `export_activity_file` | Download a completed activity as GPX / FIT / TCX / KML / CSV |
| `list_exercises` | Browse the COROS exercise catalog |
| `get_workout_builder_catalog` | Live-extracted enum registry for workout authoring |
| `authenticate_coros` / `check_coros_auth` | Explicit login & status (usually automatic) |

### Workout taxonomy

Three distinct objects that are easy to confuse:

- **Library workout** — reusable program in your account. Queried by `list_workouts`.
- **Scheduled entry** — calendar occurrence of a workout on a specific day. Queried by `list_scheduled_workouts`. Has different IDs than its source workout.
- **Plan container** — higher-level training plan that owns scheduled entries.

Full detail: [docs/workout-taxonomy.md](./docs/workout-taxonomy.md). Enum-extraction mechanics: [docs/enum-extraction.md](./docs/enum-extraction.md).

Export (GPX / FIT / TCX / KML / CSV) applies to completed activities only — structured library workouts use a separate share flow in the COROS app. The MCP writes to COROS server state; device sync is still handled by the app/watch.

## Privacy & data handling

- **Credentials**: system keyring (macOS Keychain / Windows Credential Manager / freedesktop Secret Service). If the keyring is unavailable (headless Linux, some VMs), the wizard falls back to an AES-encrypted file at `~/.coros-mcp/credentials.enc` and tells you.
- **Assistant config entries**: live in each assistant's own config file. Only a `coros` entry is added or replaced; other MCP entries are never touched.
- **Network**: outbound TLS only, directly to `teamapi.coros.com` / `teameuapi.coros.com` / `apieu.coros.com`. No telemetry, no analytics, no third-party services.
- **Binary**: `coros-mcp` lives in the `uv tool` / `pipx` isolated venv at an absolute path that MCP clients pin to.

---

## Tool reference

### Auth — `authenticate_coros`, `authenticate_coros_mobile`, `check_coros_auth`

You normally don't call these directly — credentials from the keyring or `.env` are picked up automatically. They exist for explicit login/reauth (`{ "email", "password", "region" }`) and status checks (`check_coros_auth` returns `authenticated`, `expires_in_hours`, `mobile_authenticated`, `mobile_token_status`). `authenticate_coros_mobile` is useful for restoring sleep-data access without redoing web auth.

### `get_daily_metrics`

Fetch daily metrics for a configurable number of weeks (default: 4).

```json
{ "weeks": 4 }
```

Returns: `records` (list), `count`, `date_range`. Each record includes:

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

Returns: `records`, `count`, `date_range`. Each record includes `date`, `total_duration_minutes`, `phases.{deep,light,rem,awake,nap}_minutes`, `avg_hr`, `min_hr`, `max_hr`, `quality_score`.

> Sleep data is fetched from the COROS mobile API (`apieu.coros.com`), which uses a separate token from the Training Hub web API. `coros-mcp auth` obtains both, but doing so logs you out of the COROS mobile app on your phone. Use `coros-mcp auth-web` (or let the wizard's default skip-mobile choice stand) — the mobile token is then fetched lazily on the first sleep-data request and refreshed automatically.

### `list_activities`

```json
{ "start_day": "20260101", "end_day": "20260305", "page": 1, "size": 30 }
```

Returns: `activities`, `total_count`, `page`. Each activity includes `activity_id`, `name`, `sport_type`, `sport_name`, `start_time`, `end_time`, `duration_seconds`, `distance_meters`, `avg_hr`, `max_hr`, `calories`, `training_load`, `avg_power`, `normalized_power`, `elevation_gain`.

### `get_activity_detail`

```json
{ "activity_id": "469901014965714948", "sport_type": 200 }
```

Full activity data including laps, HR zones, power zones, and sport-specific metrics. Large time-series arrays (`graphList`, `frequencyList`, `gpsLightDuration`) are stripped to keep the response manageable.

### `export_activity_file`

```json
{
  "activity_id": "469901014965714948",
  "sport_type": 100,
  "file_type": "gpx",
  "output_path": "/tmp/morning-run.gpx"
}
```

`file_type`: `gpx`, `fit`, `tcx`, `kml`, or `csv`. Returns `activity_id`, `sport_type`, `file_type`, `file_url`, `output_path`, `downloaded`.

### `list_workouts`

```json
{}
```

Returns `workouts`, `count`. Each workout includes `id`, `name`, `sport_type`, `sport_name`, `estimated_time_seconds`, `exercise_count`, `exercises` (steps with `name`, `duration_seconds`, `power_low_w`, `power_high_w`).

### `create_run_workout`

Run-native step kinds (`warmup`, `training`, `rest`, `cooldown`), distance or time targets, optional pace / HR intensity ranges, nested `repeat` groups.

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

Pace targets use `intensity_type: 3` with `intensity_value` / `intensity_value_extend` as seconds-per-km and `intensity_display_unit: 2`. Friendly pace strings like `"4:05-4:15/km"` or `"5:30/mi"` are also accepted on any run step as a `"pace"` field. For the full field vocabulary (HR zones, percent-of-LT, named intensity presets) call `get_run_workout_schema` or see [run_workout_schema.py](./run_workout_schema.py).

Returns: `workout_id`, `sport_type`, `estimated_time_seconds`, `estimated_distance_meters`, `steps_count`, `message`.

### `update_run_workout`

Clone-and-edit an existing running workout. Select each step by `step_name`, `step_id`, or `step_index` and patch it with any run-step field used by `create_run_workout`. Original is preserved; a new workout ID is returned. If the original was scheduled, use `replace_scheduled_workout` (or `schedule_workout`) to swap the calendar entry.

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

Returns: `new_workout_id`, `original_workout_id`, `name`, `steps_count`, `message`.

### `get_run_workout_schema`

Returns the shared schema used by `create_run_workout` and `update_run_workout`: allowed step kinds, target types, intensity presets pulled from the live Training Hub builder, and required vs. optional fields. Call this before authoring to avoid guessing.

### `create_workout`

Generic time-and-power builder (primarily cycling). For running, prefer `create_run_workout`.

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

`sport_type`: `2` = Indoor Cycling (default), `200` = Road Bike.

### `update_workout`

Lower-level clone-and-patch primitive used by `update_run_workout` and for strength edits. Patch steps/exercises by `step_name`, `step_id`, `step_index`, or `origin_id` (strength exercise swap). Supports `rest_seconds`, `target_type` (`time`|`reps`|`distance`), and any field the create side accepts.

### `delete_workout`

```json
{ "workout_id": "476023839273435149" }
```

### `list_planned_activities` / `list_scheduled_workouts`

```json
{ "start_day": "20260309", "end_day": "20260316" }
```

Returns scheduled entries for the window, including library-sourced and plan-embedded programs. Use `list_scheduled_workouts` for the canonical MCP-facing shape.

### `schedule_workout`

```json
{ "workout_id": "1234567890", "happen_day": "20260312", "sort_no": 1 }
```

### `move_scheduled_workout`

Move a scheduled entry to a new day without losing the underlying workout. Handles both library-sourced entries and plan-embedded programs (which have no library counterpart).

```json
{ "plan_id": "987654321", "id_in_plan": "1234567890", "new_happen_day": "20260314" }
```

### `replace_scheduled_workout`

Swap a scheduled entry for a different workout (typically a freshly updated clone) in-place. Preserves the calendar slot and sort order.

```json
{ "plan_id": "987654321", "id_in_plan": "1234567890", "replacement_workout_id": "476023839273435149" }
```

### `remove_scheduled_workout`

```json
{ "plan_id": "987654321", "id_in_plan": "1234567890", "plan_program_id": "1234567890" }
```

If `plan_program_id` is missing from `list_planned_activities`, reuse `id_in_plan`.

### `create_strength_workout`

Structured strength workout with repeated sets. Exercises come from the COROS catalog (`list_exercises`).

```json
{
  "name": "Leg Circuit",
  "sets": 3,
  "exercises": [
    {"origin_id": "54",  "name": "T1061", "overview": "sid_strength_squats", "target_type": 3, "target_value": 12, "rest_seconds": 45},
    {"origin_id": "130", "name": "T1176", "overview": "sid_strength_plank",  "target_type": 2, "target_value": 60, "rest_seconds": 30}
  ]
}
```

`target_type`: `2` = time in seconds, `3` = reps.

### `list_exercises`

```json
{ "sport_type": 4 }
```

`sport_type=4` is strength. Returns `exercises`, `count`, `sport_type`.

---

## Manual setup (advanced)

If you're not using one of the auto-detected assistants, install the server and point any MCP client at it:

```bash
uv tool install coros-training-mcp
coros-mcp auth          # interactive login, stores tokens in keyring
which coros-mcp         # absolute path for the config below
```

```json
{ "mcpServers": { "coros": { "command": "/absolute/path/to/coros-mcp", "args": ["serve"] } } }
```

## Developer setup

```bash
git clone https://github.com/dholliday3/coros-training-mcp.git
cd coros-training-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
pytest
```

## CLI reference

```bash
coros-mcp setup                 # first-time interactive setup
coros-mcp setup --reconfigure   # re-run wizard
coros-mcp uninstall             # remove from assistants
coros-mcp serve                 # start the MCP server (what MCP clients run)
coros-mcp auth                  # re-authenticate (web + mobile)
coros-mcp auth-web              # web token only (sleep data lazy-loads)
coros-mcp auth-mobile           # mobile token only
coros-mcp auth-status           # check stored tokens
coros-mcp auth-clear            # remove stored tokens
```

---

Built on top of [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp), kept as an upstream reference.

## Disclaimer

Uses the **unofficial** COROS Training Hub API. The API may change at any time without notice. Not affiliated with or endorsed by COROS. Use at your own risk.
