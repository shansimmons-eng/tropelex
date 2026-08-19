# Memory Merge Backup — 2026-08-18

## What happened

Two memory files existed for the same project with different casing:
- `tropelex.json` (lowercase) — the real data: 194 decisions, 22 sessions, 17 patterns, 36 goals
- `Tropelex.json` (capital T) — near-empty stub: 8 decisions, 1 session, 4 patterns, 1 goal

The UI reads from `Tropelex.json` (capital T) because the OpenCode startup hook
(`.opencode/hooks/startup.py`) uses `cwd.name` which returns "Tropelex" (capital T).

The startup hook was creating `Tropelex.json` as an empty stub every time OpenCode
started, because it called `POST /api/memory` with `project_name: "Tropelex"` when
the file didn't exist.

## What was done

1. Fixed startup hook to use `cwd.name.lower()` so it matches `tropelex.json`
2. Merged data from `tropelex.json` into `Tropelex.json` (tropelex.json as base,
   pulled in `context` key from Tropelex.json)
3. Both original files preserved here as-is

## Files in this backup

- `tropelex.json` — original lowercase file (the real data)
- `Tropelex.json` — original capital-T file (the empty stub)
