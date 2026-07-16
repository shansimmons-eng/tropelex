"""
Tropelex Living ADR Generator
Auto-generates Architecture Decision Records from project memory.

Supports multiple ADR formats:
- Nygard: The original format by Michael Nygard
- MADR: Markdown Any Decision Records
- Custom: Tropelex-enhanced format with decision tree context
"""

from datetime import datetime, timezone
from typing import Any

from core.decision_tree import DecisionTree


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:60]


def generate_nygard_adr(decision: dict, index: int, tree: DecisionTree | None = None) -> str:
    """
    Generate ADR in Michael Nygard format.
    Title: ADR-{index}: {decision title}
    """
    title = decision.get("decision", "Untitled Decision")
    context = decision.get("context", "")
    rationale = decision.get("rationale", "")
    timestamp = decision.get("timestamp", "")[:10]
    source = decision.get("source", "manual")
    categories = decision.get("categories", [])

    did = decision.get("id", "")
    ancestors = tree.get_ancestors(did) if tree and did else []
    descendants = tree.get_descendants(did) if tree and did else []

    lines = [
        f"# ADR-{index:03d}: {title}",
        "",
        f"Date: {timestamp}",
        f"Source: {source}",
    ]
    if categories:
        lines.append(f"Categories: {', '.join(categories)}")

    lines += [
        "",
        "## Status",
        "",
    ]

    # Determine status based on whether it's been superseded
    if descendants:
        rels = [d.get("relationship", "") for d in descendants]
        if "supersedes" in rels or "reverts" in rels:
            lines.append("Superseded")
        else:
            lines.append("Accepted")
    else:
        lines.append("Accepted")

    lines += [
        "",
        "## Context",
        "",
        context or "No context recorded.",
        "",
        "## Decision",
        "",
        title,
        "",
    ]

    if rationale:
        lines += [
            "## Rationale",
            "",
            rationale,
            "",
        ]

    # Decision tree context
    if ancestors:
        lines += [
            "## Preceded By",
            "",
        ]
        for a in ancestors:
            rel = a.get("relationship", "related_to")
            d = a.get("decision", {})
            lines.append(f"- [{rel}] {d.get('decision', 'Unknown')}")
        lines.append("")

    if descendants:
        lines += [
            "## Led To",
            "",
        ]
        for d_node in descendants:
            rel = d_node.get("relationship", "related_to")
            d = d_node.get("decision", {})
            lines.append(f"- [{rel}] {d.get('decision', 'Unknown')}")
        lines.append("")

    return "\n".join(lines)


def generate_madr_adr(decision: dict, index: int, tree: DecisionTree | None = None) -> str:
    """
    Generate ADR in MADR (Markdown Any Decision Records) format.
    """
    title = decision.get("decision", "Untitled Decision")
    context = decision.get("context", "")
    rationale = decision.get("rationale", "")
    timestamp = decision.get("timestamp", "")[:10]
    categories = decision.get("categories", [])

    did = decision.get("id", "")
    ancestors = tree.get_ancestors(did) if tree and did else []

    lines = [
        f"# {title}",
        "",
        f"## Metadata",
        "",
        f"| Key | Value |",
        f"|-----|-------|",
        f"| Date | {timestamp} |",
        f"| Source | {decision.get('source', 'manual')} |",
    ]
    if categories:
        lines.append(f"| Categories | {', '.join(categories)} |")

    lines += [
        "",
        "## Context and Problem Statement",
        "",
        context or "No context recorded.",
        "",
        "## Considered Options",
        "",
        f"* {title}",
    ]

    if ancestors:
        for a in ancestors:
            d = a.get("decision", {})
            lines.append(f"* ~~{d.get('decision', 'Unknown')}~~ (previous)")

    lines += [
        "",
        "## Decision Outcome",
        "",
        f"Chosen: {title}",
        "",
    ]

    if rationale:
        lines += [
            "### Rationale",
            "",
            rationale,
            "",
        ]

    # Pros/Cons (inferred from context)
    lines += [
        "### Consequences",
        "",
        "- Good: Decision recorded and traceable",
    ]
    if ancestors:
        lines.append(f"- Good: Clear lineage from {len(ancestors)} prior decision(s)")
    lines.append("")

    return "\n".join(lines)


