"""
PR Comment Builder — formats PR analysis results into markdown PR comments.

Pure functions that transform PRAnalysis data into human-readable markdown
for GitHub/Bitbucket PR comments. No I/O, no side effects.
"""

from core.prbot import (
    Err,
    Ok,
    PRComment,
    PRDecision,
    PRGhostWarning,
    Result,
)
from core.prbot.analyzer import PRAnalysis


def format_decision(decision: PRDecision) -> str:
    """Format a single decision for the PR comment.

    Pure function — same input always produces same output.
    """
    impact_label = (
        "high" if decision.impact_score >= 0.7
        else "medium" if decision.impact_score >= 0.4
        else "low"
    )
    return (
        f"• **Decision #{decision.decision_id}** "
        f"(confidence: {decision.confidence}, impact: {impact_label}, "
        f"relationship: {decision.relationship}) "
        f"— {decision.decision_text}"
    )


def format_warning(warning: PRGhostWarning) -> str:
    """Format a single ghost warning for the PR comment.

    Pure function — same input always produces same output.
    """
    return f"⚠️ **[{warning.severity}]** — {warning.recommendation}"


def generate_comment_summary(
    decisions: list[PRDecision],
    warnings: list[PRGhostWarning],
) -> str:
    """Generate a one-line summary of the PR analysis.

    Pure function — composes counts into a readable sentence.
    """
    parts: list[str] = []
    if decisions:
        dec_word = "decision" if len(decisions) == 1 else "decisions"
        parts.append(f"{len(decisions)} relevant {dec_word} found")
    if warnings:
        warn_word = "warning" if len(warnings) == 1 else "warnings"
        parts.append(f"{len(warnings)} ghost {warn_word} detected")
    return ", ".join(parts) if parts else "No relevant decisions or warnings found"


def build_pr_comment(analysis: PRAnalysis, project: str = "") -> Result:
    """Build a formatted markdown PR comment from analysis results.

    Pure function — no I/O, no side effects. Assembles markdown sections
    from the analysis data and returns a PRComment wrapped in Ok.
    """
    header = "📋 **Tropelex — Decision Context**"
    if project:
        header += f" (`{project}`)"

    sections: list[str] = [header, ""]

    # Section 1: Relevant decisions with context
    if analysis.relevant_decisions:
        sections.append("### Relevant Decisions")
        sections.extend(format_decision(d) for d in analysis.relevant_decisions)
        sections.append("")

    # Section 2: Ghost warnings
    if analysis.ghost_warnings:
        sections.append("### Ghost Warnings")
        sections.extend(format_warning(w) for w in analysis.ghost_warnings)
        sections.append("")

    # Section 3: Summary
    summary = generate_comment_summary(
        analysis.relevant_decisions,
        analysis.ghost_warnings,
    )
    sections.append(
        f"---\n*{summary} (relevance: {analysis.relevance_score})*"
    )

    body = "\n".join(sections)

    return Ok(value=PRComment(
        body=body,
        decisions_mentioned=analysis.relevant_decisions,
        ghost_warnings=analysis.ghost_warnings,
        relevance_score=analysis.relevance_score,
        decision_count=len(analysis.relevant_decisions),
        warning_count=len(analysis.ghost_warnings),
    ))
