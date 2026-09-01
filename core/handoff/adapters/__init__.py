"""
Cross-framework adapters (wishlist #110) -- spikes proving the Handoff
Packet protocol (docs/protocols/handoff-packet-spec.md) can round-trip
through an external multi-agent framework's own execution model, not
just Tropelex's own MCP/HTTP clients.

Deliberately spikes, not a framework-compatibility layer: one framework
(LangGraph), one direction (producer -- a real LangGraph node calls
Tropelex's own handoff-generation code and carries the result in
LangGraph's state), not a general adapter for every framework in both
directions. See core/handoff/adapters/langgraph_adapter.py's own
docstring and docs/far-ai-summary.md's Deliverable #2 for the honest
scope of what this does and doesn't demonstrate.
"""
