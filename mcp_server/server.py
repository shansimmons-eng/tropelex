"""Tropelex MCP server — exposes Tropelex's decision-memory system as MCP
tools, so any MCP-capable agent (Claude Code, Cursor, etc.) can read and
write project memory directly, the same way the OpenCode plugin, VSCode
extension, and Emacs package already do over Tropelex's REST API.

Runs in its own venv (mcp_server/.venv) — kept separate from Tropelex's own
system-Python server process so neither's dependencies leak into the other.

Requires the Tropelex server to be running (default http://localhost:8766).
Configure a different URL with the TROPELEX_URL environment variable.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

TROPELEX_URL = os.environ.get("TROPELEX_URL", "http://localhost:8766").rstrip("/")

mcp = FastMCP("tropelex")


async def _request(method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the Tropelex REST API and return the parsed JSON body.

    Raises a clear, agent-readable error (rather than a raw exception) if
    Tropelex isn't reachable or the API returns an error status.
    """
    url = f"{TROPELEX_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method, url, json=json, headers={"X-Tropelex-Client": "mcp"}
            )
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Could not reach the Tropelex server at {TROPELEX_URL}. "
            f"Is it running? (python3 -m core.tropebook.web.server). Detail: {exc}"
        )
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Tropelex API error {resp.status_code} on {path}: {detail}")
    return resp.json()


@mcp.tool()
async def list_projects() -> dict[str, Any]:
    """List all Tropelex projects and basic stats for each."""
    return await _request("GET", "/api/memory")


@mcp.tool()
async def get_project_memory(project: str) -> dict[str, Any]:
    """Get a project's full memory: decisions, sessions, preferences, patterns.

    Call this first when starting work on a project to load its accumulated
    context instead of starting from scratch.
    """
    return await _request("GET", f"/api/memory/{quote(project, safe='')}")


@mcp.tool()
async def capture_decision(project: str, decision: str, context: str = "") -> dict[str, Any]:
    """Record a new decision in a project's memory.

    Args:
        project: Project name (created automatically if it doesn't exist).
        decision: What was decided, in one sentence (e.g. "Use Postgres for the primary database").
        context: Why it was decided — optional but recommended for future recall.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/decisions",
        json={"decision": decision, "context": context},
    )


@mcp.tool()
async def end_session(project: str, summary: str) -> dict[str, Any]:
    """Record the current session as a snapshot in a project's session history.

    Call this at the end of a work session so Session Replay and Time Travel
    have something to reconstruct later.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/sessions/record",
        json={"summary": summary, "session_type": "manual"},
    )


@mcp.tool()
async def get_context_bundle(project: str, task: str, token_budget: int = 4000) -> dict[str, Any]:
    """Assemble a budget-aware bundle of the most relevant past decisions for a task.

    Use this before starting a task to pull in exactly the prior context that
    matters, instead of dumping the entire project memory into the prompt.

    Args:
        project: Project name.
        task: Natural-language description of the task about to be done.
        token_budget: Maximum token budget for the assembled bundle (500-50000).
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/prefetch",
        json={"task": task, "token_budget": token_budget},
    )


@mcp.tool()
async def check_contradictions(project: str) -> dict[str, Any]:
    """Scan a project's decisions for unresolved contradictions.

    Returns conflicting decision pairs (e.g. "use MySQL" vs "use Postgres"
    both still active) with severity and a resolution suggestion.
    """
    return await _request("GET", f"/api/memory/{quote(project, safe='')}/contradictions")


@mcp.tool()
async def check_diff_for_conflicts(project: str, diff: str) -> dict[str, Any]:
    """Pre-write guard: check a proposed unified diff against active decisions
    before committing it.

    Call this before finalizing a change to catch cases where the diff
    silently contradicts a decision nobody has revisited.

    Args:
        project: Project name.
        diff: Unified diff text of the proposed change.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/ghost-check",
        json={"diff": diff},
    )


@mcp.tool()
async def friction_scan(project: str, transcript: str) -> dict[str, Any]:
    """Scan a conversation transcript for friction signals — rephrasing,
    escalation, retries — that indicate implicit user correction or frustration.

    Args:
        project: Project name.
        transcript: Raw conversation text to scan.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/friction/scan",
        json={"transcript": transcript},
    )


@mcp.tool()
async def get_handoff_packet(project: str, role: str, token_budget: int = 4000) -> dict[str, Any]:
    """Generate a role-aware context bundle for handing work off to another agent.

    Args:
        project: Project name.
        role: The receiving agent's role (e.g. "reviewer", "implementer", "tester").
        token_budget: Maximum token budget for the packet.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/handoff",
        json={"role": role, "token_budget": token_budget},
    )


@mcp.tool()
async def explain_why(project: str, question: str) -> dict[str, Any]:
    """Ask a natural-language 'why do we...?' question and get a causal-chain
    answer synthesized from the decision graph and project memory.

    Args:
        project: Project name.
        question: e.g. "why do we use Postgres instead of MySQL?"
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/explain",
        json={"question": question},
    )


if __name__ == "__main__":
    mcp.run()
