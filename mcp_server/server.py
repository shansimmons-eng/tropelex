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
async def capture_decision(
    project: str,
    decision: str,
    context: str = "",
    risk_level: str = "low",
    reversibility: bool = True,
    affected_systems: list[str] = None,
    safety_category: str | None = None,
    requires_review: bool = False,
    alignment_considerations: str = "",
    goal_id: str | None = None,
) -> dict[str, Any]:
    """Record a new decision in a project's memory. safety_category is required.

    Args:
        project: Project name (created automatically if it doesn't exist).
        decision: What was decided, in one sentence (e.g. "Use Postgres for the primary database").
        context: Why it was decided — optional but recommended for future recall.
        risk_level: Risk level: low, medium, high, or critical. Default: low.
        reversibility: Whether this decision can be easily reversed. Default: True.
        affected_systems: List of systems/components affected (e.g., ["memory", "api"]).
        safety_category: Safety category: general, adversarial, robustness, monitoring, governance, alignment.
            Not optional in practice — omitting it gets the call rejected with a
            suggested category attached, which you should read and either accept
            (retry with it) or override with a better-fitting one. It's not
            defaulted to "general" for you; that was a real bug where every
            decision anyone forgot to classify was recorded as generically
            classified, silently.
        requires_review: Whether this decision requires human review. Default: False.
        alignment_considerations: Notes on alignment/safety considerations.
        goal_id: Optional id of a Goal (see propose_goal) this decision serves.
            Rejected with a 404 if it doesn't exist in this project.
    """
    safety_metadata = {
        "risk_level": risk_level,
        "reversibility": reversibility,
        "affected_systems": affected_systems or [],
        "rationale_quality": 0.5,
        "alignment_considerations": alignment_considerations,
        "requires_review": requires_review,
        "safety_category": safety_category,
    }

    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/decisions",
        json={
            "decision": decision,
            "context": context,
            "safety_metadata": safety_metadata,
            "goal_id": goal_id,
        },
    )


@mcp.tool()
async def propose_goal(
    project: str,
    text: str,
    priority: str = "medium",
    category: str | None = None,
) -> dict[str, Any]:
    """Propose a new goal for a project — the prospective counterpart to
    capture_decision. Where a decision records what was decided, a goal
    records what's being aimed at, before decisions accumulate under it.

    Args:
        project: Project name (created automatically if it doesn't exist).
        text: The goal, stated as a target (e.g. "Reduce login brute-force risk").
        priority: low, medium, high, or critical. Default: medium.
        category: Either a safety category (general, adversarial, robustness,
            monitoring, governance, alignment) for goals with a safety
            dimension, or "nonsafety:<label>" (e.g. "nonsafety:performance")
            for goals that don't have one. Omit if unclassified.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/goals",
        json={"text": text, "priority": priority, "category": category},
    )


@mcp.tool()
async def end_session(project: str, summary: str, agent: str = "unspecified") -> dict[str, Any]:
    """Record the current session as a snapshot in a project's session history.

    Call this at the end of a work session so Session Replay and Time Travel
    have something to reconstruct later.

    Args:
        project: Project name.
        summary: One-line summary of what happened this session.
        agent: Your own name (e.g. "Claude", "Cursor", "Gemini") — attributes
            this session to you specifically, so per-agent skill and persona
            tracking has real data instead of lumping every agent together.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/sessions/record",
        json={"summary": summary, "session_type": "manual", "agent_name": agent},
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
async def friction_scan(project: str, transcript: str, agent: str = "unspecified") -> dict[str, Any]:
    """Scan a conversation transcript for friction signals — rephrasing,
    escalation, retries — that indicate implicit user correction or frustration.

    Args:
        project: Project name.
        transcript: Raw conversation text to scan.
        agent: Your own name (e.g. "Claude", "Cursor", "Gemini") — attributes
            this scan to you specifically for per-agent friction tracking.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/friction/scan",
        json={"transcript": transcript, "agent_name": agent},
    )


@mcp.tool()
async def record_skill_outcome(
    project: str,
    session_type: str,
    categories: list[str],
    outcome: str = "success",
    details: str = "",
    agent: str = "unspecified",
) -> dict[str, Any]:
    """Record how well a task went, to build up per-agent skill and persona data.

    Call this after finishing a non-trivial task so Agent Skill Proficiency
    and Personas reflect what you actually did, instead of requiring a human
    to type it into the web UI by hand.

    Args:
        project: Project name.
        session_type: Short label for the kind of work (e.g. "bugfix", "feature", "refactor").
        categories: Skill categories this task touched (e.g. ["ui", "backend"]).
        outcome: How it went: success, partial, or failure. Default: success.
        details: Optional one-line note on what happened.
        agent: Your own name (e.g. "Claude", "Cursor", "Gemini") — attributes
            this outcome to you specifically.
    """
    return await _request(
        "POST", f"/api/memory/{quote(project, safe='')}/agent-skills/record",
        json={
            "session_type": session_type,
            "categories": categories,
            "outcome": outcome,
            "details": details,
            "agent_name": agent,
        },
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
