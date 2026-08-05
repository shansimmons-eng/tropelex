"""
Digital Twin Personas — FastAPI router.

Endpoints for synthesizing and retrieving agent personas from skill graph data.

Mount into the main app:
    from core.personas.router import persona_router
    app.include_router(persona_router)
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.agent_identity import normalize_agent_name
from core.personas import Err, Ok, PersonaError, PersonaSummary, Result
from core.personas.persona_builder import build_persona, suggest_review_focus

logger = logging.getLogger("tropelex.personas")

persona_router = APIRouter(prefix="/api/memory", tags=["personas"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


# ---------------------------------------------------------------------------
# Pydantic response models (API boundary — serialisation layer)
# ---------------------------------------------------------------------------


class PersonaResponse(BaseModel):
    """JSON-serialisable persona summary for API responses."""

    agent_name: str
    strengths: list[str]
    weaknesses: list[str]
    preferred_categories: list[str]
    accuracy_by_category: dict[str, float]
    summary_text: str
    total_sessions: int


class ReviewSuggestionResponse(BaseModel):
    """JSON-serialisable review suggestion for API responses."""

    agent_name: str
    focus_areas: list[str]
    reasoning: str


class PersonaDetailResponse(BaseModel):
    """Full persona detail including review suggestions."""

    persona: PersonaResponse
    review_suggestion: ReviewSuggestionResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_agent_skills(project: str, agent: str | None = None) -> dict[str, Any]:
    """Load agent skill data for a project, or raise 404.

    agent=None returns the project-wide aggregate (unchanged behavior). Pass
    a real agent name to scope "skills"/"sessions" down to that agent's own
    data only, so distinct agents actually get distinct personas.
    """
    from core.agent_skills import AgentSkillGraph

    graph = AgentSkillGraph(str(BASE_DIR))
    skills_file = graph._skills_file(project)
    if not skills_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No skill data found for project '{project}'",
        )
    data = graph._load(project)
    if agent is None:
        return data
    return {
        **data,
        "skills": data.get("skills_by_agent", {}).get(agent, {}),
        "sessions": [s for s in data.get("sessions", []) if s.get("agent", "unspecified") == agent],
    }


def _persona_to_response(persona: PersonaSummary) -> PersonaResponse:
    """Convert PersonaSummary dataclass to Pydantic response model."""
    return PersonaResponse(
        agent_name=persona.agent_name,
        strengths=persona.strengths,
        weaknesses=persona.weaknesses,
        preferred_categories=persona.preferred_categories,
        accuracy_by_category=persona.accuracy_by_category,
        summary_text=persona.summary_text,
        total_sessions=persona.total_sessions,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@persona_router.get("/{project}/personas/{agent}")
async def get_agent_persona(project: str, agent: str) -> dict[str, Any]:
    """Get persona summary for a specific agent in a project.

    Returns the synthesised persona including strengths, weaknesses,
    preferred categories, and a human-readable summary.
    """
    agent = normalize_agent_name(agent)
    try:
        agent_skills = _load_agent_skills(project, agent=agent)
    except HTTPException:
        raise
    except PersonaError as exc:
        logger.error("PersonaError loading skills for '%s/%s': %s", project, agent, exc)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to load skills for '%s/%s': %s", project, agent, exc)
        raise HTTPException(status_code=500, detail=f"Failed to load agent skills: {exc}")

    result = build_persona(agent_skills, agent)

    if isinstance(result, Err):
        if result.code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result.error)
        if result.code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result.error)
        logger.error("Persona build failed for '%s/%s': %s", project, agent, result.error)
        raise HTTPException(status_code=500, detail=result.error)

    persona = result.value
    review = suggest_review_focus(persona)

    return {
        "persona": _persona_to_response(persona).model_dump(),
        "review_suggestion": ReviewSuggestionResponse(
            agent_name=review.agent_name,
            focus_areas=review.focus_areas,
            reasoning=review.reasoning,
        ).model_dump(),
    }


@persona_router.get("/{project}/personas")
async def get_all_personas(project: str) -> dict[str, Any]:
    """Get persona summaries for all real agents recorded in a project.

    One entry per distinct agent (Claude, Gemini, ...) that has actually
    recorded skill outcomes — not a single persona keyed by the project
    name. Falls back to the legacy project-wide aggregate persona only for
    projects that predate agent tagging (no agent has ever been recorded).
    """
    from core.agent_skills import AgentSkillGraph

    try:
        graph = AgentSkillGraph(str(BASE_DIR))
        agent_names = graph.list_agents(project) if graph._skills_file(project).exists() else []
    except Exception as exc:
        logger.error("Failed to list agents for '%s': %s", project, exc)
        agent_names = []

    def _build_entry(agent_skills: dict[str, Any], name: str) -> Result[dict[str, Any]]:
        result = build_persona(agent_skills, name)
        if isinstance(result, Err):
            return result
        persona = result.value
        review = suggest_review_focus(persona)
        return Ok(value={
            "persona": _persona_to_response(persona).model_dump(),
            "review_suggestion": ReviewSuggestionResponse(
                agent_name=review.agent_name,
                focus_areas=review.focus_areas,
                reasoning=review.reasoning,
            ).model_dump(),
        })

    personas: list[dict[str, Any]] = []

    if agent_names:
        for name in agent_names:
            try:
                agent_skills = _load_agent_skills(project, agent=name)
            except HTTPException:
                raise
            except Exception as exc:
                logger.error("Failed to load skills for '%s/%s': %s", project, name, exc)
                continue
            entry = _build_entry(agent_skills, name)
            if isinstance(entry, Err):
                logger.error("Persona build failed for '%s/%s': %s", project, name, entry.error)
                continue
            personas.append(entry.value)
    else:
        # Legacy fallback: no agent-tagged data exists yet, so surface the
        # old project-wide aggregate rather than an empty list.
        try:
            agent_skills = _load_agent_skills(project)
        except HTTPException:
            raise
        except PersonaError as exc:
            logger.error("PersonaError loading skills for '%s': %s", project, exc)
            raise HTTPException(status_code=500, detail=str(exc))
        except Exception as exc:
            logger.error("Failed to load skills for '%s': %s", project, exc)
            raise HTTPException(status_code=500, detail=f"Failed to load agent skills: {exc}")

        entry = _build_entry(agent_skills, project)
        if isinstance(entry, Err):
            logger.error("Persona build failed for '%s': %s", project, entry.error)
            raise HTTPException(status_code=500, detail=entry.error)
        personas.append(entry.value)

    return {
        "project": project,
        "personas": personas,
        "count": len(personas),
    }
