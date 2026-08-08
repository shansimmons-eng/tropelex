"""
Concrete pre_push checks: the two the trigger registry was proposed for
("does every endpoint have a test", "is there error handling before we push").

Both are heuristics over source text, not real coverage/AST analysis — they
catch the common case (a route with literally zero mentions of its path in
any test file; a route body with no try/except) and will have false
negatives on cleverly-indirected code. Treat findings as a prompt to look,
not as ground truth.

Registering these against PRE_PUSH has a real side effect the moment this
module is imported (decorators run at import time), so importing it is the
opt-in step — nothing here runs until something calls
`registry.run("pre_push", context)`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.triggers.registry import CheckResult, PRE_PUSH, registry

_ROUTE_DECORATOR = re.compile(
    r'^@\w+_router\.(get|post|delete|patch|put)\(\s*["\']([^"\']+)["\']', re.MULTILINE
)
# A function has a body-level try/except if "try:" appears before the next
# top-level "async def"/"def" at the same indent. Cheap approximation:
# look for "try:" anywhere between this decorator and the next one.
_TRY_BLOCK = re.compile(r"\btry:\s*\n")


def _iter_router_files(repo_path: Path) -> list[Path]:
    return sorted((repo_path / "core").glob("*/router.py"))


def _iter_routes(text: str) -> list[tuple[str, int]]:
    """Return [(path, start_offset), ...] for each route decorator in a router file."""
    return [(m.group(2), m.end()) for m in _ROUTE_DECORATOR.finditer(text)]


@registry.check(PRE_PUSH)
def check_every_endpoint_has_a_test(context: dict[str, Any]) -> CheckResult:
    repo_path = Path(context.get("repo_path", "."))
    tests_dir = repo_path / "tests"
    test_text = ""
    if tests_dir.is_dir():
        test_text = "\n".join(
            p.read_text(errors="ignore") for p in tests_dir.glob("test_*.py")
        )

    untested = []
    for router_file in _iter_router_files(repo_path):
        text = router_file.read_text(errors="ignore")
        for path, _ in _iter_routes(text):
            # Strip path params for a loose substring match — tests usually
            # hit a concrete path like "/demo/market/clear", not the
            # "{project}" template, so match on the static segments only.
            needle = re.sub(r"\{[^}]+\}", "", path).strip("/")
            if needle and needle not in test_text:
                untested.append(f"{router_file.relative_to(repo_path)}: {path}")

    if untested:
        return CheckResult(
            name="check_every_endpoint_has_a_test",
            event=PRE_PUSH,
            passed=False,
            detail=f"{len(untested)} route(s) with no apparent test reference: "
            + "; ".join(untested[:10])
            + (" ..." if len(untested) > 10 else ""),
            severity="warn",
        )
    return CheckResult(
        name="check_every_endpoint_has_a_test",
        event=PRE_PUSH,
        passed=True,
        detail="every route path has at least one match in tests/",
    )


@registry.check(PRE_PUSH)
def check_error_handling_present(context: dict[str, Any]) -> CheckResult:
    repo_path = Path(context.get("repo_path", "."))

    unguarded = []
    for router_file in _iter_router_files(repo_path):
        text = router_file.read_text(errors="ignore")
        decorators = list(_ROUTE_DECORATOR.finditer(text))
        for i, m in enumerate(decorators):
            body_start = m.end()
            body_end = decorators[i + 1].start() if i + 1 < len(decorators) else len(text)
            body = text[body_start:body_end]
            if not _TRY_BLOCK.search(body):
                unguarded.append(f"{router_file.relative_to(repo_path)}: {m.group(2)}")

    if unguarded:
        return CheckResult(
            name="check_error_handling_present",
            event=PRE_PUSH,
            passed=False,
            detail=f"{len(unguarded)} route(s) with no try/except in their body: "
            + "; ".join(unguarded[:10])
            + (" ..." if len(unguarded) > 10 else ""),
            severity="warn",
        )
    return CheckResult(
        name="check_error_handling_present",
        event=PRE_PUSH,
        passed=True,
        detail="every route body contains a try/except",
    )
