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

import json as _json
import os
import time
from collections import Counter
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

# This process runs in its own venv/subprocess, separate from the Tropelex
# server it talks to over HTTP -- it doesn't inherit the server's shell
# environment, so the instance secret (P1) has to be read the same way
# core/tropebook/web/server.py itself reads it: from the repo-root .env.
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and "=" in _line and not _line.startswith("#"):
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip().strip('"').strip("'"))

TROPELEX_URL = os.environ.get("TROPELEX_URL", "http://localhost:8766").rstrip("/")
TROPEL_EX_SECRET = os.environ.get("TROPEL_EX_SECRET", "")

mcp = FastMCP("tropelex")

# ── Session-shape capture (wishlist.md #45) ─────────────────────────────────
# One MCP server process is already one real agent session -- Claude Code
# (and other MCP-capable clients) spawn a fresh subprocess per session, so
# this module-level state needs no explicit session-id threaded through
# every tool call. Reset on end_session flush; process exit is the implicit
# fallback boundary for sessions that never call it. Same "in-memory,
# process-scoped" convention core/telemetry.py's own log already uses.
_call_count = 0
_error_count = 0
_tool_names: Counter[str] = Counter()
_durations_ms: list[float] = []  # every call, including errors/timeouts
_output_bytes: list[int] = []  # success calls only
_first_call_monotonic: float | None = None
_last_call_monotonic: float | None = None


def _record_tool_call(tool_name: str, duration_ms: float, error: bool, output_bytes: int) -> None:
    global _call_count, _error_count, _first_call_monotonic, _last_call_monotonic
    now = time.monotonic()
    _call_count += 1
    if error:
        _error_count += 1
    _tool_names[tool_name] += 1
    _durations_ms.append(duration_ms)
    if not error:
        _output_bytes.append(output_bytes)
    if _first_call_monotonic is None:
        _first_call_monotonic = now
    _last_call_monotonic = now


def _build_session_shape() -> dict[str, Any] | None:
    """Snapshot the current session's shape, or None if nothing happened
    this session -- an all-zero record would poison the baseline rather
    than honestly representing "no data"."""
    if _call_count == 0:
        return None
    total_duration_s = 0.0
    if _first_call_monotonic is not None and _last_call_monotonic is not None and _call_count >= 2:
        total_duration_s = _last_call_monotonic - _first_call_monotonic
    return {
        "tool_call_count": _call_count,
        "unique_tools_used": len(_tool_names),
        "avg_call_duration_ms": sum(_durations_ms) / len(_durations_ms) if _durations_ms else 0.0,
        "max_call_duration_ms": max(_durations_ms) if _durations_ms else 0.0,
        "error_count": _error_count,
        "avg_output_bytes": sum(_output_bytes) / len(_output_bytes) if _output_bytes else 0.0,
        "total_duration_s": total_duration_s,
    }


def _reset_session_shape() -> None:
    global _call_count, _error_count, _first_call_monotonic, _last_call_monotonic
    _call_count = 0
    _error_count = 0
    _tool_names.clear()
    _durations_ms.clear()
    _output_bytes.clear()
    _first_call_monotonic = None
    _last_call_monotonic = None


