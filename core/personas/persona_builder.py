"""
Persona Builder — pure functions for synthesizing Digital Twin Personas
from AgentSkillGraph data.

All functions are pure (same input → same output, no side effects).
Each function is <50 lines per code-quality standards.
"""

from core.personas import Err, Ok, PersonaSummary, Result, ReviewSuggestion


# Thresholds aligned with AgentSkillGraph._proficiency_label
_EXPERT_MIN_SCORE = 0.7   # "expert" or "proficient" → strength
_NOVICE_MAX_SCORE = 0.4   # "novice" or "learning" → weakness
_MIN_ATTEMPTS = 3          # minimum attempts before a skill is meaningful


def identify_strengths(skills: dict[str, dict]) -> list[str]:
    """Categories where the agent is expert-level (score ≥ 0.7, ≥ 3 attempts).

    Args:
        skills: mapping of category → {score, attempts, successes, failures, ...}

    Returns:
        Sorted list of category names where the agent excels.
    """
    return sorted(
        name
        for name, info in skills.items()
        if info.get("score", 0) >= _EXPERT_MIN_SCORE
        and info.get("attempts", 0) >= _MIN_ATTEMPTS
    )


def identify_weaknesses(skills: dict[str, dict]) -> list[str]:
    """Categories where the agent is novice-level or low accuracy.

    Selects categories with score ≤ 0.4 and at least 3 attempts.

    Args:
        skills: mapping of category → {score, attempts, ...}

    Returns:
        Sorted list of category names where the agent struggles.
    """
    return sorted(
        name
        for name, info in skills.items()
        if info.get("score", 0) <= _NOVICE_MAX_SCORE
        and info.get("attempts", 0) >= _MIN_ATTEMPTS
    )


def build_persona(agent_skills: dict, agent_name: str) -> Result:
    """Synthesize a PersonaSummary from skill graph data.

    Args:
        agent_skills: raw dict from AgentSkillGraph._load(), containing
                      "skills", "sessions", etc.
        agent_name: identifier for this agent (e.g. project name).

    Returns:
        Ok(PersonaSummary) on success, Err on validation failure.
    """
    if not agent_name or not agent_name.strip():
        return Err(error="agent_name is required", code="VALIDATION_ERROR")

    skills = agent_skills.get("skills", {})
    sessions = agent_skills.get("sessions", [])

    if not skills:
        return Ok(value=PersonaSummary(
            agent_name=agent_name,
            strengths=[],
            weaknesses=[],
            preferred_categories=[],
            accuracy_by_category={},
            summary_text=f"{agent_name}: No skill data recorded yet.",
            total_sessions=len(sessions),
        ))

    strengths = identify_strengths(skills)
    weaknesses = identify_weaknesses(skills)

    # Preferred = top 3 categories by score
    ranked = sorted(skills.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)
    preferred = [name for name, _ in ranked[:3]]

    accuracy = {name: round(info.get("score", 0.0), 3) for name, info in skills.items()}

    summary_text = generate_summary_text_raw(
        agent_name, strengths, weaknesses, preferred, accuracy,
    )

    return Ok(value=PersonaSummary(
        agent_name=agent_name,
        strengths=strengths,
        weaknesses=weaknesses,
        preferred_categories=preferred,
        accuracy_by_category=accuracy,
        summary_text=summary_text,
        total_sessions=len(sessions),
    ))


def generate_summary_text(persona: PersonaSummary) -> str:
    """Generate a human-readable summary from a PersonaSummary.

    Example output:
        "auth-agent: Excels at backend, security. Needs improvement in ui.
         Prefers working on backend, security, testing."
    """
    return generate_summary_text_raw(
        persona.agent_name,
        persona.strengths,
        persona.weaknesses,
        persona.preferred_categories,
        persona.accuracy_by_category,
    )


def generate_summary_text_raw(
    agent_name: str,
    strengths: list[str],
    weaknesses: list[str],
    preferred: list[str],
    accuracy: dict[str, float],
) -> str:
    """Internal helper: build summary text from component parts."""
    parts: list[str] = []

    if strengths:
        parts.append(f"Excels at {', '.join(strengths)}.")
    if weaknesses:
        parts.append(f"Needs improvement in {', '.join(weaknesses)}.")
    if preferred:
        parts.append(f"Prefers working on {', '.join(preferred)}.")

    # Tendency hint for lowest-scoring categories
    low = sorted(accuracy.items(), key=lambda kv: kv[1])[:2]
    if low and low[0][1] < 0.5:
        cats = ", ".join(name for name, _ in low)
        parts.append(f"Tends to struggle with {cats}.")

    return f"{agent_name}: {' '.join(parts)}" if parts else f"{agent_name}: No significant patterns detected."


def suggest_review_focus(persona: PersonaSummary) -> ReviewSuggestion:
    """Suggest what to focus on when reviewing this agent's work.

    Prioritizes known weaknesses, then borderline-proficiency categories.
    """
    focus_areas: list[str] = list(persona.weaknesses)

    # Borderline: 0.4 < score < 0.6 — not clearly good or bad
    borderline = [
        cat for cat, score in persona.accuracy_by_category.items()
        if 0.4 < score < 0.6 and cat not in focus_areas
    ]
    focus_areas.extend(borderline[:2])

    # Fallback if nothing to flag
    if not focus_areas:
        focus_areas = list(persona.preferred_categories[:2]) or ["general quality"]

    reasoning_parts: list[str] = []
    if persona.weaknesses:
        reasoning_parts.append(f"Known weaknesses in {', '.join(persona.weaknesses)}")
    if borderline:
        reasoning_parts.append(f"Borderline proficiency in {', '.join(borderline[:2])}")
    if not reasoning_parts:
        reasoning_parts.append("No significant weaknesses; focus on consistency and edge cases")

    return ReviewSuggestion(
        agent_name=persona.agent_name,
        focus_areas=focus_areas[:5],
        reasoning="; ".join(reasoning_parts) + ".",
    )
