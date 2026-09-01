"""
LangGraph producer adapter (#110) -- a real LangGraph node that calls
Tropelex's actual handoff-generation code, proving a genuine HandoffPacket
survives being carried through LangGraph's own state-passing execution
model, not just Tropelex's own HTTP/MCP clients.

Producer direction only, per #110's own scoping ("minimal producer OR
consumer, not a full two-way integration"): this node produces a
Tropelex packet for a LangGraph graph to carry forward. It does not
consume or validate a LangGraph-native object on the way in -- that
would mean assuming a specific shape for LangGraph's own internal state
schema without a real external workflow driving it, weaker evidence for
a spike than calling Tropelex's own code from within a real graph.

Calls core.handoff.router.generate_handoff directly, in-process -- the
actual production router function (memory load, packet build, hashing,
audit logging), not a reimplementation of its logic and not routed
through HTTP. Same "call real production code directly" convention
core/driftbench/scenarios.py already uses for the same honesty reason:
this measures whether the real mechanism actually works inside a real
LangGraph node, not a simulation of it.

Requires the optional `adapters` extra (`pip install tropelex[adapters]`
or `uv sync --extra adapters`) -- langgraph is not a core dependency.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from core.handoff.router import HandoffRequest, generate_handoff


class TropelexHandoffState(TypedDict):
    """LangGraph state schema carrying a Tropelex handoff through a graph.

    `handoff_packet` starts None and is filled in by generate_handoff_node
    -- the real dict shape core.handoff.router.generate_handoff returns
    (role, active_decisions, must_survive_decision_ids, packet_hash, ...),
    not a LangGraph-specific reshaping of it.
    """
    project: str
    role: str
    token_budget: int
    agent_name: str
    handoff_packet: dict[str, Any] | None


async def generate_handoff_node(state: TropelexHandoffState) -> dict[str, Any]:
    """A real LangGraph node function: `graph.add_node("...", generate_handoff_node)`.

    Returns a partial state update (LangGraph merges it into the running
    state) rather than the full state, matching LangGraph's own node
    contract -- only `handoff_packet` changes here.
    """
    req = HandoffRequest(
        role=state["role"],
        token_budget=state.get("token_budget", 4000),
        agent_name=state.get("agent_name", "langgraph-adapter"),
    )
    packet = await generate_handoff(state["project"], req)
    return {"handoff_packet": packet}


def build_handoff_graph():
    """Compile the minimal 1-node graph the demo script and tests both
    use: START -> generate_handoff_node -> END. A separate function
    rather than inlined in the demo script so the test file exercises the
    exact same graph construction, not a hand-rolled duplicate of it.
    """
    graph = StateGraph(TropelexHandoffState)
    graph.add_node("generate_handoff", generate_handoff_node)
    graph.add_edge(START, "generate_handoff")
    graph.add_edge("generate_handoff", END)
    return graph.compile()
