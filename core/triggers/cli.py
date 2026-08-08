"""
CLI entrypoint for firing a trigger event from the command line, e.g. from
a git hook: `python -m core.triggers.cli pre_push`.

Not installed as a git hook by this sketch — see hooks/pre-push.sh for a
reference script the user can copy into .git/hooks/pre-push themselves.
"""

from __future__ import annotations

import sys

from core.triggers import checks  # noqa: F401 - registers pre_push checks on import
from core.triggers.registry import registry


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: python -m core.triggers.cli <event>", file=sys.stderr)
        print(f"known events: {', '.join(registry.registered_events())}", file=sys.stderr)
        return 2

    event = argv[1]
    results = registry.run(event, context={"repo_path": "."})

    if not results:
        print(f"no checks registered for event '{event}'")
        return 0

    blocked = False
    for r in results:
        status = "PASS" if r.passed else ("BLOCK" if r.severity == "block" else "WARN")
        print(f"[{status}] {r.name}: {r.detail}")
        if not r.passed and r.severity == "block":
            blocked = True

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
