# Installer & Onboarding Plan

Goal: a single command, `uv tool install coros-training-mcp && coros-mcp setup`, walks a new user from zero to a working MCP registered with their AI assistants of choice. No wrapper script, no `.env` editing, no Keychain CLI, no manual JSON surgery.

Status tracked in [TODOS.md](../TODOS.md). Scope estimate: ~10-13 hours of focused work.

## Scope

**In scope**:
- PyPI packaging as `coros-training-mcp` (pip/pipx/uv-tool installable).
- Interactive `coros-mcp setup` wizard: credentials → verify → keyring → assistant picker → config install → smoke test.
- Per-assistant config writers for Claude Code CLI, Claude Desktop, Codex CLI, Cursor.
- Atomic JSON merging — never clobber existing unrelated MCP entries.
- `coros-mcp uninstall` and `coros-mcp setup --reconfigure` for lifecycle management.
- Cross-platform: macOS (primary), Linux, Windows (best-effort — Claude Desktop path handling).
- End-to-end validation against a real `claude mcp list` after install.

**Out of scope (deferred)**:
- Compiled binary via PyInstaller / shiv — not needed for MCP distribution.
- Homebrew formula — nice-to-have for macOS; add later if we see demand.
- Auto-update mechanism — rely on `uv tool upgrade` / `pipx upgrade`.
- GUI / Electron installer.

## Distribution choice: `uv tool install` / `pipx`, not a binary

MCP clients exec a command and stream stdio. What we actually need is a command on the user's `PATH`. `uv tool install coros-training-mcp` (and `pipx install coros-training-mcp` as the fallback) gives us that for free, with:

- No code signing (PyInstaller on macOS is painful).
- No per-arch/per-OS builds.
- Native deps (`pycryptodome`, `keyring`) install via wheels from PyPI.
- Updates via `uv tool upgrade`.

Trade-off: requires Python 3.11+ on the user's machine. `uv` fetches its own interpreter, so this isn't actually a blocker in practice. Users who can't install `uv` or `pipx` (rare) can fall back to the existing manual venv path — we'll keep that in the README as an appendix.

## Packaging (`pyproject.toml`)

Current state: `name = "coros-mcp"`, `version = "0.1"`, flat layout, hatchling. Changes needed:

1. **Rename** to `name = "coros-training-mcp"` to match the GitHub repo and the product positioning.
2. **Version bump** to `0.2.0` for the packaged release.
3. **Description** — replace "MCP server for Coros sleep and HRV data" with the running-first positioning from the README.
4. **Dependencies** — add `questionary>=2.0` for the TUI prompts. Keep the existing set.
5. **Hatch file list** — currently `packages = ["."]` with an `include` list. Verify it ships every `.py` the server imports at runtime:
   - `cli.py`, `server.py`, `coros_api.py`, `models.py`
   - `pace_parser.py`, `run_workout_schema.py`, `strength_workout_schema.py`, `workout_catalog.py`, `traininghub_*.py`
   - `auth/` package
   - `docs/enums/*.json` (loaded at runtime by workout_catalog)
   - **Don't ship**: `tests/`, `docs/` (except enums), `.playwright-browsers/`, the wrapper script
6. **Console script** — already have `coros-mcp = "cli:main"`. Keep it.
7. **Author / URL / license** — add for PyPI display.

## Wizard design (`coros-mcp setup`)

Linear flow using `questionary`. Each step is defensive: validate, re-prompt on failure, never leave half-installed state.

### Step 1 — Credentials

```
Welcome to Coros MCP setup.

Email: ________
Password: ________ (masked)
Region:
  > EU (teameuapi.coros.com)
    US (teamapi.coros.com)
    Asia (teamcnapi.coros.com)
```

Region default based on timezone heuristic: `America/*` → `us`, `Asia/*` → `asia`, everything else → `eu`. User can override.

### Step 2 — Verify

Call `coros_api.login(email, password, region, skip_mobile=True)` to confirm the credentials work against the chosen region. If it fails, show the error and re-prompt — don't force the user to restart the whole wizard. Common failure: wrong region.

Offer mobile auth too (needed for sleep data) with a prompt explaining the mobile-app-logout side effect. Default: skip for now, pull lazily on first sleep query.

### Step 3 — Store

Already-working: `auth.storage.store_token` writes to keyring when available, encrypted file otherwise. Print the storage location explicitly so the user knows where their secret went.

### Step 4 — Detect installed assistants

Each assistant has a detector:

| Assistant | Detection |
|---|---|
| Claude Code CLI | `shutil.which("claude")` is not None |
| Claude Desktop | config dir exists (per-OS path) |
| Codex CLI | `shutil.which("codex")` is not None |
| Cursor | `shutil.which("cursor")` or its config dir exists |

Show only detected ones in the picker. Include a "None of these — show me manual instructions" option as fallback.

### Step 5 — Multi-select

```
Install Coros MCP into which assistants?
  [x] Claude Code (CLI)
  [x] Claude Desktop
  [ ] Codex CLI
```

Remember the selection; no "install in all" shortcut (too destructive).

### Step 6 — Write configs

For each picked assistant:

1. **Resolve the command**: after `pip install`, the `coros-mcp` binary is in an isolated venv. `uv tool install` places it at `~/.local/bin/coros-mcp` or similar. Use `shutil.which("coros-mcp")` to get the absolute path (MCP clients need an absolute path for stability).
2. **Read existing config** (create dir + empty JSON if missing).
3. **Parse**. If unparseable → bail loudly; don't overwrite.
4. **Check for existing `coros` entry**. If present and command matches → skip with a message. If present but command differs → ask to overwrite.
5. **Merge** — add/replace the `coros` key under `mcpServers`, leave everything else alone.
6. **Atomic write** — write to `<config>.tmp`, `os.replace` onto the real path. Never leave a partial file.

