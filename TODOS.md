# COROS MCP Fork Todos

This file tracks the actionable work for the fork. Strategy, scope, and architectural context live in [CLAUDE.md](./CLAUDE.md).

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

## Common Patch Helpers

- [x] Change rep distance
- [x] Change workout date
- [x] Shorten or lengthen warm-up and cool-down
- [ ] Change rep count with verified live running data
- [ ] Change target pace with verified COROS running intensity enums

## Sport-Specific Tooling

- [x] Define run workout schema with explicit exercise kinds: `warmup`, `training`, `rest`, `cooldown`, `interval`
- [x] Define run-specific target schema with `time` and `distance`
- [x] Define run-specific intensity schema and map friendly names to COROS enums where verified
- [ ] Design bike-specific create/update tools after the run schema settles
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

## Strength Logging

- [ ] Deferred for now
- [ ] Capture app traffic while editing strength results
- [ ] Identify write endpoint, auth mode, and payload shape
- [ ] Verify whether strength result edits are session-bound, watch-bound, or app-only
- [ ] Add `log_strength_results` only after the endpoint is verified

## Upstreaming

- [ ] Identify generic fixes safe to upstream
- [ ] Keep running-specific product direction in the fork unless upstream wants it
