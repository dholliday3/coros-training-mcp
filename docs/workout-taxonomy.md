# COROS Workout Taxonomy

This fork uses the following terms consistently when talking about COROS workout data.

## 1. Library Workout

A library workout is a reusable workout/program saved in the account-level workout library.

In the current MCP, these come from:

- `list_workouts`
- `get_workout`
- `create_workout`
- `update_workout`
- `delete_workout`

Backend endpoint:

- `/training/program/query`

Important notes:

- This is the object you create in the library first.
- This is not automatically a calendar event.
- This is also not necessarily the exact object that ends up attached to a scheduled calendar entry.

## 2. Scheduled Workout Entry

A scheduled workout entry is a workout occurrence on a specific day in the training calendar.

In the current MCP, these come from:

- `list_scheduled_workouts`
- `list_planned_activities`
- `schedule_workout`
- `remove_scheduled_workout`
- `move_scheduled_workout`
- `replace_scheduled_workout`

Backend endpoints:

- `/training/schedule/query`
- `/training/schedule/update`

Important fields on a scheduled entry:

- `plan_id`
- `id_in_plan`
- `plan_program_id`
- `happen_day`
- `sort_no`

Important notes:

- A scheduled workout entry is a calendar item, not just a reference to a library workout.
- COROS may materialize a scheduled copy with different IDs than the original library workout.
- That is why scheduled operations must use schedule identifiers like `plan_id` and `id_in_plan`, not just `workout_id`.

## 3. Plan Container

A plan container is the higher-level training calendar/plan object that owns scheduled entries.

In raw schedule payloads this appears through fields like:

- `planId`
- `planIdIndex`
- top-level schedule metadata returned by `/training/schedule/query`

Important notes:

- A plan may represent an official plan, imported plan, or another COROS schedule container.
- Multiple scheduled entries can belong to the same plan.
- The current fork does not expose a first-class "plan management" tool yet; it focuses on scheduled entries inside plans.

## 4. Program Inside A Schedule

The raw schedule response also includes `programs`, which are workout payloads associated with scheduled entities.

Important notes:

- These often look similar to library workouts.
- They are not guaranteed to have the same identity as the original library workout.
- In practice, COROS may rewrite or reassign IDs when a workout is scheduled.

This is why the fork uses clone-and-swap semantics for schedule-safe editing:

- create or patch a library workout
- schedule the replacement
- remove the old scheduled entry

## Practical Mental Model

The safest mental model is:

1. Create or edit a library workout
2. Schedule it onto the calendar
3. Treat the scheduled calendar entry as its own object with plan-specific IDs
4. Let the COROS app/watch sync handle delivery to the device

## Device Sync

The MCP writes to COROS server state. It does not push directly to the watch.

So the workflow is:

- library workout created or updated in COROS
- optionally scheduled in COROS
- COROS app/watch sync propagates it to the device

## How The Fork Maps Tools To Taxonomy

- Library workout tools:
  - `list_workouts`
  - `get_workout`
  - `create_workout`
  - `update_workout`
  - `delete_workout`

- Scheduled workout tools:
  - `list_scheduled_workouts`
  - `schedule_workout`
  - `remove_scheduled_workout`
  - `move_scheduled_workout`
  - `replace_scheduled_workout`

- Raw/legacy schedule inspection:
  - `list_planned_activities`

## Current Confidence

The fork now handles the taxonomy correctly enough for:

- viewing the library workout list
- viewing scheduled workout entries
- moving scheduled entries
- replacing scheduled entries with edited clones

The remaining caveat is that COROS identity mapping across library workouts and scheduled copies is not perfectly stable, so code and tests should not assume that a scheduled item always preserves the original library workout ID.
