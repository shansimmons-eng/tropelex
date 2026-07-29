"""Agent Surface Audit — scans the agent's own harness configuration for risk.

Every other Tropelex detection feature (Ghost Decisions, Contradictions, Doc
Mining) audits the *code and decisions* an agent produces. Nothing audits the
agent's own operating environment: CLAUDE.md/AGENTS.md, .claude/settings.json,
.mcp.json, hooks, and skill/agent definitions. A misconfigured hook, an
over-broad tool permission, or a leaked key in a committed config file is a
safety-relevant risk that never shows up in a decision graph.

Inspired by AgentShield (github.com/affaan-m/agentshield) — same five-category
shape (secrets, permissions, hooks, MCP, agent config) — reimplemented here as
pure functions so it plugs into the existing severity-ranked finding pattern
used by Contradictions and Doc Mining, instead of shelling out to a separate
tool.
"""
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, Union

T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    """Success wrapper — carries the resulting value."""
    value: T


@dataclass(frozen=True)
class Err:
    """Error wrapper — carries an error message and code."""
    error: str
    code: str = "UNKNOWN"
    details: dict[str, Any] | None = None


Result = Union[Ok[T], Err]


class AgentAuditError(Exception):
    """Base for agent-audit errors."""
    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class AuditFinding:
    """A single risk finding from scanning the agent's harness config."""
    id: str
    category: str  # secrets | permissions | hooks | mcp | agent_config
    severity: str  # low | medium | high | critical
    file: str
    line: int
    description: str
    recommendation: str


@dataclass(frozen=True)
class AuditReport:
    """Full audit result: every finding plus summary stats."""
    findings: list[AuditFinding] = field(default_factory=list)
    files_scanned: list[str] = field(default_factory=list)
    category_counts: dict[str, int] = field(default_factory=dict)
    severity_distribution: dict[str, int] = field(default_factory=dict)
    grade: str = "A"
