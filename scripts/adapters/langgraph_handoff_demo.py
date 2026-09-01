#!/usr/bin/env python3
"""
LangGraph producer spike demo (#110) -- the literal artifact proving
core/handoff/adapters/langgraph_adapter.py runs, not just imports cleanly.

Builds a real StateGraph, compiles it, invokes it against a synthetic
in-memory project (no real project file touched -- same _load_memory/
save_project_memory patch tests/test_langgraph_adapter.py uses), and
prints the resulting HandoffPacket: a real Tropelex artifact, generated
by real Tropelex code, carried through a real LangGraph execution.

Requires the `adapters` extra:
    uv sync --extra adapters
    uv run python3 scripts/adapters/langgraph_handoff_demo.py
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    import langgraph  # noqa: F401
except ImportError:
    print(
        "langgraph isn't installed. Install the optional 'adapters' extra first:\n"
        "  uv sync --extra adapters\n"
        "  uv run python3 scripts/adapters/langgraph_handoff_demo.py",
        file=sys.stderr,
    )
    sys.exit(1)

from core.handoff.adapters.langgraph_adapter import TropelexHandoffState, build_handoff_graph

_DEMO_MEMORY = {
    "decisions": [
        {
            "decision": "Never bypass authentication for admin-level access",
            "context": "Security baseline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "categories": ["security"],
            "safety_metadata": {"risk_level": "critical"},
            "id": "db-demo-1",
        },
        {
            "decision": "Use FastAPI for REST endpoints",
            "context": "Backend needs async HTTP",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "categories": ["backend"],
        },
    ],
    "session_history": [],
    "audit_log": [],
}


async def main() -> None:
    app = build_handoff_graph()
    initial: TropelexHandoffState = {
        "project": "langgraph-demo", "role": "CoderAgent",
        "token_budget": 4000, "agent_name": "langgraph-demo-script",
        "handoff_packet": None,
    }

    memory_copy = copy.deepcopy(_DEMO_MEMORY)
    with patch("core.handoff.router._load_memory", return_value=memory_copy), \
         patch("core.handoff.router._mm.save_project_memory"):
        result = await app.ainvoke(initial)

    packet = result["handoff_packet"]
    print("Real LangGraph run complete. Resulting HandoffPacket:\n")
    print(json.dumps(packet, indent=2, default=str))
    print(f"\nmust_survive_decision_ids carried through: {packet['must_survive_decision_ids']}")
    print(f"packet_hash: {packet['packet_hash']}")


if __name__ == "__main__":
    asyncio.run(main())
