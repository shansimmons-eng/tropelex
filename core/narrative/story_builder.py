"""
Narrative Story Builder — generates prose narratives from the decision graph.

Turns decision history into audience-specific stories: origin, pivots,
current state. All functions pure (no I/O), memory dict passed in.
"""

from datetime import datetime, timezone

from core.decision_tree import DecisionTree
from core.knowledge_decay import score_decision
from core.narrative import (
    Err,
    NarrativeReport,
    NarrativeSection,
    Ok,
    Result,
)


def generate_origin_section(timeline: list[dict]) -> NarrativeSection:
    """'How it all started' — first decisions, initial tech stack.

    Takes a pre-sorted timeline (from DecisionTree.get_timeline())
    and frames the earliest entries as the project's founding choices.
    """
    first = timeline[:3]
    if not first:
        return NarrativeSection(
            heading="How It All Started",
            body="No founding decisions recorded yet.",
            section_type="origin",
        )
    lines = [f"The project began with: '{d.get('decision', 'an unnamed choice')}'" for d in first]
    body = " ".join(lines)
    return NarrativeSection(heading="How It All Started", body=body, section_type="origin")


def generate_pivot_section(tree: DecisionTree) -> NarrativeSection:
    """'What changed and why' — superseded decisions, reversals.

    Uses the decision tree's chains and edges to find supersedes/reverts
    and frames them as deliberate course corrections.
    """
    chains = tree.get_chains()
    reversal_edges = [e for e in tree.edges if e["relationship"] in ("supersedes", "reverts")]
    # Also surface pivot decisions from chains (caused_by sequences)
    chain_pivots = [c[-1] for c in chains if len(c) > 1]
    if not reversal_edges and not chain_pivots:
        return NarrativeSection(
            heading="What Changed and Why",
            body="The project has followed a steady course with no major reversals.",
            section_type="pivot",
        )
    pivot_lines = []
    for edge in reversal_edges[:3]:
        orig = tree.nodes.get(edge["target"], {})
        new = tree.nodes.get(edge["source"], {})
        orig_text = orig.get("decision", "an earlier choice")[:60]
        new_text = new.get("decision", "a new direction")[:60]
        pivot_lines.append(f"'{orig_text}' was replaced by '{new_text}'")
    for cp in chain_pivots[:2]:
        if len(pivot_lines) >= 3:
            break
        pivot_lines.append(f"This led to: '{cp.get('decision', '')[:60]}'")
    body = " ".join(pivot_lines) if pivot_lines else "Multiple evolution paths detected."
    return NarrativeSection(heading="What Changed and Why", body=body, section_type="pivot")


def generate_resolution_section(decisions: list[dict], timeline: list[dict]) -> NarrativeSection:
    """'Where we are now' — current high-confidence decisions.

    Filters to decisions scoring 'high' or 'medium' confidence
    via score_decision, presenting the active architecture.
    """
    scored = [(d, score_decision(d, decisions)) for d in timeline]
    active = [(d, s) for d, s in scored if s["tier"] in ("high", "medium")]
    active.sort(key=lambda x: x[1]["score"], reverse=True)
    if not active:
        return NarrativeSection(
            heading="Where We Are Now",
            body="No high-confidence decisions found to describe the current state.",
            section_type="resolution",
        )
    top = active[:5]
    lines = [f"Currently: '{d.get('decision', '')[:60]}' (confidence: {s['tier']})" for d, s in top]
    body = " ".join(lines)
    return NarrativeSection(heading="Where We Are Now", body=body, section_type="resolution")


def summarize_decisions(decisions: list[dict], max_items: int = 5) -> str:
    """One-paragraph summary of the most important decisions.

    Ranks by confidence score and joins the top N into prose.
    """
    if not decisions:
        return "No decisions recorded for this project."
    scored = [(d, score_decision(d, decisions)) for d in decisions]
    scored.sort(key=lambda x: x[1]["score"], reverse=True)
    top = scored[:max_items]
    parts = [f"'{d.get('decision', '')[:50]}'" for d, _ in top]
    return "Key decisions include: " + "; ".join(parts) + "."


def build_narrative(memory: dict, audience: str = "new_hire") -> Result[NarrativeReport]:
    """Generate a full prose narrative from project memory.

    Loads decisions from memory dict, builds timeline via DecisionTree,
    and generates audience-specific sections. Returns NarrativeReport.
    """
    if not isinstance(memory, dict):
        return Err(error="memory must be a dict", code="VALIDATION_ERROR")
    valid_audiences = ("investor", "new_hire", "pm")
    if audience not in valid_audiences:
        return Err(error=f"audience must be one of {valid_audiences}", code="VALIDATION_ERROR")

    decisions = memory.get("decisions", [])
    if not decisions:
        return Err(error="No decisions found in memory", code="NOT_FOUND")

    tree = DecisionTree.from_decisions(decisions)
    timeline = tree.get_timeline()
    origin = generate_origin_section(timeline)
    pivot = generate_pivot_section(tree)
    resolution = generate_resolution_section(decisions, timeline)
    summary_text = summarize_decisions(decisions)

    sections = _select_sections(audience, origin, pivot, resolution)
    word_count = sum(len(s.body.split()) for s in sections)
    project_name = memory.get("project_name", "Unknown Project")

    report = NarrativeReport(
        title=f"{project_name} — Project Story ({audience})",
        sections=sections,
        summary=summary_text,
        audience=audience,
        word_count=word_count,
        project_name=project_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    return Ok(value=report)


def _select_sections(
    audience: str,
    origin: NarrativeSection,
    pivot: NarrativeSection,
    resolution: NarrativeSection,
) -> list[NarrativeSection]:
    """Pick and order sections based on audience interest.

    investor: pivots → resolution → origin (what changed, where we are, background)
    new_hire: origin → pivot → resolution (learn the history)
    pm: pivot → resolution → origin (challenges, current state, context)
    """
    if audience == "investor":
        return [pivot, resolution, origin]
    if audience == "pm":
        return [pivot, resolution, origin]
    return [origin, pivot, resolution]
