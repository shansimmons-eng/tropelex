"""
Tropelex Git Sync CLI
On-demand git history analysis and memory sync.

Usage:
    python -m scripts.git_sync <repo_path> <project_name> [--deep] [--summary-only]
    python -m scripts.git_sync ~/myproject myproject --deep
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure Tropelex root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_summary(summary: dict) -> None:
    """Pretty-print a repo summary."""
    print(f"\n{'='*50}")
    print(f"  Repository Summary")
    print(f"{'='*50}")
    print(f"  Branch: {summary.get('branch', 'unknown')}")
    print(f"  Stack:  {', '.join(summary.get('stack', []))}")

    commits = summary.get("commits", [])
    if commits:
        print(f"\n  Recent commits ({len(commits)}):")
        for c in commits:
            print(f"    {c['hash']}  {c['date']}  {c['subject'][:60]}")

    decisions = summary.get("decisions", [])
    if decisions:
        print(f"\n  Decisions found: {len(decisions)}")
        for d in decisions[:5]:
            print(f"    [{d.get('date', '')}] {d.get('decision', '')[:70]}")

    # Deep analysis fields
    deep = summary.get("deep_decisions", [])
    if deep:
        print(f"\n  Deep analysis: {len(deep)} commits analyzed")
        cat_freq = summary.get("category_frequency", {})
        if cat_freq:
            print(f"  Work categories: {dict(sorted(cat_freq.items(), key=lambda x: -x[1]))}")

        reverts = summary.get("reverts", [])
        if reverts:
            print(f"  Reverts detected: {len(reverts)}")
            for r in reverts:
                print(f"    {r['hash']}  {r['subject'][:60]}")

    print()


def print_sync_result(result: dict) -> None:
    """Pretty-print sync result."""
    print(f"\n{'='*50}")
    print(f"  Git Sync Result")
    print(f"{'='*50}")
    print(f"  Synced:     {result.get('synced', False)}")
    print(f"  Branch:     {result.get('branch', 'unknown')}")
    print(f"  Stack:      {', '.join(result.get('stack', []))}")

    if "new_decisions" in result:
        print(f"  New decisions: {result['new_decisions']}")
        if result.get("shallow_decisions"):
            print(f"    Shallow: {result['shallow_decisions']}")
        if result.get("deep_decisions"):
            print(f"    Deep:    {result['deep_decisions']}")

    stack_changes = result.get("stack_changes", {})
    if stack_changes.get("changed"):
        print(f"\n  Tech stack changes:")
        if stack_changes.get("added"):
            print(f"    + {', '.join(stack_changes['added'])}")
        if stack_changes.get("removed"):
            print(f"    - {', '.join(stack_changes['removed'])}")

    categories = result.get("work_categories", {})
    if categories:
        print(f"\n  Work categories: {dict(sorted(categories.items(), key=lambda x: -x[1]))}")

    if result.get("error"):
        print(f"  Error: {result['error']}")

    print()


async def run_sync(repo_path: str, project_name: str, deep: bool, summary_only: bool):
    from core.git_integration import (
        get_deep_repo_summary,
        get_repo_summary,
        is_git_repo,
    )
    from core.memory.manager import MemoryManager

    if not is_git_repo(repo_path):
        print(f"Error: {repo_path} is not a git repository")
        return 1

    mm = MemoryManager()

    if summary_only:
        if deep:
            summary = get_deep_repo_summary(repo_path)
        else:
            summary = get_repo_summary(repo_path)
        print_summary(summary)
        return 0

    from core.git_integration import sync_repo_to_memory

    result = await sync_repo_to_memory(repo_path, project_name, mm)
    print_sync_result(result)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Tropelex Git Sync CLI")
    parser.add_argument("repo_path", help="Path to the git repository")
    parser.add_argument("project_name", help="Tropelex project name")
    parser.add_argument("--deep", action="store_true", help="Deep analysis (parse diffs, detect rationale)")
    parser.add_argument("--summary-only", action="store_true", help="Show summary without syncing to memory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    asyncio.run(run_sync(args.repo_path, args.project_name, args.deep, args.summary_only))


if __name__ == "__main__":
    main()