def generate_tropelex_adr(decision: dict, index: int, tree: DecisionTree | None = None) -> str:
    """
    Generate ADR in Tropelex-enhanced format.
    Includes full decision tree context, patterns, and tech stack.
    """
    title = decision.get("decision", "Untitled Decision")
    context = decision.get("context", "")
    rationale = decision.get("rationale", "")
    timestamp = decision.get("timestamp", "")[:10]
    source = decision.get("source", "manual")
    categories = decision.get("categories", [])
    hash_val = decision.get("hash", "")

    did = decision.get("id", "")
    ancestors = tree.get_ancestors(did) if tree and did else []
    descendants = tree.get_descendants(did) if tree and did else []

    lines = [
        f"# ADR: {title}",
        "",
        "---",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Date** | {timestamp} |",
        f"| **ID** | {hash_val or did} |",
        f"| **Source** | {source} |",
    ]
    if categories:
        lines.append(f"| **Categories** | {', '.join(categories)} |")

    # Status
    status = "Accepted"
    if descendants:
        rels = [d.get("relationship", "") for d in descendants]
        if "reverts" in rels:
            status = "Reverted"
        elif "supersedes" in rels:
            status = "Superseded"
    lines.append(f"| **Status** | {status} |")

    lines += [
        "",
        "---",
        "",
        "## Decision",
        "",
        f"> {title}",
        "",
    ]

    if context:
        lines += [
            "## Context",
            "",
            context,
            "",
        ]

    if rationale:
        lines += [
            "## Rationale",
            "",
            rationale,
            "",
        ]

    # Decision tree lineage
    if ancestors or descendants:
        lines += [
            "## Decision Lineage",
            "",
        ]
        if ancestors:
            lines.append("### What Led Here")
            lines.append("")
            for a in ancestors:
                rel = a.get("relationship", "related_to")
                d = a.get("decision", {})
                ts = d.get("timestamp", "")[:10]
                lines.append(f"- **[{rel}]** `{ts}` {d.get('decision', 'Unknown')}")
            lines.append("")

        if descendants:
            lines.append("### What Followed")
            lines.append("")
            for d_node in descendants:
                rel = d_node.get("relationship", "related_to")
                d = d_node.get("decision", {})
                ts = d.get("timestamp", "")[:10]
                lines.append(f"- **[{rel}]** `{ts}` {d.get('decision', 'Unknown')}")
            lines.append("")

    # Metadata footer
    lines += [
        "---",
        "",
        f"*Generated by Tropelex on {_now()}*",
    ]

    return "\n".join(lines)


def generate_adr(decision: dict, index: int, format: str = "tropelex", tree: DecisionTree | None = None) -> str:
    """Generate an ADR in the specified format."""
    generators = {
        "nygard": generate_nygard_adr,
        "madr": generate_madr_adr,
        "tropelex": generate_tropelex_adr,
    }
    gen = generators.get(format, generate_tropelex_adr)
    return gen(decision, index, tree)


def generate_adrs_for_project(
    project_memory: dict,
    format: str = "tropelex",
    only_significant: bool = True,
) -> list[dict[str, str]]:
    """
    Generate ADRs for all decisions in a project.
    Returns [{filename, content, decision_id}].

    If only_significant=True, skips trivial decisions (single-word, < 20 chars).
    """
    decisions = project_memory.get("decisions", [])
    if not decisions:
        return []

    tree = DecisionTree.from_decisions(decisions)
    project_name = project_memory.get("project_name", "project")

    adrs = []
    for i, decision in enumerate(decisions, 1):
        text = decision.get("decision", "")

        # Filter trivial decisions
        if only_significant:
            if len(text) < 20:
                continue
            if len(text.split()) < 3:
                continue

        did = decision.get("hash") or decision.get("id", f"decision-{i}")
        slug = _slugify(text[:50])
        filename = f"ADR-{i:03d}-{slug}.md"

        content = generate_adr(decision, i, format, tree)

        adrs.append({
            "filename": filename,
            "content": content,
            "decision_id": did,
            "decision_text": text,
            "index": i,
        })

    return adrs


def generate_adr_markdown_bundle(
    project_memory: dict,
    format: str = "tropelex",
) -> str:
    """
    Generate a single markdown file containing all ADRs for a project.
    Useful for export/documentation.
    """
    project_name = project_memory.get("project_name", "Project")
    adrs = generate_adrs_for_project(project_memory, format)

    if not adrs:
        return f"# {project_name} — Architecture Decision Records\n\nNo decisions recorded yet."

    lines = [
        f"# {project_name} — Architecture Decision Records",
        "",
        f"Generated: {_now()}",
        f"Total decisions: {len(adrs)}",
        "",
        "## Table of Contents",
        "",
    ]

    for adr in adrs:
        lines.append(f"- [{adr['filename']}](#{adr['filename'].lower().replace('.md', '')})")

    lines.append("")

    for adr in adrs:
        lines.append(f"---")
        lines.append("")
        lines.append(adr["content"])
        lines.append("")

    return "\n".join(lines)
