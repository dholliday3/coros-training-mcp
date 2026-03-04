# coros-mcp

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that fetches sleep, HRV, and daily metrics from the unofficial Coros Training Hub API and exposes them to AI assistants like Claude.

**No API key required.** This server authenticates directly with your Coros Training Hub credentials. Your token is stored securely in your system keyring (or an encrypted local file as fallback), never transmitted anywhere except to Coros.

## What You Can Do

Ask your AI assistant questions like:

- "What was my HRV trend over the last 4 weeks?"
- "Show me my resting heart rate and training load for last week"
- "How many steps did I average per day this month?"
- "Compare my sleep duration across the last 30 days"

## Features

| Tool | Description |
|------|-------------|
| `authenticate_coros` | Log in with email and password — token stored securely in keyring |
| `check_coros_auth` | Check whether a valid auth token is present |
| `get_hrv_data` | Fetch HRV data (Heart Rate Variability / nightly RMSSD) |
| `get_daily_metrics` | Fetch daily metrics (resting HR, steps, calories, training load, distance) for n weeks (default: 4) |
| `get_sleep_data` | Fetch sleep data — sleep phase breakdown not yet available (see [docs](docs/discover-endpoints.md)) |

---

## Setup

### Option A: Auto-Setup with Claude Code

If you have [Claude Code](https://claude.ai/code), paste this prompt:

```
Set up the Coros MCP server from https://github.com/cygnusb/coros-mcp — clone it, create a venv, install it with pip install -e ., add it to my MCP config, then tell me to run 'coros-mcp auth' in my terminal to authenticate.
```

Claude will handle the installation and guide you through configuration.

### Option B: Manual Setup

#### Step 1: Install

```bash
git clone https://github.com/cygnusb/coros-mcp.git
cd coros-mcp
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Or with `uv`:

```bash
uv pip install -e .
```

#### Step 2: Add to Claude Code

```bash
claude mcp add coros -- python /path/to/coros-mcp/server.py
```

Or add to Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "coros": {
      "command": "/path/to/coros-mcp/.venv/bin/python",
      "args": ["/path/to/coros-mcp/server.py"]
    }
  }
}
```

#### Step 3: Authenticate

Run the following command in your terminal — **outside** of any Claude session:

```bash
coros-mcp auth
```

You will be prompted for your email, password, and region (`eu`, `us`, or `asia`). Your credentials are sent directly to Coros and the token is stored securely in your system keyring (or an encrypted local file as fallback). **You only need to do this once** — the token persists across restarts.

**Other auth commands:**

```bash
coros-mcp auth-status   # Check if authenticated
coros-mcp auth-clear    # Remove stored token
```

---

## Tool Reference

### `authenticate_coros`

Log in with your Coros credentials. The auth token is stored securely in your system keyring (or an encrypted file as fallback).

```json
{ "email": "you@example.com", "password": "yourpassword", "region": "eu" }
```

Returns: `authenticated`, `user_id`, `region`, `message`

### `check_coros_auth`

Check whether a valid token is stored and how long ago it was issued.

```json
{}
```

Returns: `authenticated`, `user_id`, `region`, `expires_in_hours`

### `get_hrv_data`

Fetch nightly HRV (RMSSD) data from the Coros API.

```json
{}
```

Returns: `records` (list), `count`, `date_range`

Each record includes: `date`, `avg_sleep_hrv`

### `get_daily_metrics`

Fetch daily metrics for a configurable number of weeks (default: 4).

```json
{ "weeks": 4 }
```

Returns: `records` (list), `count`, `date_range`

Each record includes: `date`, `avg_sleep_hrv`, `resting_hr`, `steps`, `calories`, `training_load`, `distance`, `duration`

### `get_sleep_data`

Fetch sleep data for one or more days. Note: sleep phase breakdown (deep/light/REM/awake) is not yet available — the mobile-app endpoint has not been discovered yet. See [`docs/discover-endpoints.md`](docs/discover-endpoints.md).

```json
{ "date": "20240315", "days": 7 }
```

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
├── auth/              # Token storage (keyring + encrypted file fallback)
├── pyproject.toml     # Project metadata & dependencies
├── .env.example       # Example configuration
└── docs/
    └── discover-endpoints.md  # Guide for discovering undocumented endpoints
```

## Dependencies

- [fastmcp](https://github.com/jlowin/fastmcp) — MCP framework
- [httpx](https://www.python-httpx.org/) — Async HTTP client
- [pydantic](https://docs.pydantic.dev/) — Data validation
- [python-dotenv](https://github.com/theskumar/python-dotenv) — `.env` support

## Disclaimer

This project uses the **unofficial** Coros Training Hub API. The API may change at any time without notice. Use at your own risk.
