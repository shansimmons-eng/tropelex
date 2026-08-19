"""
RepoSeek — FastAPI router.

Mount into the main app:
    from core.reposeek.router import router as reposeek_router
    app.include_router(reposeek_router)
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from core.reposeek.github_client import search_github
from core.reposeek.models import SeekQuery
from core.reposeek.scoring import score_results
from core.result import Err

logger = logging.getLogger("reposeek.router")

router = APIRouter(prefix="/api/reposeek", tags=["reposeek"])

_MAX_PROJECT_NAME_LEN = 64
_README_MAX_LINES = 500


def _validate_project(name: str) -> str:
    """Validate and return the trimmed project name.

    Raises HTTPException 422 for empty or overly long names.
    """
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name must not be empty")
    if len(name) > _MAX_PROJECT_NAME_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"Project name must be ≤{_MAX_PROJECT_NAME_LEN} characters",
        )
    return name


def _load_profile_from_memory(project: str) -> dict | None:
    """Read project data from Tropelex MemoryManager.

    Returns the profile dict (tech_stack, description, patterns) or
    None if the project has no meaningful memory data.
    """
    from core.memory.manager import MemoryManager

    mm = MemoryManager()
    memory = mm.get_project_memory(project)
    # A newly-created empty memory has no real tech_stack or description
    if memory.get("tech_stack") or memory.get("description"):
        return {
            "tech_stack": memory.get("tech_stack", []),
            "description": memory.get("description", ""),
            "patterns": memory.get("patterns", []),
        }
    return None


async def _fetch_readme_as_profile(project: str) -> dict | None:
    """Fall back to extracting a profile from the repo's README via GitHub API.

    Returns a synthetic profile dict or None on failure.
    """
    import httpx

    url = f"https://api.github.com/repos/{project}/readme"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers={"Accept": "application/vnd.github.raw+json"},
            )
            if resp.status_code != 200:
                return None
            lines = resp.text.splitlines()[:_README_MAX_LINES]
            text = "\n".join(lines)
            return {
                "tech_stack": [],
                "description": text[:500],
                "patterns": [],
            }
    except (httpx.ConnectError, httpx.TimeoutException):
        return None


def _extract_search_terms(description: str, max_words: int = 3) -> str:
    """Extract the most meaningful keywords from a description.

    Drops stop-words, short tokens, verbs, and common filler.
    Keeps up to *max_words* terms — GitHub search treats each word as required,
    so fewer words = more results. 3 words is the sweet spot.
    """
    stop = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "as", "be", "are", "was",
        "were", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "can", "shall",
        "that", "this", "these", "those", "not", "no", "nor", "if", "then",
        "so", "up", "out", "its", "into", "across", "about", "than", "via",
        "also", "just", "use", "used", "using", "all", "each", "every",
        "built", "based", "using", "like", "well", "new", "fast", "simple",
        "radical", "veracity", "principles", "next-gen", "generation",
    }
    words = description.split()
    keywords = []
    for w in words:
        clean = w.lower().strip(".,;:!?\"'()-")
        if len(clean) <= 2:
            continue
        if clean in stop:
            continue
        # Skip verbs/adj suffixes
        if len(clean) > 4 and (clean.endswith("ing") or clean.endswith("ed") or clean.endswith("es")):
            if clean not in {"agents", "models", "tools", "systems", "plugins", "tokens", "mirrors", "simulators"}:
                continue
        keywords.append(clean)
    return " ".join(keywords[:max_words])


async def _do_scan(project: str) -> dict:
    """Core scan logic — load profile, search GitHub, score, return."""
    profile = _load_profile_from_memory(project)
    if not profile:
        profile = await _fetch_readme_as_profile(project)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

    # If memory has tech_stack but no description, try to get one from the README
    if not profile.get("description") and profile.get("tech_stack"):
        readme_profile = await _fetch_readme_as_profile(project)
        if readme_profile and readme_profile.get("description"):
            profile["description"] = readme_profile["description"]

    search_terms = _extract_search_terms(profile.get("description", ""))
    tech_stack = profile.get("tech_stack", [])

    # Build the search query: prefer description keywords, fall back to tech stack
    if search_terms:
        query_text = search_terms
    elif tech_stack:
        # Use the most distinctive tech items (skip very generic ones)
        generic = {"python", "javascript", "html", "css", "sql"}
        distinct = [t for t in tech_stack if t.lower() not in generic]
        query_text = " ".join(distinct[:5]) if distinct else " ".join(tech_stack[:3])
    else:
        query_text = "AI tools"

    query = SeekQuery(
        query=query_text,
        language=tech_stack[0] if tech_stack else None,
        topics=tech_stack,
    )

    result = await search_github(query)
    if isinstance(result, Err):
        if result.code == "RATE_LIMITED":
            raise HTTPException(
                status_code=503,
                detail="GitHub API rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        raise HTTPException(status_code=500, detail=result.error)

    scored = score_results(result.value, profile)
    return {"repos": [r.to_dict() for r in scored]}


@router.get("/scan")
async def scan(project: str = Query(..., description="Project name to scan for")):
    """Search GitHub for repos matching a Tropelex project profile.

    Reads project data from memory (tech_stack, description, patterns),
    falls back to README extraction, then scores results by similarity.
    """
    project = _validate_project(project)
    return await _do_scan(project)
