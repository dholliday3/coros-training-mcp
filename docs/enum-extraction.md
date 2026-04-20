# COROS Enum Extraction

This fork now includes:

- a static Training Hub enum extractor in [traininghub_static_enums.py](../traininghub_static_enums.py)
- a live Training Hub builder correlator in [traininghub_live_builder_catalog.py](../traininghub_live_builder_catalog.py)

## Approach

The extractor does not rely on the private COROS workout API or brittle browser clicks.

It downloads three public web assets:

- `https://training.coros.com/`
- the current `en-US.prod.js` locale bundle
- the current `main-*.js` Training Hub application bundle

From those assets it extracts:

- sport categories
- sport type names
- exercise type names and display labels
- target type names and display labels
- rest type names and display labels
- base intensity type names
- intensity unit names

Display labels are resolved from the locale bundle whenever possible. Some target and rest labels appear inline in the main bundle as non-English literals, so the extractor normalizes those with a small override table.

## Static Output

Default output path:

```bash
.venv/bin/python traininghub_static_enums.py
```

This writes:

```text
docs/enums/traininghub-static-enums.json
```

## Live Builder Output

Default output path:

```bash
.venv/bin/python traininghub_live_builder_catalog.py
```

This writes:

```text
docs/enums/traininghub-live-builder-catalog.json
```

The live builder pass logs into Training Hub with COROS credentials from `COROS_EMAIL` / `COROS_PASSWORD` or the same macOS Keychain items used by the MCP launcher:

- `coros-mcp-email`
- `coros-mcp-password`

It then opens the workout builder, captures the available sport list, records the visible builder option sets for each supported activity, and correlates the run builder’s dropdown labels to the raw `training/program/calculate` draft payload fields.

## What This Solves

- Keeps enum discovery automated and repeatable
- Avoids manual clicking through Training Hub just to recover stable enum tables
- Gives us user-facing display values for the core public workout-builder taxonomy
- Stores composite running intensity mappings in the repo so agents do not have to rediscover them live
- Stores per-activity builder option sets for run, trail run, bike, swim, strength, indoor climb, and bouldering
- Makes the extracted catalog available through the MCP tool `get_workout_builder_catalog`

## Current Limitation

The final intensity label shown in the app is partially composite.

For example, the UI distinguishes:

- `Heart Rate`
- `% Max HR`
- `% HR Reserve`
- `% Threshold HR`
- `Pace`
- `% Threshold Pace`
- `Effort Pace`
- `% Effort Pace`

The Training Hub main bundle exposes the base intensity category enum, but the final label also depends on additional fields such as `hrType` and percent flags. So the static extractor gives us:

- stable base intensity enums
- stable display values for target/rest/exercise/sport metadata
- partial intensity display metadata

The live builder correlator closes that remaining gap for the run builder by capturing draft payloads for labels such as `Heart Rate`, `% Max Heart Rate`, `Pace`, `% Threshold Pace`, `Effort Pace`, and `% Effort Pace`.
