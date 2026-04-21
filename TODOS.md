# COROS MCP Fork Todos

This file tracks the actionable work for the fork. Strategy, scope, and architectural context live in [CLAUDE.md](./CLAUDE.md).

Major work-in-progress plans:
- [Installer & onboarding plan](./docs/installer-plan.md) — `uv tool install` + `coros-mcp setup` wizard, end-to-end packaged distribution.
- [Release process](./docs/release.md) — OIDC trusted publishing via GitHub Actions (no long-lived PyPI tokens).

## Current Phase

- [x] Create `get_workout`
- [x] Create `list_scheduled_workouts`
- [x] Create `move_scheduled_workout`
- [x] Preserve running-relevant workout and schedule fields needed for inspection
- [x] Design and implement `update_workout` request and response contract
- [x] Implement `replace_scheduled_workout`

## Next Up

- [x] Add opt-in destructive end-to-end live MCP workflow test with cleanup
- [x] Shift the product direction toward sport-specific create/update tools instead of one generic create surface
- [x] Add `create_run_workout`
- [x] Add `update_run_workout`
- [x] Keep generic scheduling and library tools as the cross-cutting layer
- [ ] Treat generic `create_workout` as legacy/internal once running-specific creation is stable
- [x] Validate `update_workout` against live running workouts from the COROS account
- [x] Validate `replace_scheduled_workout` against a real scheduled workout in a safe live test window
- [x] Add a live complex run workflow test with repeats and mixed targets
- [x] Split live Training Hub builder catalog coverage from the normal live MCP workflow tests
- [ ] Document recommended edit patterns for common requests
- [ ] Add live MCP test covering `move_scheduled_workout` against a plan-embedded program from a subscribed training plan (current live tests only cover library-sourced moves — the plan-embedded path is only unit-tested)
- [ ] Add live MCP test covering `replace_scheduled_workout` against a plan-embedded strength workout (exercises the strength + plan-embedded + clone-and-patch combination end-to-end)

## Common Patch Helpers

- [x] Change rep distance
- [x] Change workout date
- [x] Shorten or lengthen warm-up and cool-down
- [ ] Change rep count with verified live running data
- [x] Change target pace with verified COROS running intensity enums
- [x] Add ergonomic parsing for human run pace inputs such as `4:10-4:20 /km` and map them onto the shared run intensity fields

## Sport-Specific Tooling

- [x] Define run workout schema with explicit exercise kinds: `warmup`, `training`, `rest`, `cooldown`, `interval`
- [x] Define run-specific target schema with `time` and `distance`
- [x] Define run-specific intensity schema and map friendly names to COROS enums where verified
- [ ] Design bike-specific create/update tools after the run schema settles
- [x] Add exercise-level patches for strength workouts (change reps or duration, swap exercises via `origin_id`, adjust rest via `rest_seconds`, modify target_type with `reps` alias) — these now flow through the existing `update_workout` tool
- [x] Expose a shared strength-step schema through an MCP tool (`get_strength_workout_schema`) so create/update share vocabulary, mirroring the run-step contract
- [x] Capture live builder option lists for run, trail run, bike, swim, strength, indoor climb, and bouldering
- [ ] Keep swim / climb / bouldering in mind for future create/update tools, but do not implement them yet
- [x] Expose the checked-in workout builder catalog through an MCP tool for agent use
- [x] Expose a dedicated shared run-step schema through an MCP tool so create/update use the same field vocabulary

## API Research

- [ ] Determine whether COROS has an in-place workout update endpoint
- [x] Add automated static Training Hub enum extraction from public frontend bundles
- [x] Add automated live Training Hub builder correlation and check the output into the repo
- [x] Enumerate COROS running intensity enums used by the app well enough for friendly pace editing
- [x] Resolve composite running intensity display mapping (`intensityType` + `hrType` + percent flags)
- [x] Extract live builder option sets for the remaining supported activity types
- [ ] Measure how much raw payload preservation is needed to avoid destructive rewrites
- [ ] Determine whether completed strength results can be edited through the same backend used by the app or watch
- [ ] Verify `/training/schedule/update` accepts plan-embedded program shapes directly (missing `access`, `authorId`, `status`, etc. that library programs have) — if not, add a `_prepare_embedded_program_for_scheduling` helper that fills those defaults before POST

## Strength Logging

- [ ] Deferred for now
- [ ] Capture app traffic while editing strength results
- [ ] Identify write endpoint, auth mode, and payload shape
- [ ] Verify whether strength result edits are session-bound, watch-bound, or app-only
- [ ] Add `log_strength_results` only after the endpoint is verified

## Packaging & Onboarding

See [docs/installer-plan.md](./docs/installer-plan.md) for the full design.

- [x] Tighten `pyproject.toml`: rename to `coros-training-mcp`, version `0.2.0`, add `questionary` dep, verify wheel includes every runtime module
- [x] Implement `coros-mcp setup` wizard: questionary credentials prompt, live login verify with re-prompt on failure, keyring storage with explicit fallback messaging
- [x] Add assistant detection + config writers: Claude Code CLI, Claude Desktop, Codex CLI, Cursor. Atomic JSON merge that preserves unrelated MCP entries.
- [x] Add post-install smoke test: exec `coros-mcp serve` over stdio, send `initialize` request, confirm response
- [x] Add `coros-mcp uninstall` and `coros-mcp setup --reconfigure` lifecycle commands
- [x] Unit + integration tests for installer (config writers, detection, smoke test)
- [x] End-to-end release validation on a clean environment per the plan's validation checklist (local wheel → `uv tool install` → `coros-mcp serve` smoke test → `claude mcp add` subprocess round-trip → atomic config merge preserving other MCP entries)
- [x] Rewrite README setup section around the packaged flow; move the manual Keychain/wrapper path to an appendix
- [x] Set up GitHub Actions release workflow with OIDC trusted publishing (`.github/workflows/release.yml`) — no long-lived API tokens; tag-triggered; verifies tag↔pyproject version match; enforces strict semver tags; runs tests; smoke-tests the built wheel
- [x] Register pending trusted publisher on PyPI (`pypi` env) per [docs/release.md](./docs/release.md)
- [x] Create `pypi` GitHub environment with tag-scoped deployment policy (`v*`)
- [x] Cut `v0.2.0` → first real PyPI publish (claims the project name) — shipped 2026-04-21, https://pypi.org/project/coros-training-mcp/0.2.0/
- [x] Publish a GitHub Pages install landing page — live at https://dholliday3.github.io/coros-training-mcp/ (served from `gh-pages` branch; static, no JS, COROS-inspired dark styling)

## Upstreaming

- [ ] Identify generic fixes safe to upstream
- [ ] Keep running-specific product direction in the fork unless upstream wants it
