#!/usr/bin/env python3
"""
Normalize Agent Identity — one-time repair of already-stored agent_name
values so historical data reflects the same canonicalization the code now
applies at write time (core/agent_identity.normalize_agent_name).

The code fix alone only prevents *future* drift ("Claude" vs
"claude-sonnet-5" no longer diverge going forward) — it does not
retroactively merge data already written under the old, unnormalized
names. This script does that merge, across three independent storage
locations that don't share one file:

- memory/agent_skills/{project}.json  -- skills_by_agent is an aggregate
  dict; two keys folding to the same canonical name are MERGED (counters
  summed, score recomputed), not just renamed. sessions[].agent is a
  simple per-record field rewrite.
- memory/replays/{project}/index.json and each
  memory/replays/{project}/{session_id}.json -- agent field, independent
  records, rewritten in both places so they stay consistent with each
  other.
- memory/{project}.json -- friction_history[].agent_name and
  market.bets[].agent_name, independent records, simple rewrite.
  decisions[].agent_name is skipped if absent (not populated by the
  current capture path). bet["id"] is left untouched even though it
  embeds the raw historical agent name -- only the display field matters
  to every read path, and rewriting ids risks breaking any external
  reference to a bet id for zero functional benefit.

Usage:
    python3 scripts/normalize_agent_identity.py              # dry run (default)
    python3 scripts/normalize_agent_identity.py --apply       # actually write
    python3 scripts/normalize_agent_identity.py --apply --project tropelex
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.agent_identity import normalize_agent_name  # noqa: E402
from core.memory.manager import MemoryManager  # noqa: E402


def _merge_skill_bucket(dst: dict, src: dict) -> None:
    """Merge one agent's skills_by_agent[name] category bucket into another."""
    for category, stats in src.items():
        if category not in dst:
            dst[category] = dict(stats)
            continue
        target = dst[category]
        target["attempts"] = target.get("attempts", 0) + stats.get("attempts", 0)
        target["successes"] = target.get("successes", 0) + stats.get("successes", 0)
        target["failures"] = target.get("failures", 0) + stats.get("failures", 0)
        target["score"] = target["successes"] / max(target["attempts"], 1)
        if stats.get("first_seen") and stats["first_seen"] < target.get("first_seen", stats["first_seen"]):
            target["first_seen"] = stats["first_seen"]
        if stats.get("last_seen") and stats["last_seen"] > target.get("last_seen", stats["last_seen"]):
            target["last_seen"] = stats["last_seen"]


def normalize_agent_skills(project: str, base_path: Path, apply: bool) -> list[str]:
    """Repair memory/agent_skills/{project}.json. Returns a list of change summary lines."""
    changes: list[str] = []
    skills_file = base_path / "memory" / "agent_skills" / f"{project}.json"
    if not skills_file.exists():
        return changes

    with open(skills_file) as f:
        data = json.load(f)

    skills_by_agent = data.get("skills_by_agent", {})
    merged: dict[str, dict] = {}
    for raw_name, bucket in skills_by_agent.items():
        canonical = normalize_agent_name(raw_name)
        if canonical not in merged:
            merged[canonical] = dict(bucket)
        else:
            _merge_skill_bucket(merged[canonical], bucket)
        if canonical != raw_name:
            changes.append(f"  skills_by_agent: '{raw_name}' -> '{canonical}'")

    sessions_changed = 0
    for session in data.get("sessions", []):
        old = session.get("agent", "unspecified")
        new = normalize_agent_name(old)
        if new != old:
            session["agent"] = new
            sessions_changed += 1
    if sessions_changed:
        changes.append(f"  sessions: {sessions_changed} agent field(s) normalized")

    if changes and apply:
        data["skills_by_agent"] = merged
        with open(skills_file, "w") as f:
            json.dump(data, f, indent=2)
    elif changes:
        # dry run: still show what the merged key set would look like
        changes.append(f"  (dry run, would merge into {len(merged)} agent(s): {sorted(merged)})")

    return changes


