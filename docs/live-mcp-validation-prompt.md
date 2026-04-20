# Live MCP Validation Prompt

Use this prompt in Claude Code, Codex, or another MCP-capable agent after wiring the client to the forked COROS MCP.

This prompt is designed to validate the currently implemented tools against a live COROS account without making destructive changes by default.

## Prompt

```text
You are validating the local COROS MCP fork against the live COROS account.

Use only COROS MCP tools for this task. Do not invent outputs. Inspect tool results directly.

Rules:
- Use absolute dates in YYYYMMDD format.
- Do not move, delete, or reschedule anything unless I explicitly confirm after you show me the exact target workout.
- Prefer running workouts when choosing examples.
- If a tool returns an error, report the exact error and continue with the remaining safe checks when possible.

Validation steps:

1. Call `list_workouts`.
2. Summarize how many workouts exist and how many appear to be running workouts (`sport_type = 100`).
3. Pick one running workout and call `get_workout` on it.
4. Summarize the fields present on that workout that matter for future editing:
   - workout id
   - sport type / sport name
   - estimated distance
   - estimated time
   - target type / target value
   - per-step target type / target value
   - per-step intensity type / intensity values
   - any running-specific overview labels

5. Call `list_scheduled_workouts` for the next 14 days.
6. Summarize:
   - total scheduled workouts
   - which ones are running workouts
   - for one running scheduled workout, show:
     - plan_id
     - id_in_plan
     - plan_program_id
     - happen_day
     - sort_no
     - workout_id
     - workout_name

7. For that same scheduled running workout, explain whether `move_scheduled_workout` has enough information to move it safely and show the exact tool call you would make to move it two days later.
8. Do not execute the move yet. Ask me for confirmation first.

9. After the safe checks, give me a gap report:
   - which currently implemented tools worked
   - what fields still look insufficient for `update_workout`
   - whether the current data looks rich enough to support running distance edits in a future clone-and-swap implementation

Current tool expectations:
- Implemented and should work: `list_workouts`, `get_workout`, `list_scheduled_workouts`, `move_scheduled_workout`
- Not implemented yet: `update_workout`, `replace_scheduled_workout`, `log_strength_results`
```

## Optional Destructive Follow-Up

Only run this if you explicitly want to test a real move:

```text
Now execute the exact `move_scheduled_workout` call you proposed for the selected running workout.
After it completes, call `list_scheduled_workouts` again for the same date window and verify:
- the workout is gone from the old day
- the workout appears on the new day
- there is no duplicate leftover entry
If there is a duplicate or mismatch, report the exact IDs and dates.
```
