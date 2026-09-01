"""
Tests for the LangGraph producer spike (#110, core/handoff/adapters/
langgraph_adapter.py).

Requires the optional `adapters` extra (langgraph) -- if it isn't
installed, these tests skip cleanly rather than erroring or faking a
pass, the same graceful-degradation posture #106 uses for "no LLM
backend available." Run via a venv with the extra installed
(`uv sync --extra adapters --extra dev && uv run pytest
tests/test_langgraph_adapter.py`) to actually exercise this file instead
of skipping it.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

langgraph = pytest.importorskip("langgraph")

from core.handoff.adapters.langgraph_adapter import (  # noqa: E402
    TropelexHandoffState,
    build_handoff_graph,
    generate_handoff_node,
)

SAMPLE_MEMORY = {
    "decisions": [
        {
            "decision": "Use FastAPI for REST endpoints",
            "context": "Backend needs async HTTP",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "categories": ["backend"],
        },
        {
            "decision": "Never bypass authentication for admin-level access",
            "context": "Security baseline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "categories": ["security"],
            "safety_metadata": {"risk_level": "critical"},
            "id": "db-langgraph-1",
        },
    ],
    "session_history": [],
    "audit_log": [],
}


@contextmanager
def _mock_load(memory):
    """Same patch shape as tests/test_handoff_packets.py's TestHandoffEndpoint
    ._mock_load: patches _load_memory AND save_project_memory so
    generate_handoff's real audit-logging write never touches a real
    on-disk project file, and deep-copies so mutation (append_audit_event)
    doesn't leak into other tests sharing SAMPLE_MEMORY."""
    memory_copy = copy.deepcopy(memory)
    with patch("core.handoff.router._load_memory", return_value=memory_copy), \
         patch("core.handoff.router._mm.save_project_memory") as mock_save:
        yield mock_save, memory_copy


class TestGenerateHandoffNode:
    async def test_node_returns_real_packet_dict(self):
        state: TropelexHandoffState = {
            "project": "langgraph-spike", "role": "CoderAgent",
            "token_budget": 4000, "agent_name": "test", "handoff_packet": None,
        }
        with _mock_load(SAMPLE_MEMORY):
            update = await generate_handoff_node(state)

        packet = update["handoff_packet"]
        assert packet["role"] == "CoderAgent"
        assert "packet_hash" in packet and packet["packet_hash"]
        assert packet["must_survive_decision_ids"] == ["db-langgraph-1"]

    async def test_node_only_updates_handoff_packet_key(self):
        state: TropelexHandoffState = {
            "project": "langgraph-spike", "role": "CoderAgent",
            "token_budget": 4000, "agent_name": "test", "handoff_packet": None,
        }
        with _mock_load(SAMPLE_MEMORY):
            update = await generate_handoff_node(state)

        assert set(update.keys()) == {"handoff_packet"}


class TestHandoffGraph:
    async def test_real_graph_invoke_produces_real_packet(self):
        """The actual spike: build a real StateGraph, compile it, invoke
        it -- confirms the packet survives LangGraph's own execution
        model and state-merging, not just a bare function call."""
        app = build_handoff_graph()
        initial: TropelexHandoffState = {
            "project": "langgraph-spike", "role": "ReviewerAgent",
            "token_budget": 4000, "agent_name": "langgraph-adapter-test",
            "handoff_packet": None,
        }

        with _mock_load(SAMPLE_MEMORY):
            result = await app.ainvoke(initial)

        assert result["project"] == "langgraph-spike"  # unrelated state keys survive
        packet = result["handoff_packet"]
        assert packet is not None
        assert packet["role"] == "ReviewerAgent"
        assert "packet_hash" in packet
        assert packet["must_survive_decision_ids"] == ["db-langgraph-1"]

    async def test_graph_logs_a_real_audit_event(self):
        """generate_handoff's own handoff_created audit write (#59) fires
        exactly the same way inside the graph as it does via HTTP --
        confirms this isn't a code path that only works when called
        directly, bypassing production side effects."""
        app = build_handoff_graph()
        initial: TropelexHandoffState = {
            "project": "langgraph-spike", "role": "CoderAgent",
            "token_budget": 4000, "agent_name": "test", "handoff_packet": None,
        }

        with _mock_load(SAMPLE_MEMORY) as (mock_save, memory_copy):
            await app.ainvoke(initial)

        assert any(e.get("event_type") == "handoff_created" for e in memory_copy["audit_log"])
        mock_save.assert_called_once()
