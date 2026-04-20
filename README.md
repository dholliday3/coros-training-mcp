# coros-training-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for COROS training data, workout authoring, workout scheduling, and builder-aware agent tooling.

This project is built on top of [cygnusb/coros-mcp](https://github.com/cygnusb/coros-mcp) and keeps that repository as an upstream reference. It extends the original project with workout taxonomy docs, sport-specific running tools, live builder catalog extraction, shared run-step schemas, and a much broader automated test suite.

**No API key required.** This server authenticates directly with your Coros Training Hub credentials. Your token is stored securely in your system keyring (or an encrypted local file as fallback), never transmitted anywhere except to Coros.

For the distinction between library workouts, scheduled calendar entries, and plan containers, see [docs/workout-taxonomy.md](./docs/workout-taxonomy.md).

## What You Can Do

Ask your AI assistant questions like:

- "How much deep sleep and REM did I get last week?"
- "What was my HRV trend over the last 4 weeks?"
- "Show me my resting heart rate and training load for last week"
- "How many steps did I average per day this month?"
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

The fork distinguishes between three related objects:

- `library workout`: a reusable workout/program in your account library
- `scheduled workout entry`: a calendar occurrence on a specific day
- `plan container`: the higher-level COROS schedule/plan that owns scheduled entries

Important consequences:

- `list_workouts` shows library workouts, not calendar entries
- `list_scheduled_workouts` shows scheduled entries, not the full library
- scheduling a workout may create a scheduled copy with different IDs than the original library workout
- the MCP writes to COROS server state, but device sync is still handled by the COROS app/watch
- running creation/editing is moving toward sport-specific tools like `create_run_workout` and `update_run_workout`
- `get_run_workout_schema` exposes the exact shared run-step contract so agents do not need to guess which fields are valid on create vs update
- the older generic `create_workout` remains available, but it is still shaped around simpler time/power workout construction
- GPX/FIT/TCX/KML export applies to completed activities, not to structured library workouts; structured workouts use a separate share flow in the app

See [docs/workout-taxonomy.md](./docs/workout-taxonomy.md) for the full explanation.

For automated enum discovery from public Training Hub assets and the live Training Hub builder, see [docs/enum-extraction.md](./docs/enum-extraction.md).

---

## Setup

### Recommended Local Setup

For local use on macOS, the recommended path in this repo is:

1. install the repo into a local virtualenv
2. store COROS credentials in macOS Keychain
3. point your MCP client at the included wrapper script [run-coros-mcp.zsh](./run-coros-mcp.zsh)

That gives you:

- no plaintext COROS credentials in your MCP config
- automatic `COROS_EMAIL` / `COROS_PASSWORD` loading at process start
- a default `COROS_REGION` value with local override support

The wrapper expects these Keychain items:

- service `coros-mcp-email`
- service `coros-mcp-password`

Add them with:

```bash
security add-generic-password -U -a "$USER" -s "coros-mcp-email" -w "you@example.com"
security add-generic-password -U -a "$USER" -s "coros-mcp-password" -w "your-coros-password"
```

Then point your MCP client at:

```bash
/path/to/coros-training-mcp/run-coros-mcp.zsh
```

### Standard Cross-Platform Path

If you are not on macOS, or you would rather avoid the wrapper script, the more standard setup path is:

1. install the repo into a local virtualenv
2. run the raw `coros-mcp` binary from that virtualenv
3. provide credentials via a local `.env` file or MCP-scoped environment variables

That looks like:

```bash
/path/to/coros-training-mcp/.venv/bin/coros-mcp serve
```

This path is a better fit when:

- you want the most typical Python MCP server setup
- you are using Linux or Windows
- you prefer explicit env vars over macOS Keychain integration
- you want the same launch pattern as the upstream `cygnusb/coros-mcp` repo

### Option A: Auto-Setup with Claude Code

If you have [Claude Code](https://claude.ai/code), paste this prompt:

```
Set up the COROS Training MCP server from https://github.com/dholliday3/coros-training-mcp — clone it, create a venv, install it with pip install -e ., configure the included run-coros-mcp.zsh wrapper for MCP, and tell me how to add my COROS credentials to macOS Keychain.
```

Claude will handle the installation and guide you through configuration.

### Option B: Manual Setup

#### Step 1: Install

```bash
git clone https://github.com/dholliday3/coros-training-mcp.git
cd coros-training-mcp
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Or with `uv`:

```bash
uv pip install -e .
```

#### Step 2: Add to Your MCP Client

Recommended on macOS:

```bash
claude mcp add coros -- /path/to/coros-training-mcp/run-coros-mcp.zsh
```

Or for Codex:

```bash
codex mcp add coros -- /path/to/coros-training-mcp/run-coros-mcp.zsh
```

If you prefer to launch the raw binary directly instead of the wrapper:

```bash
claude mcp add coros -- /path/to/coros-training-mcp/.venv/bin/coros-mcp serve
```

Equivalent Codex example:

```bash
codex mcp add coros -- /path/to/coros-training-mcp/.venv/bin/coros-mcp serve
```

To limit the MCP to a specific project only (recommended):

```bash
cd /path/to/your/project
claude mcp add --scope project coros -- /path/to/coros-training-mcp/.venv/bin/coros-mcp serve
```

Or add to Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "coros": {
      "command": "/path/to/coros-training-mcp/run-coros-mcp.zsh"
    }
  }
}
```

Or, for the standard raw-binary path:

```json
{
  "mcpServers": {
    "coros": {
      "command": "/path/to/coros-training-mcp/.venv/bin/coros-mcp",
      "args": ["serve"]
    }
  }
}
```

#### Step 3: Configure Credentials

**Option A — macOS Keychain + wrapper script (recommended for local use):**

Add the expected Keychain items:

```bash
security add-generic-password -U -a "$USER" -s "coros-mcp-email" -w "you@example.com"
security add-generic-password -U -a "$USER" -s "coros-mcp-password" -w "your-coros-password"
```

Then verify the wrapper can read them:

```bash
/path/to/coros-training-mcp/run-coros-mcp.zsh auth-status
```

You can override the default region if needed:

```bash
COROS_REGION=eu /path/to/coros-training-mcp/run-coros-mcp.zsh auth-status
```

**Option B — `.env` file:**

Create a `.env` file in your project directory:

```
COROS_EMAIL=you@example.com
COROS_PASSWORD=yourpassword
COROS_REGION=eu
```

The server authenticates automatically on the first request and re-authenticates transparently whenever the token expires. No manual auth step needed.

If your MCP client supports inline env vars, that works too. For example, the same raw-binary setup can be configured with `COROS_EMAIL`, `COROS_PASSWORD`, and `COROS_REGION` set in the MCP server environment instead of using a `.env` file.

**Option C — Manual authentication:**

Run the following command in your terminal — **outside** of any Claude session:

```bash
coros-mcp auth
```

You will be prompted for your email, password, and region (`eu`, `us`, or `asia`). This stores both the Training Hub web token and the mobile API token (used for sleep data). Your credentials are sent directly to Coros and the tokens are stored securely in your system keyring (or an encrypted local file as fallback). **You only need to do this once** — the tokens persist across restarts.

> **Note:** The mobile login (`apieu.coros.com`) will log you out of the Coros mobile app on your phone. If you want to avoid this, use `coros-mcp auth-web` instead — it stores only the web token, and the mobile token will be obtained automatically when you first request sleep data.

**Other auth commands:**

```bash
/path/to/coros-training-mcp/run-coros-mcp.zsh        # start via Keychain-backed wrapper
/path/to/coros-training-mcp/run-coros-mcp.zsh auth-status
coros-mcp serve         # Start the MCP server (used by Claude Code / Claude Desktop)
coros-mcp auth-web      # Web API only — skips mobile login (sleep data obtained lazily)
coros-mcp auth-mobile   # Mobile API only (sleep data)
coros-mcp auth-status   # Check if authenticated
coros-mcp auth-clear    # Remove stored tokens
```

---

## Tool Reference

### `authenticate_coros`

Log in with your Coros credentials. The auth token is stored securely in your system keyring (or an encrypted file as fallback).

```json
{ "email": "you@example.com", "password": "yourpassword", "region": "eu" }
```

Returns: `authenticated`, `user_id`, `region`, `message`

### `authenticate_coros_mobile`

Authenticate with the Coros mobile API only. This is mainly useful if you need to restore sleep-data access without redoing full web authentication.

```json
{ "email": "you@example.com", "password": "yourpassword", "region": "eu" }
```

Returns: `authenticated`, `user_id`, `region`, `message`

### `check_coros_auth`

Check whether valid web and mobile tokens are stored and how long the web token remains valid.

```json
{}
```

Returns: `authenticated`, `user_id`, `region`, `expires_in_hours`, `mobile_authenticated`, `mobile_token_status`

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

### `create_workout`

Create a new structured workout. Workouts appear in the Coros app and can be synced to the watch. Steps can be plain steps or repeat groups for intervals.

**Plain steps:**

```json
{
  "name": "Sweet Spot 90min",
  "sport_type": 2,
  "steps": [
    {"name": "15:00 Warmup",     "duration_minutes": 15, "power_low_w": 148, "power_high_w": 192},
    {"name": "20:00 Sweet Spot", "duration_minutes": 20, "power_low_w": 260, "power_high_w": 275},
    {"name": "5:00 Rest",        "duration_minutes":  5, "power_low_w": 100, "power_high_w": 150},
    {"name": "20:00 Sweet Spot", "duration_minutes": 20, "power_low_w": 260, "power_high_w": 275},
    {"name": "30:00 Cooldown",   "duration_minutes": 30, "power_low_w": 100, "power_high_w": 192}
  ]
}
```

**With repeat groups (intervals):**

```json
{
  "name": "3×10min Sweet Spot",
  "sport_type": 2,
  "steps": [
    {"name": "Warmup",    "duration_minutes": 10, "power_low_w": 150, "power_high_w": 200},
    {"repeat": 3, "steps": [
      {"name": "Sweet Spot", "duration_minutes": 10, "power_low_w": 265, "power_high_w": 285},
      {"name": "Recovery",   "duration_minutes":  3, "power_low_w": 150, "power_high_w": 175}
    ]},
    {"name": "Cooldown",  "duration_minutes": 11, "power_low_w": 150, "power_high_w": 200}
  ]
}
```

`sport_type`: `2` = Indoor Cycling (default), `200` = Road Bike

Returns: `workout_id`, `name`, `total_minutes`, `steps_count`, `message`

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

## Requirements

- Python ≥ 3.11
- A Coros account (Training Hub)

---

## Project Structure

```
coros-mcp/
├── server.py          # MCP server with tool definitions
├── coros_api.py       # Coros API client (auth, requests, parsers)
├── models.py          # Pydantic data models
├── cli.py             # CLI entry point (serve, auth, auth-mobile, auth-status, auth-clear)
├── auth/              # Token storage (keyring + encrypted file fallback)
├── pyproject.toml     # Project metadata & dependencies
└── docs/
    └── mobile-token.md  # Mobile API token background (legacy reference)
```

## Dependencies

- [fastmcp](https://github.com/jlowin/fastmcp) — MCP framework
- [httpx](https://www.python-httpx.org/) — Async HTTP client
- [pydantic](https://docs.pydantic.dev/) — Data validation
- [pycryptodome](https://pycryptodome.readthedocs.io/) — AES encryption for mobile API auth
- [keyring](https://github.com/jaraco/keyring) — Secure token storage
- [python-dotenv](https://github.com/theskumar/python-dotenv) — `.env` support

## Disclaimer

This project uses the **unofficial** Coros Training Hub API. The API may change at any time without notice. Use at your own risk.
