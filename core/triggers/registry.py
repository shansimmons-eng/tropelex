"""
Trigger registry — event -> check(s) -> logged result.

Sketch/prototype. Not wired into server.py or any git hook yet.

The pattern this formalizes already exists piecemeal across the codebase
(git_integration.sync_repo_to_memory runs after a sync event, friction/router
persists a scan's result to friction_history, capture_decision writes on
session events). This module gives that pattern one shape: register a check
function against a named event, run all checks for that event with a shared
context dict, get back typed results, persist them.

Usage:
    from core.triggers.registry import registry, CheckResult

    @registry.check("pre_push")
    def my_check(context: dict) -> CheckResult:
        ...
        return CheckResult(name="my_check", event="pre_push", passed=True, detail="ok")

    results = registry.run("pre_push", context={"repo_path": "."})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# Events this registry knows how to fire. Not an enforced enum on purpose —
# new event names can be registered against without touching this module —
# but these are the ones with checks defined in checks.py today.
PRE_PUSH = "pre_push"
POST_COMMIT = "post_commit"
SESSION_END = "session_end"
PR_OPENED = "pr_opened"


@dataclass
class CheckResult:
    """Outcome of a single check run against a single event firing."""

    name: str
    event: str
    passed: bool
    detail: str
    severity: str = "warn"  # "warn" (informational) or "block" (should stop the action)


CheckFn = Callable[[dict[str, Any]], CheckResult]


@dataclass
class TriggerRegistry:
    """Maps event names to the check functions registered against them."""

    _checks: dict[str, list[CheckFn]] = field(default_factory=dict)

    def check(self, event: str) -> Callable[[CheckFn], CheckFn]:
        """Decorator: register a check function against an event."""

        def decorator(fn: CheckFn) -> CheckFn:
            self._checks.setdefault(event, []).append(fn)
            return fn

        return decorator

    def run(self, event: str, context: dict[str, Any]) -> list[CheckResult]:
        """Run every check registered for `event`, in registration order.

        A check raising is treated as a failed "block" result rather than
        propagating — one broken check shouldn't take down the others or
        the caller.
        """
        results = []
        for fn in self._checks.get(event, []):
            try:
                results.append(fn(context))
            except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
                results.append(
                    CheckResult(
                        name=getattr(fn, "__name__", "unknown_check"),
                        event=event,
                        passed=False,
                        detail=f"check raised: {exc}",
                        severity="block",
                    )
                )
        return results

    def registered_events(self) -> list[str]:
        return list(self._checks.keys())


registry = TriggerRegistry()


def record_trigger_run(
    project: str,
    memory_manager: Any,
    event: str,
    results: list[CheckResult],
) -> None:
    """Persist a trigger firing to project memory as `trigger_runs`.

    Mirrors the friction_history pattern in core/friction/router.py: append,
    then cap to the most recent 50 so memory doesn't grow unbounded.
    """
    memory = memory_manager.get_project_memory(project)
    runs = memory.setdefault("trigger_runs", [])
    runs.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "detail": r.detail,
                    "severity": r.severity,
                }
                for r in results
            ],
            "all_passed": all(r.passed for r in results),
        }
    )
    memory["trigger_runs"] = runs[-50:]  # bounded — most recent 50 firings
    memory_manager.save_project_memory(project, memory)
