# COROS MCP Fork Plan

This repository is a local fork of `cygnusb/coros-mcp` intended to become a running-first, editable COROS MCP rather than a mostly read-only metrics/workout wrapper.

Actionable implementation tasks live in [TODOS.md](./TODOS.md).
Terminology for library workouts, scheduled entries, and plan containers lives in [docs/workout-taxonomy.md](./docs/workout-taxonomy.md).

## Goals

- Support first-class editing of scheduled running workouts.
- Support running workout variables such as distance, pace, repeats, rest, and date changes.
- Keep the MCP tool surface small and stable.
- Hide sport-specific payload complexity behind a unified workout schema.
- Preserve compatibility with upstream where it does not fight the fork's direction.

## Non-Goals

- Do not keep separate user-facing tool families for bike, run, and strength unless the backend makes a unified tool impossible.
- Do not store raw account credentials in repo files.
- Do not promise post-workout strength result logging until the write endpoint is verified.

## Current State

The upstream project already supports:

- Web and mobile auth against unofficial COROS endpoints
- Daily metrics, sleep, HRV, activities
- Workout creation and deletion
- Schedule listing, schedule add, and schedule remove
- Strength workout creation from the COROS exercise catalogue

The main gap is that workout creation is currently shaped around time-based, power-oriented workouts and does not expose a generic edit path for running workouts.

## Product Direction

The fork should present a small set of MCP tools:

- `list_workouts`
- `get_workout`
- `create_run_workout`
- `update_run_workout`
- `create_workout` as a compatibility path for simpler non-running construction
- `update_workout` as the lower-level clone-and-patch primitive
- `delete_workout`
- `list_scheduled_workouts`
- `move_scheduled_workout`
- `replace_scheduled_workout`

Optional later tools:

- `clone_workout`
- `log_strength_results`
- `list_activity_results`

## Unified Workout Schema

User-facing tools should share one schema with per-step variants instead of separate tool families.

Top-level workout shape:

```json
{
  "name": "Tuesday Threshold",
  "sport": "run",
  "steps": [
    {
      "kind": "segment",
      "name": "Warm-up",
      "target": { "type": "distance", "value": 3000, "unit": "m" },
      "intensity": { "type": "open" }
    },
    {
      "kind": "repeat",
      "count": 5,
      "steps": [
        {
          "kind": "segment",
          "name": "Rep",
          "target": { "type": "distance", "value": 1000, "unit": "m" },
          "intensity": { "type": "pace", "low": 245, "high": 255, "unit": "s_per_km" }
        },
        {
          "kind": "segment",
          "name": "Recovery",
          "target": { "type": "time", "value": 120, "unit": "s" },
          "intensity": { "type": "open" }
        }
      ]
    }
  ]
}
```

Rules:

- `sport` drives payload conversion, not tool choice.
- `target.type` should support at least `time`, `distance`, and `open`.
- `intensity.type` should support at least `pace`, `power`, `hr`, and `open`.
- Strength steps should use exercise IDs plus reps, weight, duration, and rest fields.
- The MCP should preserve unknown raw COROS fields when possible so edits are less destructive.

## Why A Unified Tool Surface Still Needs Sport-Specific Adapters

The user-facing interface can stay simple, but the backend adapter cannot be fully generic because COROS payloads are not the same across sports.

Examples:

- Running workouts care about distance and pace targets.
- Cycling workouts often use time and power targets.
- Strength workouts use exercise catalogue IDs, reps, duration, and rest.

The right split is:

- Generic MCP tools and generic workout schema at the top
- Sport-specific payload mappers under the hood

## Edit Semantics

There are two different edit classes.

### 1. Schedule edits

Use this for date or ordering changes only.

Implementation:

- Fetch scheduled item
- Remove scheduled entry
- Re-schedule the same workout on a new day or new sort order

### 2. Workout content edits

Use this for distance, pace, interval, or exercise changes.

Implementation:

- Fetch raw workout
- Convert raw payload to unified schema
- Apply requested patch
- Create replacement workout
- Re-schedule replacement if the original was scheduled
- Optionally delete the old workout after confirmation

This is clone-and-swap, not in-place mutation, unless a reliable update endpoint is found.

## Roadmap Summary

- Phase 1 is focused on workout fetch, scheduled workout inspection, and safe move semantics.
- Phase 2 adds the unified running schema and clone-and-swap workout updates.
- Strength result logging remains a separate research track until the write endpoint is confirmed.

## Repository Plan

- Keep this fork rebased or merged from upstream selectively.
- Upstream small generic fixes when they are clean and not opinionated.
- Keep running-edit workflow in the fork even if upstream does not want the broader product direction.
- Keep local auth wrappers and secret management outside the committed repo where possible.

## Local Auth Guidance

- COROS credentials should come from local secret storage, not committed files.
- The local launcher script may read from macOS Keychain or another secret manager and then start the MCP server.
- Do not commit real credentials, token captures, or network traces containing secrets.

## Status Tracking

Use [TODOS.md](./TODOS.md) for implementation status, research work, and upstreaming candidates.
