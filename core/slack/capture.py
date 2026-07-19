"""
Slack Decision Capture — pure functions for capturing and extracting
decisions from chat-style messages.
"""

import re
from typing import Any

from core.slack import (
    CapturedDecision,
    ExtractionResult,
    Ok,
    Err,
    Result,
    SlackCaptureError,
)

# Patterns that signal a decision was made
_DECISION_SIGNALS = [
    re.compile(r"\blet'?s go with\b", re.IGNORECASE),
    re.compile(r"\bwe (?:decided|agreed|chose|picked)\b", re.IGNORECASE),
    re.compile(r"\bswitching to\b", re.IGNORECASE),
    re.compile(r"\bgoing with\b", re.IGNORECASE),
    re.compile(r"\bsettled on\b", re.IGNORECASE),
    re.compile(r"\bapproved\b", re.IGNORECASE),
    re.compile(r"\bconfirmed\b", re.IGNORECASE),
    re.compile(r"\bwe'?re (?:using|doing|going)\b", re.IGNORECASE),
    re.compile(r"\bdecision:\b", re.IGNORECASE),
    re.compile(r"\btldr:\b", re.IGNORECASE),
]

# Conflict keywords — opposing positions
_OPPOSING_PAIRS = [
    ({"rest", "restful"}, {"graphql", "grpc"}),
    ({"react"}, {"vue", "angular", "svelte"}),
    ({"postgres", "postgresql"}, {"mysql", "mariadb"}),
    ({"mongodb", "mongo"}, {"postgres", "mysql", "sql"}),
    ({"typescript"}, {"javascript"}),
    ({"docker"}, {"kubernetes", "k8s"}),
    ({"monolith", "monolithic"}, {"microservice", "microservices"}),
]


def detect_decision_signals(message: str) -> bool:
    """Check if a message contains decision-making language."""
    if not message or not isinstance(message, str):
        return False
    return any(pat.search(message) for pat in _DECISION_SIGNALS)


def extract_decision_text(message: str) -> str:
    """Extract the core decision from a message, stripping signal phrases."""
    if not message:
        return ""
    # Try to find text after signal phrases
    for pat in _DECISION_SIGNALS:
        m = pat.search(message)
        if m:
            rest = message[m.end():].strip()
            if rest:
                return rest[:200]
    # Fallback: return the message itself (trimmed)
    return message.strip()[:200]


def detect_conflict(
    new_decision: str,
    existing_decisions: list[dict[str, Any]],
) -> list[str]:
    """Find existing decisions that conflict with the new one."""
    if not new_decision or not existing_decisions:
        return []

    new_words = set(re.findall(r"[a-z][a-z0-9]+", new_decision.lower()))
    conflicts: list[str] = []

    for d in existing_decisions:
        text = d.get("decision", "")
        existing_words = set(re.findall(r"[a-z][a-z0-9]+", text.lower()))

        for pos, neg in _OPPOSING_PAIRS:
            if (new_words & pos and existing_words & neg) or \
               (new_words & neg and existing_words & pos):
                conflicts.append(text)
                break

    return conflicts


def capture_decision(
    memory: dict[str, Any],
    decision_text: str,
    context: str = "",
    channel: str = "",
    agent_name: str = "",
) -> Result[CapturedDecision]:
    """Add a captured decision to project memory."""
    if not decision_text or not isinstance(decision_text, str):
        return Err(error="decision_text must be a non-empty string", code="VALIDATION_ERROR")

    from datetime import datetime, timezone

    decision = CapturedDecision(
        decision_text=decision_text.strip()[:500],
        context=context.strip()[:500],
        source="manual",
        channel=channel.strip()[:100],
        timestamp=datetime.now(timezone.utc).isoformat(),
        agent_name=agent_name.strip()[:100],
    )

    # Add to memory
    memory.setdefault("decisions", []).append({
        "timestamp": decision.timestamp,
        "decision": decision.decision_text,
        "context": decision.context or f"Captured from Slack ({decision.channel})",
        "source": "slack",
    })

    return Ok(value=decision)


def extract_decisions_from_thread(
    messages: list[str],
) -> Result[ExtractionResult]:
    """Extract implicit decisions from a list of chat messages."""
    if not isinstance(messages, list):
        return Err(error="messages must be a list of strings", code="VALIDATION_ERROR")

    from datetime import datetime, timezone

    extracted: list[CapturedDecision] = []
    now = datetime.now(timezone.utc).isoformat()

    for i, msg in enumerate(messages):
        if not isinstance(msg, str):
            continue
        if detect_decision_signals(msg):
            text = extract_decision_text(msg)
            if text:
                extracted.append(CapturedDecision(
                    decision_text=text,
                    context=f"Extracted from message {i + 1}",
                    source="extracted",
                    channel="",
                    timestamp=now,
                    agent_name="",
                ))

    summary = f"Extracted {len(extracted)} decision(s) from {len(messages)} message(s)"

    return Ok(value=ExtractionResult(
        decisions=tuple(extracted),
        thread_summary=summary,
        extraction_count=len(extracted),
    ))