def normalize_replays(project: str, base_path: Path, apply: bool) -> list[str]:
    """Repair memory/replays/{project}/index.json and each session file."""
    changes: list[str] = []
    project_dir = base_path / "memory" / "replays" / project
    if not project_dir.exists():
        return changes

    index_file = project_dir / "index.json"
    if index_file.exists():
        with open(index_file) as f:
            index = json.load(f)
        index_changed = 0
        for entry in index:
            old = entry.get("agent", "unspecified")
            new = normalize_agent_name(old)
            if new != old:
                entry["agent"] = new
                index_changed += 1
        if index_changed:
            changes.append(f"  index.json: {index_changed} agent field(s) normalized")
            if apply:
                with open(index_file, "w") as f:
                    json.dump(index, f, indent=2)

    session_files_changed = 0
    for session_file in project_dir.glob("*.json"):
        if session_file.name == "index.json":
            continue
        with open(session_file) as f:
            record = json.load(f)
        old = record.get("agent", "unspecified")
        new = normalize_agent_name(old)
        if new != old:
            session_files_changed += 1
            if apply:
                record["agent"] = new
                with open(session_file, "w") as f:
                    json.dump(record, f, indent=2, default=str)
    if session_files_changed:
        changes.append(f"  session files: {session_files_changed} agent field(s) normalized")

    return changes


def normalize_project_memory(project: str, mm: MemoryManager, apply: bool) -> list[str]:
    """Repair memory/{project}.json: friction_history and market.bets."""
    changes: list[str] = []
    memory = mm.get_project_memory(project)

    friction_changed = 0
    for entry in memory.get("friction_history", []):
        old = entry.get("agent_name", "unspecified")
        new = normalize_agent_name(old)
        if new != old:
            entry["agent_name"] = new
            friction_changed += 1
    if friction_changed:
        changes.append(f"  friction_history: {friction_changed} agent_name field(s) normalized")

    bets_changed = 0
    for bet in memory.get("market", {}).get("bets", []):
        old = bet.get("agent_name", "unspecified")
        new = normalize_agent_name(old)
        if new != old:
            bet["agent_name"] = new
            bets_changed += 1
    if bets_changed:
        changes.append(f"  market.bets: {bets_changed} agent_name field(s) normalized")

    decisions_changed = 0
    for decision in memory.get("decisions", []):
        if "agent_name" not in decision:
            continue
        old = decision["agent_name"]
        new = normalize_agent_name(old)
        if new != old:
            decision["agent_name"] = new
            decisions_changed += 1
    if decisions_changed:
        changes.append(f"  decisions: {decisions_changed} agent_name field(s) normalized")

    if changes and apply:
        mm.save_project_memory(project, memory)

    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize historical agent_name values across stored memory")
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default is dry run)")
    parser.add_argument("--project", help="Limit to one project (default: all)")
    args = parser.parse_args()

    mm = MemoryManager(str(ROOT))

    # Agent skills and session replay files aren't necessarily 1:1 with
    # memory/{project}.json (a project can have skill/replay data without
    # ever having touched market/friction, or vice versa), so gather the
    # project name universe from all three sources.
    projects = set(mm.list_projects())
    projects |= {f.stem for f in (ROOT / "memory" / "agent_skills").glob("*.json")}
    if (ROOT / "memory" / "replays").exists():
        projects |= {d.name for d in (ROOT / "memory" / "replays").iterdir() if d.is_dir()}

    if args.project:
        projects &= {args.project}
        if not projects:
            print(f"No matching data found for project '{args.project}'")
            return

    mode = "APPLYING CHANGES" if args.apply else "DRY RUN (pass --apply to write)"
    print(f"=== Agent identity normalization: {mode} ===\n")

    any_changes = False
    for project in sorted(projects):
        project_changes: list[str] = []
        project_changes += normalize_agent_skills(project, ROOT, args.apply)
        project_changes += normalize_replays(project, ROOT, args.apply)
        project_changes += normalize_project_memory(project, mm, args.apply)

        if project_changes:
            any_changes = True
            print(f"[{project}]")
            for line in project_changes:
                print(line)
            print()

    if not any_changes:
        print("No inconsistent agent_name values found. Nothing to do.")
    elif not args.apply:
        print("Dry run complete. Re-run with --apply to write these changes.")
    else:
        print("Changes applied.")


if __name__ == "__main__":
    main()
