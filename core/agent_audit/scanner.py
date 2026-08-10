"""Agent Surface Audit — scanner functions.

Pure functions where possible; `audit_agent_surface` is the one IO boundary
(reads files from disk). Everything else takes already-read text/JSON and
returns findings, so the detection logic itself stays unit-testable without
a filesystem.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from core.agent_audit import AuditFinding, AuditReport
from core.injection_sentinel import INJECTION_MARKERS as _INJECTION_MARKERS

# ---------------------------------------------------------------------------
# Category 1: secrets detection
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("OpenAI API Key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Anthropic API Key", re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Private Key Header", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "Generic high-entropy secret assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"
            r"['\"][A-Za-z0-9+/_\-]{20,}['\"]"
        ),
    ),
]


def scan_secrets(content: str, file: str) -> list[AuditFinding]:
    """Scan file text for hardcoded secrets. Pure function."""
    findings: list[AuditFinding] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(_finding(
                    category="secrets",
                    severity="critical",
                    file=file,
                    line=line_no,
                    description=f"{label} pattern found in {file}",
                    recommendation="Remove the secret, rotate it, and load it from an environment "
                                    "variable or .env file instead (confirm .env is gitignored).",
                ))
                break  # one finding per line is enough signal
    return findings


# ---------------------------------------------------------------------------
# Category 2: permission auditing (.claude/settings*.json)
# ---------------------------------------------------------------------------

_DANGEROUS_PERMISSION_PATTERNS = [
    re.compile(r"^Bash\(\*\)$"),
    re.compile(r"^Bash$"),
    re.compile(r".*rm\s+-rf.*\*.*"),
]


def scan_permissions(settings: dict[str, Any], file: str) -> list[AuditFinding]:
    """Audit a parsed settings.json for over-broad tool permissions."""
    findings: list[AuditFinding] = []

    if settings.get("dangerouslySkipPermissions") is True:
        findings.append(_finding(
            category="permissions", severity="critical", file=file, line=1,
            description="dangerouslySkipPermissions is enabled — every tool call runs unconfirmed",
            recommendation="Remove dangerouslySkipPermissions unless this is a fully sandboxed, "
                            "disposable environment.",
        ))

    allow = settings.get("permissions", {}).get("allow", [])
    for rule in allow if isinstance(allow, list) else []:
        if not isinstance(rule, str):
            continue
        if any(p.match(rule) for p in _DANGEROUS_PERMISSION_PATTERNS):
            findings.append(_finding(
                category="permissions", severity="high", file=file, line=1,
                description=f"Unrestricted permission rule: '{rule}'",
                recommendation="Scope the rule to specific commands/paths instead of a wildcard "
                                "(e.g. 'Bash(git *)' instead of 'Bash(*)').",
            ))

    return findings


# ---------------------------------------------------------------------------
# Category 3: hook injection analysis
# ---------------------------------------------------------------------------

_HOOK_INJECTION_PATTERNS = [
    (re.compile(r"curl[^|\n]*\|\s*(ba)?sh"), "Pipes a remote download straight into a shell"),
    (re.compile(r"\beval\s+[\"$]"), "Uses eval on interpolated input"),
    (re.compile(r"\$\{?ARGUMENTS\}?[^\"']*(?<!\")\s*$"), "Interpolates $ARGUMENTS unquoted into a command"),
    (re.compile(r"wget[^|\n]*\|\s*(ba)?sh"), "Pipes a remote download straight into a shell"),
]


def scan_hooks(settings: dict[str, Any], file: str) -> list[AuditFinding]:
    """Audit hook command strings in a parsed settings.json for injection risk."""
    findings: list[AuditFinding] = []
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return findings

    for event, entries in hooks.items():
        for entry in entries if isinstance(entries, list) else []:
            for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
                command = hook.get("command", "") if isinstance(hook, dict) else ""
                for pattern, label in _HOOK_INJECTION_PATTERNS:
                    if pattern.search(command):
                        findings.append(_finding(
                            category="hooks", severity="high", file=file, line=1,
                            description=f"{event} hook: {label}",
                            recommendation="Validate/quote input before it reaches a shell, and "
                                           "avoid piping remote content directly into sh/bash.",
                        ))
    return findings


# ---------------------------------------------------------------------------
# Category 4: MCP server risk profiling (.mcp.json)
# ---------------------------------------------------------------------------

def scan_mcp_config(mcp_config: dict[str, Any], file: str) -> list[AuditFinding]:
    """Audit a parsed .mcp.json for risky MCP server definitions."""
    findings: list[AuditFinding] = []
    servers = mcp_config.get("mcpServers", {})
    if not isinstance(servers, dict):
        return findings

    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        command = spec.get("command", "")
        args = spec.get("args", [])
        joined_args = " ".join(str(a) for a in args) if isinstance(args, list) else ""

        if command == "npx" and "@latest" in joined_args:
            findings.append(_finding(
                category="mcp", severity="medium", file=file, line=1,
                description=f"MCP server '{name}' runs an unpinned '@latest' package via npx",
                recommendation="Pin to a specific version so a compromised upstream release "
                                "can't silently change what runs in this harness.",
            ))

        env = spec.get("env", {})
        if isinstance(env, dict) and any(
            isinstance(v, str) and v.startswith("$") and v.upper() == v
            for v in env.values()
        ):
            # a bare unresolved "$VAR" placeholder usually means a template was
            # committed without the real value being substituted at install time
            findings.append(_finding(
                category="mcp", severity="low", file=file, line=1,
                description=f"MCP server '{name}' has an env value that looks like an "
                             "unresolved placeholder",
                recommendation="Confirm env values are substituted at install time, not "
                                "committed as literal placeholder strings.",
            ))

    return findings


# ---------------------------------------------------------------------------
# Category 5: agent/skill config review
# ---------------------------------------------------------------------------
# _INJECTION_MARKERS is imported from core.injection_sentinel (#40) -- that
# module is the canonical home now; this file just reuses it for file/line
# config scanning rather than keeping its own copy.


def scan_agent_config(content: str, file: str) -> list[AuditFinding]:
    """Scan an agent/skill definition file for prompt-injection-style instructions."""
    findings: list[AuditFinding] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        for _name, pattern in _INJECTION_MARKERS:
            if pattern.search(line):
                findings.append(_finding(
                    category="agent_config", severity="high", file=file, line=line_no,
                    description=f"Suspicious instruction pattern in {file}: '{line.strip()[:80]}'",
                    recommendation="Review whether this line is legitimate or was injected via "
                                   "a compromised dependency, template, or copy-pasted source.",
                ))
                break
    return findings


# ---------------------------------------------------------------------------
# Orchestrator (the one IO boundary)
# ---------------------------------------------------------------------------

_CONFIG_GLOBS = ["CLAUDE.md", "AGENTS.md", ".mcp.json"]
_SETTINGS_FILES = [".claude/settings.json", ".claude/settings.local.json"]
_AGENT_GLOB = ".claude/agents/*.md"
_SKILL_GLOB = ".claude/skills/**/SKILL.md"

_SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.6, "medium": 0.3, "low": 0.1}


def _finding(category: str, severity: str, file: str, line: int,
             description: str, recommendation: str) -> AuditFinding:
    raw = f"{category}{file}{line}{description}"
    fid = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return AuditFinding(
        id=fid, category=category, severity=severity, file=file, line=line,
        description=description, recommendation=recommendation,
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def compute_grade(severity_distribution: dict[str, int]) -> str:
    """A-F grade from a severity distribution. Pure function."""
    penalty = sum(
        count * _SEVERITY_WEIGHT.get(sev, 0.0)
        for sev, count in severity_distribution.items()
    )
    if penalty == 0:
        return "A"
    if penalty < 1:
        return "B"
    if penalty < 2.5:
        return "C"
    if penalty < 5:
        return "D"
    return "F"


def audit_agent_surface(repo_path: str) -> AuditReport:
    """Scan a repo's agent harness configuration for risk. The one IO boundary
    in this module — every category scanner above is a pure function.
    """
    base = Path(repo_path)
    findings: list[AuditFinding] = []
    files_scanned: list[str] = []

    for rel in _CONFIG_GLOBS:
        path = base / rel
        if not path.is_file():
            continue
        text = _read_text(path)
        if text is None:
            continue
        files_scanned.append(rel)
        findings.extend(scan_secrets(text, rel))
        if rel == ".mcp.json":
            parsed = _read_json(path)
            if parsed is not None:
                findings.extend(scan_mcp_config(parsed, rel))

    for rel in _SETTINGS_FILES:
        path = base / rel
        if not path.is_file():
            continue
        text = _read_text(path)
        if text is None:
            continue
        files_scanned.append(rel)
        findings.extend(scan_secrets(text, rel))
        parsed = _read_json(path)
        if parsed is not None:
            findings.extend(scan_permissions(parsed, rel))
            findings.extend(scan_hooks(parsed, rel))

    for pattern in (_AGENT_GLOB, _SKILL_GLOB):
        for path in base.glob(pattern):
            if not path.is_file():
                continue
            text = _read_text(path)
            if text is None:
                continue
            rel = str(path.relative_to(base))
            files_scanned.append(rel)
            findings.extend(scan_secrets(text, rel))
            findings.extend(scan_agent_config(text, rel))

    category_counts: dict[str, int] = {}
    severity_distribution: dict[str, int] = {}
    for f in findings:
        category_counts[f.category] = category_counts.get(f.category, 0) + 1
        severity_distribution[f.severity] = severity_distribution.get(f.severity, 0) + 1

    return AuditReport(
        findings=findings,
        files_scanned=sorted(set(files_scanned)),
        category_counts=category_counts,
        severity_distribution=severity_distribution,
        grade=compute_grade(severity_distribution),
    )
