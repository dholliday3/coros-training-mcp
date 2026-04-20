# Agent Integration Test Prompt

Use this prompt in Claude Code, Codex, or another MCP-capable agent after wiring the forked COROS MCP into the client.

The recommended local setup is to point the client at `run-coros-mcp.zsh`, which reads COROS credentials from the same macOS Keychain services used by the current MCP:

- `coros-mcp-email`
- `coros-mcp-password`

## Prompt

```text
You are testing the local COROS MCP fork end to end.

Use only the COROS MCP tools for the workflow below. Do not assume the tool outputs; inspect them.

1. Call `list_scheduled_workouts` for the next 14 days.
2. Pick one running workout from the results. If there is no running workout, stop and report that clearly.
3. Call `get_workout` for that workout.
4. Summarize the running-specific fields that are present, especially anything related to distance, target type, target value, intensity type, and intensity range.
5. If the selected workout has a `plan_id`, `id_in_plan`, and `workout_id`, propose the exact `move_scheduled_workout` call needed to move it two days later, but do not execute it unless explicitly asked.
6. Report any missing fields that would block a future `update_workout` implementation for running workouts.

Use absolute dates in `YYYYMMDD` format in your report.
```

## What This Covers

- MCP tool discovery and invocation through the agent
- Schedule flattening for real COROS data
- Workout fetch for a scheduled running workout
- Inspection of running payload fields needed for future edit support

## Notes

- This is a smoke/investigation prompt, not a destructive test.
- Run a separate prompt if you want to actually exercise `move_scheduled_workout`.