async def _request(
    tool_name: str, method: str, path: str, json: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Call the Tropelex REST API and return the parsed JSON body.

    Raises a clear, agent-readable error (rather than a raw exception) if
    Tropelex isn't reachable or the API returns an error status.

    tool_name is threaded explicitly by every caller (not inferred via
    inspect.stack()) so session-shape capture has an unambiguous label —
    explicit over clever. Capture happens in `finally` so every exit path
    (success, connect error, 4xx/5xx, timeout) is recorded; a call that
    dies after the full timeout *is* the "hang duration" signal this
    feature exists to catch, so it isn't excluded.

    timeout defaults to 30s (fine for every existing tool) but deep
    research calls genuinely run 1-3+ minutes (hybrid mode fans out to
    last30days concurrently with web-researcher-mcp, then merges) --
    those callers pass a longer value explicitly rather than this default
    silently cutting them off mid-run.
    """
    start = time.monotonic()
    error = False
    output_bytes = 0
    try:
        url = f"{TROPELEX_URL}{path}"
        headers = {"X-Tropelex-Client": "mcp"}
        if TROPEL_EX_SECRET:
            headers["Authorization"] = f"Bearer {TROPEL_EX_SECRET}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url, json=json, headers=headers)
        except httpx.ConnectError as exc:
            error = True
            raise RuntimeError(
                f"Could not reach the Tropelex server at {TROPELEX_URL}. "
                f"Is it running? (python3 -m core.tropebook.web.server). Detail: {exc}"
            )
        if resp.status_code >= 400:
            error = True
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RuntimeError(f"Tropelex API error {resp.status_code} on {path}: {detail}")
        result = resp.json()
        try:
            output_bytes = len(_json.dumps(result).encode())
        except (TypeError, ValueError):
            # Byte-sizing is a metrics nicety, not part of the actual tool
            # call -- never let it mask the real result on the vanishingly
            # unlikely chance the response isn't cleanly re-serializable.
            output_bytes = 0
        return result
    except Exception:
        error = True
        raise
    finally:
        # Capture must never break the tool call it's instrumenting --
        # a bug in this bookkeeping is not worth taking down every MCP
        # call in production over.
        try:
            _record_tool_call(tool_name, (time.monotonic() - start) * 1000, error, output_bytes)
        except Exception:
            pass


@mcp.tool()
async def list_projects() -> dict[str, Any]:
    """List all Tropelex projects and basic stats for each."""
    return await _request("list_projects", "GET", "/api/memory")


@mcp.tool()
async def get_project_memory(project: str) -> dict[str, Any]:
    """Get a project's full memory: decisions, sessions, preferences, patterns.

    Call this first when starting work on a project to load its accumulated
    context instead of starting from scratch.
    """
    return await _request("get_project_memory", "GET", f"/api/memory/{quote(project, safe='')}")


@mcp.tool()
async def capture_decision(
    project: str,
    decision: str,
    context: str = "",
    risk_level: str | None = None,
    reversibility: bool | None = None,
    affected_systems: list[str] | None = None,
    safety_category: str | None = None,
    requires_review: bool | None = None,
    alignment_considerations: str = "",
    goal_id: str | None = None,
) -> dict[str, Any]:
    """Record a new decision in a project's memory. safety_category is required.

    Args:
        project: Project name (created automatically if it doesn't exist).
        decision: What was decided, in one sentence (e.g. "Use Postgres for the primary database").
        context: Why it was decided — optional but recommended for future recall.
        risk_level: Risk level: low, medium, high, or critical. Left unset, the
            server auto-classifies it from the decision text.
        reversibility: Whether this decision can be easily reversed. Left unset,
            the server auto-classifies it — UNLESS the resolved risk_level lands
            on high/critical, in which case this becomes required (#54): the
            call gets rejected with the auto-classifier's guess attached, which
            you should read and either accept (retry with it) or override.
        affected_systems: List of systems/components affected (e.g., ["memory", "api"]).
            Same high/critical-risk requirement as reversibility.
        safety_category: Safety category: general, adversarial, robustness, monitoring, governance, alignment.
            Not optional in practice — omitting it gets the call rejected with a
            suggested category attached, which you should read and either accept
            (retry with it) or override with a better-fitting one. It's not
            defaulted to "general" for you; that was a real bug where every
            decision anyone forgot to classify was recorded as generically
            classified, silently.
        requires_review: Whether this decision requires human review. Same
            high/critical-risk requirement as reversibility.
        alignment_considerations: Notes on alignment/safety considerations.
        goal_id: Optional id of a Goal (see propose_goal) this decision serves.
            Rejected with a 404 if it doesn't exist in this project.
    """
    # Only include fields the caller actually set. Filling in bool/list
    # defaults here (reversibility=True, affected_systems=[], etc.) would
    # make every field look "explicitly provided" to the server's #54 gate
    # even when the caller never thought about it — the exact silent-
    # default bug that gate exists to prevent, just moved one layer up.
    safety_metadata: dict[str, Any] = {"alignment_considerations": alignment_considerations}
    if risk_level is not None:
        safety_metadata["risk_level"] = risk_level
    if reversibility is not None:
        safety_metadata["reversibility"] = reversibility
    if affected_systems is not None:
        safety_metadata["affected_systems"] = affected_systems
    if requires_review is not None:
        safety_metadata["requires_review"] = requires_review
    safety_metadata["safety_category"] = safety_category

    return await _request(
        "capture_decision", "POST", f"/api/memory/{quote(project, safe='')}/decisions",
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
        "propose_goal", "POST", f"/api/memory/{quote(project, safe='')}/goals",
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
    try:
        shape = _build_session_shape()
    except Exception:
        # Session-shape is an enhancement on top of end_session's real job
        # (recording the summary) -- a bug here must never stop that from
        # happening.
        shape = None
    body: dict[str, Any] = {"summary": summary, "session_type": "manual", "agent_name": agent}
    if shape is not None:
        body["session_shape"] = shape
    try:
        return await _request(
            "end_session", "POST", f"/api/memory/{quote(project, safe='')}/sessions/record",
            json=body,
        )
    finally:
        # Reset regardless of success -- a failed flush's telemetry is lost
        # rather than retried (best-effort behavioral data, not audit-critical).
        # Guarded so a reset bug can't mask the real return value/exception
        # above (an exception raised in `finally` overrides one from `try`).
        try:
            _reset_session_shape()
        except Exception:
            pass


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
        "get_context_bundle", "POST", f"/api/memory/{quote(project, safe='')}/prefetch",
        json={"task": task, "token_budget": token_budget},
    )


@mcp.tool()
async def check_contradictions(project: str) -> dict[str, Any]:
    """Scan a project's decisions for unresolved contradictions.

    Returns conflicting decision pairs (e.g. "use MySQL" vs "use Postgres"
    both still active) with severity and a resolution suggestion.
    """
    return await _request("check_contradictions", "GET", f"/api/memory/{quote(project, safe='')}/contradictions")


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
        "check_diff_for_conflicts", "POST", f"/api/memory/{quote(project, safe='')}/ghost-check",
        json={"diff": diff},
    )


@mcp.tool()
async def override_ghost_warning(
    project: str, decision_id: str, rationale: str, agent: str = "unspecified"
) -> dict[str, Any]:
    """Explicitly override a blocked ghost/contradiction warning for one decision.

    check_diff_for_conflicts raises an error instead of returning normally
    when a high-severity warning has no recorded override (see #53's
    enforceable gate policy) — call this first with your reasoning, then
    retry check_diff_for_conflicts. The override is written into the
    project's audit trail, not silently applied.

    Args:
        project: Project name.
        decision_id: The decision the warning was raised against.
        rationale: Why this warning is being overridden.
        agent: Your own name (e.g. "Claude", "Cursor", "Gemini").
    """
    return await _request(
        "override_ghost_warning", "POST",
        f"/api/memory/{quote(project, safe='')}/decisions/{quote(decision_id, safe='')}/override",
        json={"rationale": rationale, "agent_name": agent},
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
        "friction_scan", "POST", f"/api/memory/{quote(project, safe='')}/friction/scan",
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
        "record_skill_outcome", "POST", f"/api/memory/{quote(project, safe='')}/agent-skills/record",
        json={
            "session_type": session_type,
            "categories": categories,
            "outcome": outcome,
            "details": details,
            "agent_name": agent,
        },
    )


@mcp.tool()
async def get_handoff_packet(
    project: str, role: str, token_budget: int = 4000, agent: str = "unspecified"
) -> dict[str, Any]:
    """Generate a role-aware context bundle for handing work off to another agent.

    The response includes packet_hash (#59) -- pass it to acknowledge_handoff
    once you've read the packet and understood its constraints, so it's not
    left showing as an unacknowledged handoff in Needs Attention.

    Args:
        project: Project name.
        role: The receiving agent's role (e.g. "reviewer", "implementer", "tester").
        token_budget: Maximum token budget for the packet.
        agent: Your own name (e.g. "Claude", "Cursor", "Gemini").
    """
    return await _request(
        "get_handoff_packet", "POST", f"/api/memory/{quote(project, safe='')}/handoff",
        json={"role": role, "token_budget": token_budget, "agent_name": agent},
    )


@mcp.tool()
async def acknowledge_handoff(
    project: str, packet_hash: str, agent: str = "unspecified",
    acknowledged_constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Acknowledge a handoff packet you received via get_handoff_packet.

    Records the acknowledgment in the project's audit trail (#52) and
    clears the packet from Needs Attention's unacknowledged-handoffs list.
    Voluntary, not required to proceed with normal writes -- but skipping
    it leaves the handoff visibly outstanding for a human to notice.

    Args:
        project: Project name.
        packet_hash: The packet_hash returned by get_handoff_packet.
        agent: Your own name (e.g. "Claude", "Cursor", "Gemini").
        acknowledged_constraints: Optional list of specific constraints from
            the packet you're confirming you understood.
    """
    return await _request(
        "acknowledge_handoff", "POST",
        f"/api/memory/{quote(project, safe='')}/handoff/acknowledge",
        json={
            "packet_hash": packet_hash, "agent_name": agent,
            "acknowledged_constraints": acknowledged_constraints or [],
        },
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
        "explain_why", "POST", f"/api/memory/{quote(project, safe='')}/explain",
        json={"question": question},
    )


@mcp.tool()
async def run_deep_research(
    project: str, query: str, hybrid: bool = False, max_steps: int = 3,
) -> dict[str, Any]:
    """Run Deep Research on a query and import findings as citations into
    Tropebook (wishlist #90 -- confirmed gap: no research/feed tools
    existed before this).

    Two engines, picked via `hybrid`:
    - False (default): web-researcher-mcp only -- citation-grade web
      sources, real URLs, no fabricated citations. Faster, ~30-90s.
    - True: last30days (social/news signal fanout: Reddit, X, YouTube,
      HN, web) and web-researcher-mcp run concurrently, then merged by
      the project's LLM backend. Slower, genuinely 1-3+ minutes -- this
      call uses an extended timeout accordingly, don't assume a fast
      response.

    Args:
        project: Project name.
        query: The research question/topic.
        hybrid: Use both engines and merge (slower, broader) instead of
            just web-researcher-mcp (faster, narrower).
        max_steps: Search->refine->search steps for the web-researcher-mcp
            leg (1-6 for web-only, 1-4 for hybrid's web leg).
    """
    if hybrid:
        return await _request(
            "run_deep_research", "POST",
            f"/api/memory/{quote(project, safe='')}/deep-research/hybrid",
            json={"query": query, "max_web_steps": max_steps},
            timeout=480.0,
        )
    return await _request(
        "run_deep_research", "POST",
        f"/api/memory/{quote(project, safe='')}/deep-research/web-research",
        json={"topic": query, "max_steps": max_steps},
        timeout=180.0,
    )


@mcp.tool()
async def list_research_feeds(
    enabled_only: bool = False, tag: str | None = None,
) -> dict[str, Any]:
    """List Tropelex's scheduled research feeds -- named, recurring queries
    that accumulate citations over time.

    Args:
        enabled_only: Only return feeds that are currently active.
        tag: Filter to feeds carrying this tag.
    """
    params = []
    if enabled_only:
        params.append("enabled_only=true")
    if tag:
        params.append(f"tag={quote(tag, safe='')}")
    qs = f"?{'&'.join(params)}" if params else ""
    return await _request("list_research_feeds", "GET", f"/api/research-feeds{qs}")


@mcp.tool()
async def get_research_feed(feed_id: str) -> dict[str, Any]:
    """Get one research feed's configuration and metadata (name, query,
    interval, tags, total citations, last run time).

    Args:
        feed_id: The feed's id, from list_research_feeds.
    """
    return await _request(
        "get_research_feed", "GET", f"/api/research-feeds/{quote(feed_id, safe='')}"
    )


@mcp.tool()
async def run_research_feed(feed_id: str) -> dict[str, Any]:
    """Trigger an immediate run of a scheduled research feed, ingesting new
    citations right now instead of waiting for its next scheduled run.

    This invokes a real research provider (web_search or deep_research,
    per the feed's own config), so it can take anywhere from a few seconds
    to a couple of minutes depending on which provider the feed uses.

    Args:
        feed_id: The feed's id, from list_research_feeds.
    """
    return await _request(
        "run_research_feed", "POST", f"/api/research-feeds/{quote(feed_id, safe='')}/run",
        timeout=180.0,
    )


# ── Prompts ──────────────────────────────────────────────────────────────
# MCP prompts (distinct from tools above) are auto-surfaced as native slash
# commands by clients that support prompt discovery -- Devin CLI
# (/mcp__tropelex__<name>), Gemini CLI, and Zed (via ACP, when the backing
# agent is one of the above). No client-side command files needed for those
# three; this is the one shared addition that covers all of them. Content
# mirrors .claude/commands/*.md exactly -- same project-resolution
# reasoning, just as a prompt template instead of hand-written prose for a
# single client.


@mcp.prompt()
def tropelex_show_context(project: str | None = None) -> str:
    """Show Tropelex's accumulated context for the current project."""
    hint = f' (you may already know it as "{project}")' if project else ""
    return (
        f"Call list_projects first, and match the current repository directory "
        f"name{hint} against the returned project names case-insensitively: "
        "project names are case-sensitive server-side, so don't guess the "
        "directory name's exact casing. If nothing matches clearly, ask which "
        "project to use.\n\n"
        "Then call get_project_memory for that project and summarize what it "
        "returns for the user: past decisions and their rationale, session "
        "summaries, learned patterns, and preferences, so this session starts "
        "with the accumulated context instead of from scratch."
    )


@mcp.prompt()
def tropelex_record_decision(decision: str, context: str = "") -> str:
    """Record a decision in Tropelex memory."""
    return (
        "Call list_projects first, and match the current repository directory "
        "name against the returned project names case-insensitively: project "
        "names are case-sensitive server-side, so don't guess the directory "
        "name's exact casing. If nothing matches clearly, ask which project "
        "to use.\n\n"
        "Record this decision in Tropelex using the capture_decision tool for "
        "that project.\n\n"
        f"Decision: {decision}\n"
        f"Context: {context or '(none given -- ask if it would help future recall)'}\n\n"
        "capture_decision requires safety_category; if you omit it the call "
        "is rejected with a suggested category attached -- read it and either "
        "accept (retry with it) or override with a better-fitting one. After "
        "recording, confirm briefly and continue with the task at hand."
    )


@mcp.prompt()
def tropelex_end_session(summary: str) -> str:
    """End the session and record it in Tropelex for pattern learning."""
    return (
        "Call list_projects first, and match the current repository directory "
        "name against the returned project names case-insensitively: project "
        "names are case-sensitive server-side, so don't guess the directory "
        "name's exact casing. If nothing matches clearly, ask which project "
        "to use.\n\n"
        f"Session summary: {summary or '(none given -- write one from the conversation)'}\n\n"
        "Call end_session for that project with that summary and your own "
        "agent name (e.g. \"Devin\", \"Gemini\", \"Zed\") in the agent field: "
        "this attributes the session so per-agent skill and persona tracking "
        "has real data instead of everything landing under \"unspecified\". "
        "Confirm to the user once it's recorded."
    )


@mcp.prompt()
def tropelex_up(description: str = "", tech_stack: str = "") -> str:
    """Register a new project with Tropelex (description + tech stack)."""
    return (
        "Call list_projects first, and match the current repository directory "
        "name against the returned project names case-insensitively. If a "
        "matching project already exists, tell the user it's already "
        "registered and stop -- don't re-create it. (Note: capture_decision "
        "and end_session already auto-create a project on first use if it "
        "doesn't exist yet, just without a description or tech stack -- this "
        "prompt is specifically for setting those up properly instead of "
        "leaving them blank.)\n\n"
        "If no matching project exists: there's no tool for project creation "
        "with metadata, so use the REST API directly -- "
        "POST http://localhost:8766/api/memory with JSON body "
        '{"project_name": <current directory\'s basename>, "description": '
        '<description>, "tech_stack": [<tech_stack items>]}.\n\n'
        f"Description: {description or '(none given -- infer one from the project files you can see, e.g. package.json, requirements.txt, pyproject.toml)'}\n"
        f"Tech stack: {tech_stack or '(none given -- infer from the same files)'}\n\n"
        "Confirm to the user once the project is created, and mention the "
        "show-context, record-decision, and end-session prompts as what "
        "they'll use from here."
    )


if __name__ == "__main__":
    mcp.run()