Per-assistant specifics:

- **Claude Code**: prefer `subprocess.run(["claude", "mcp", "add", "coros", "--", "<path>", "serve"])` — lets the CLI handle its own config format (currently `~/.claude.json`). Fall back to direct JSON edit if the CLI fails.
- **Claude Desktop**: direct JSON edit. Path:
  - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
  - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
  - Linux: `~/.config/Claude/claude_desktop_config.json`
- **Codex**: `subprocess.run(["codex", "mcp", "add", "coros", "--", "<path>", "serve"])`.
- **Cursor**: direct JSON edit of `~/.cursor/mcp.json` (same schema as Claude Desktop).

### Step 7 — Smoke test

Exec `coros-mcp serve` as a subprocess. Send an MCP initialize request over stdin. Expect a valid initialize response within 5 seconds. Kill the subprocess. Report pass/fail — failure doesn't roll back install but surfaces the problem clearly ("server installed but fails to start; check `coros-mcp auth-status`").

### Step 8 — Done

```
✓ Credentials stored in macOS Keychain.
✓ Installed into Claude Code (restart not required).
✓ Installed into Claude Desktop (restart Claude Desktop to activate).
✓ Server starts and responds correctly.

Try it:
  In Claude Code: "List my Coros runs from last week."
  In Claude Desktop: "What was my HRV trend over the past month?"

Reconfigure:  coros-mcp setup --reconfigure
Uninstall:    coros-mcp uninstall
Logs:         coros-mcp auth-status
```

## Lifecycle commands

- **`coros-mcp setup --reconfigure`** — run the wizard without wiping credentials. Use case: user wants to add Coros to a new assistant after initial setup.
- **`coros-mcp uninstall`** — multi-select picker of currently-installed-into assistants, remove the `coros` entry from each, optionally clear keyring.
- **`coros-mcp auth-status`** — already exists; the wizard instructions point here for troubleshooting.

## File layout

Two new modules to keep `cli.py` from becoming a monster:

- `installer/__init__.py`
- `installer/wizard.py` — top-level flow, prompts.
- `installer/assistants.py` — detection + per-assistant config writers. One function per assistant: `install_claude_code()`, `install_claude_desktop()`, `install_codex()`, `install_cursor()`, plus matching `uninstall_*` / `detect_*` helpers.
- `installer/smoke.py` — subprocess smoke test.
- `installer/regions.py` — timezone → region default.

Everything else stays put.

## Testing

Three layers:

1. **Unit** — config writers against synthetic JSON:
   - Empty config file creates valid structure.
   - Existing unrelated MCP entries preserved after our merge.
   - Existing `coros` entry: replaced when command differs, untouched when identical, reported on conflict.
   - Atomic write: on forced failure mid-write, original file is unchanged.
   - Detection: mock `shutil.which` and `Path.exists` to simulate each combination.
2. **Integration** — run the real `claude mcp add` / `codex mcp add` in a tmp `HOME` if available on the test runner; otherwise skip with a clear marker.
3. **End-to-end** — documented manual validation that runs on a clean machine or fresh user (see Validation section).

## End-to-end validation plan

On a clean machine / fresh user account:

1. `uv tool install coros-training-mcp` (from PyPI or from a locally-built wheel).
2. `coros-mcp setup`.
3. Type dummy creds → confirm they fail gracefully → enter real creds → confirm region validation works.
4. Verify keyring entry exists (`security find-generic-password -s coros-mcp` on macOS).
5. Confirm `claude mcp list` shows `coros` pointing at the absolute path.
6. Confirm `~/Library/Application Support/Claude/claude_desktop_config.json` has the `coros` entry and still contains any pre-existing MCPs (test with a pre-seeded fake entry).
7. Open Claude Code, type a natural prompt that exercises a tool (e.g., "What workouts do I have scheduled this week?"). Confirm the tool call round-trips.
8. `coros-mcp uninstall` → pick Claude Code → confirm entry is removed, other MCPs still present.
9. `coros-mcp setup --reconfigure` → pick a different set of assistants → confirm.
10. Document the whole run in a short log and attach to the release PR.

## Risks & mitigations

- **Keyring unavailable** (Linux headless, CI, corporate VMs) — detect + explain the encrypted-file fallback explicitly in the wizard output, not silently.
- **Claude Desktop config missing** (user hasn't launched the app) — create the directory + minimal file; print a note that they'll need to launch the app once for the change to take effect.
- **Multiple Claude installs on PATH** (e.g., homebrew + manual) — always use the absolute path from `shutil.which` and log which one we picked.
- **User has pre-existing `coros` MCP pointing at the old wrapper script** — detect (command mismatch), ask to replace.
- **`uv tool install` lock contention** — typical `uv` behavior handles this; not our problem.
- **Version upgrades change the `coros-mcp` binary path** — `uv tool`'s managed venv keeps the path stable; `pipx` similarly. Document `uv tool upgrade` as the supported upgrade path.

## Release checklist

- [ ] All items in [TODOS.md](../TODOS.md) under "Packaging & onboarding" are checked.
- [ ] `pytest` green including new installer tests.
- [ ] Manual end-to-end validation run completed and logged.
- [ ] README rewritten; old Keychain/wrapper setup moved to an appendix.
- [ ] `version = "0.2.0"` bumped; CHANGELOG entry added.
- [ ] PyPI credentials configured; test-publish to TestPyPI first.
- [ ] `uv tool install coros-training-mcp` works on a clean machine.
- [ ] `uv tool install coros-training-mcp --index-url ...` works against TestPyPI.
- [ ] Tag the release in git.
