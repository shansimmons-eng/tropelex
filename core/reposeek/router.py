"""
RepoSeek — FastAPI router.

Mount into the main app:
    from core.reposeek.router import router as reposeek_router
    app.include_router(reposeek_router)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core.reposeek.github_client import search_github
from core.reposeek.models import RepoResult, SeekQuery
from core.reposeek.scoring import score_results
from core.reposeek.storage import RepoSeekStore
from core.result import Err

logger = logging.getLogger("reposeek.router")

router = APIRouter(prefix="/api/reposeek", tags=["reposeek"])

_MAX_PROJECT_NAME_LEN = 64
_README_MAX_LINES = 500
_MAX_BATCH_RESULTS = 20
_MAX_ITEM_SCANS_PER_BATCH = 3
_MAX_SCAN_DEPTH = 2  # 0=initial, 1=first item-scan round, 2=second and final


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ItemScanRequest(BaseModel):
    item_url: str


class ExcludeRequest(BaseModel):
    url: str
    title: str = ""


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

    # Exclude list applies to every scan, not just item-scans derived from a
    # batch -- excluding a repo is meant to stop seeing it at all, not just
    # in child batches.
    store = RepoSeekStore()
    excluded = store.excluded_urls(project)
    filtered = [r for r in scored if r.url not in excluded][:_MAX_BATCH_RESULTS]

    batch = {
        "id": store.new_batch_id(),
        "created_at": _now_iso(),
        "depth": 0,
        "parent_batch_id": None,
        "source_item": None,
        "query": query.to_dict(),
        "results": [r.to_dict() for r in filtered],
        "item_scans_used": 0,
    }
    store.add_batch(project, batch)

    return {"batch_id": batch["id"], "depth": 0, "repos": batch["results"]}


def _profile_from_repo_result(repo: RepoResult) -> dict:
    """Build a profile dict (same shape _load_profile_from_memory returns)
    directly from an already-fetched search result -- no README fetch
    needed, the result already carries its own description."""
    return {
        "tech_stack": [repo.language] if repo.language else [],
        "description": repo.description or "",
        "patterns": [],
    }


@router.get("/scan")
async def scan(project: str = Query(..., description="Project name to scan for")):
    """Search GitHub for repos matching a Tropelex project profile.

    Reads project data from memory (tech_stack, description, patterns),
    falls back to README extraction, then scores results by similarity.
    Persists the result as a new depth-0 batch.
    """
    project = _validate_project(project)
    return await _do_scan(project)


@router.post("/{project}/batches/{batch_id}/items/scan")
async def scan_item(project: str, batch_id: str, body: ItemScanRequest):
    """Profile a single result from an existing batch as if it were its
    own project, search GitHub from that profile, and persist the result
    as a new child batch.

    Bounded on purpose: at most 3 of these per parent batch (width), at
    most 2 rounds deep total (depth 0=initial, 1, 2 — depth 2 is
    terminal). A search that comes back empty after exclude/parent-dedup
    filtering is a normal stopping point, not an error -- the batch is
    still created and returned, just with zero results.
    """
    project = _validate_project(project)
    store = RepoSeekStore()

    batch = store.get_batch(project, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found for project '{project}'")

    if batch.get("depth", 0) >= _MAX_SCAN_DEPTH:
        raise HTTPException(
            status_code=409,
            detail=f"Max scan depth ({_MAX_SCAN_DEPTH}) reached for this batch -- no further item scans allowed.",
        )

    if batch.get("item_scans_used", 0) >= _MAX_ITEM_SCANS_PER_BATCH:
        raise HTTPException(
            status_code=409,
            detail=f"Max item scans ({_MAX_ITEM_SCANS_PER_BATCH}) already used for this batch.",
        )

    item = next((r for r in batch.get("results", []) if r.get("url") == body.item_url), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item '{body.item_url}' not found in batch '{batch_id}'")

    repo = RepoResult.from_dict(item)
    profile = _profile_from_repo_result(repo)

    search_terms = _extract_search_terms(profile.get("description", ""))
    tech_stack = profile.get("tech_stack", [])
    # Unlike _do_scan's "AI tools" catch-all (a project-wide default that
    # makes no sense here), the item itself is always a valid fallback
    # query -- its own owner/repo title.
    query_text = search_terms or (tech_stack[0] if tech_stack else repo.title)

    query = SeekQuery(
        query=query_text,
        language=tech_stack[0] if tech_stack else None,
        topics=tech_stack,
    )

    result = await search_github(query)
    if isinstance(result, Err):
        # Don't burn an item-scan slot on a transient API failure -- only
        # a completed search (even an empty one) counts against the cap.
        if result.code == "RATE_LIMITED":
            raise HTTPException(
                status_code=503,
                detail="GitHub API rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        raise HTTPException(status_code=500, detail=result.error)

    scored = score_results(result.value, profile)

    excluded = store.excluded_urls(project)
    parent_urls = {r.get("url") for r in batch.get("results", [])}
    blocked = excluded | parent_urls
    filtered = [r for r in scored if r.url not in blocked][:_MAX_BATCH_RESULTS]

    store.bump_item_scans_used(project, batch_id)

    new_batch = {
        "id": store.new_batch_id(),
        "created_at": _now_iso(),
        "depth": batch["depth"] + 1,
        "parent_batch_id": batch_id,
        "source_item": {"title": repo.title, "url": repo.url},
        "query": query.to_dict(),
        "results": [r.to_dict() for r in filtered],
        "item_scans_used": 0,
    }
    store.add_batch(project, new_batch)

    return {
        "batch_id": new_batch["id"],
        "depth": new_batch["depth"],
        "parent_batch_id": batch_id,
        "source_item": new_batch["source_item"],
        "item_scans_used": new_batch["item_scans_used"],
        "repos": new_batch["results"],
    }


@router.post("/{project}/batches/{batch_id}/items/research")
async def research_item(project: str, batch_id: str, body: ItemScanRequest):
    """Run a lightweight Deep Research pass on one item from an existing
    batch and import the findings as citations tagged with that repo
    (wishlist #81) -- distinct from Scan Item (which searches GitHub again
    for more similar repos): this searches the wider web for the repo
    itself, README/discussion/context Repo Seek's own GitHub Search calls
    never surface.

    Not bounded by scan depth/width like Scan Item -- there's no batch
    tree here, this is a one-shot side-effect (citations get written),
    not a new lineage node. max_steps kept low (2) since this is meant to
    stay "lightweight" per the wishlist item, not a full Deep Research run.
    """
    project = _validate_project(project)
    store = RepoSeekStore()

    batch = store.get_batch(project, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found for project '{project}'")

    item = next((r for r in batch.get("results", []) if r.get("url") == body.item_url), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item '{body.item_url}' not found in batch '{batch_id}'")

    repo = RepoResult.from_dict(item)
    topic = f"{repo.title}: {repo.description}" if repo.description else repo.title

    from core.tropebook.deep_research import DeepResearchImporter
    from core.tropebook.tropebook import SourceType
    from core.tropebook.web.server import get_tropebook
    from core.tropebook.web_research_agent import run_web_deep_research
    from core.tropebook.web_researcher_client import WebResearcherError

    try:
        result = await run_web_deep_research(topic, max_steps=2, project=project)
    except WebResearcherError as exc:
        logger.error("research_item deep research failed for %r: %s", topic, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    importer = DeepResearchImporter(get_tropebook())
    sources = importer.parse_markdown_research(result["report_markdown"])
    repo_tag = f"repo:{repo.title}"
    for source in sources:
        if repo_tag not in source.topics:
            source.topics.append(repo_tag)
    imported = importer.import_sources(
        sources, add_relationships=False, source_type=SourceType.WEB_RESEARCHER_MCP
    )

    return {
        "repo": {"title": repo.title, "url": repo.url},
        "topic": topic,
        "sources_found": len(sources),
        "imported": imported,
    }


@router.post("/{project}/exclude")
async def add_exclude(project: str, body: ExcludeRequest):
    """Permanently exclude a repo from future scans for this project."""
    project = _validate_project(project)
    store = RepoSeekStore()
    store.exclude_add(project, body.url, body.title)
    items = store.exclude_list(project)
    return {"excluded_count": len(items)}


@router.delete("/{project}/exclude")
async def remove_exclude(project: str, url: str = Query(..., description="URL to remove from the exclude list")):
    """Undo an exclude -- the repo can appear in scans again."""
    project = _validate_project(project)
    store = RepoSeekStore()
    if not store.exclude_remove(project, url):
        raise HTTPException(status_code=404, detail=f"'{url}' was not on the exclude list")
    items = store.exclude_list(project)
    return {"excluded_count": len(items)}


@router.get("/{project}/exclude")
async def list_exclude(project: str):
    """The project's current exclude list."""
    project = _validate_project(project)
    store = RepoSeekStore()
    items = store.exclude_list(project)
    return {"excluded": items, "count": len(items)}


@router.get("/{project}/batches")
async def list_batches(project: str):
    """Summary of every batch for this project -- powers the lineage
    breadcrumb strip. Full results are fetched per-batch via
    GET /{project}/batches/{batch_id}, not included here."""
    project = _validate_project(project)
    store = RepoSeekStore()
    batches = store.list_batches(project)
    summaries = [
        {
            "id": b.get("id"),
            "depth": b.get("depth", 0),
            "parent_batch_id": b.get("parent_batch_id"),
            "source_item": b.get("source_item"),
            "created_at": b.get("created_at"),
            "result_count": len(b.get("results", [])),
            "item_scans_used": b.get("item_scans_used", 0),
        }
        for b in batches
    ]
    return {"batches": summaries, "count": len(summaries)}


@router.get("/{project}/batches/{batch_id}")
async def get_batch_detail(project: str, batch_id: str):
    """Full detail for one batch, including its results -- used to
    navigate back to an ancestor via the lineage breadcrumb without
    re-scanning."""
    project = _validate_project(project)
    store = RepoSeekStore()
    batch = store.get_batch(project, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found for project '{project}'")
    return batch


@router.get("/{project}/export")
async def export_batches(
    project: str,
    format: str = Query("json", pattern="^(json|markdown)$"),
    batch_id: str | None = Query(None, description="Export just this batch; omit for every batch"),
):
    """Export one batch or the project's full scan history."""
    project = _validate_project(project)
    store = RepoSeekStore()

    if batch_id:
        batch = store.get_batch(project, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found for project '{project}'")
        batches = [batch]
    else:
        batches = store.list_batches(project)

    if format == "json":
        return {"project": project, "batches": batches}

    lines = [f"# RepoSeek Export — {project}", ""]
    for b in batches:
        source_item = b.get("source_item")
        lineage = (
            f"Derived from: {source_item['title']} (round {b.get('depth', 0)})"
            if source_item else "Initial scan"
        )
        lines.append(f"## Batch {b.get('id')} — depth {b.get('depth', 0)}")
        lines.append(lineage)
        lines.append("")
        results = b.get("results", [])
        if not results:
            lines.append("_No results._")
        for r in results:
            lines.append(
                f"- [{r.get('title')}]({r.get('url')}) — "
                f"{r.get('language') or 'unknown'}, {r.get('stars', 0)} stars, "
                f"score {r.get('similarity_score', 0):.2f}"
            )
        lines.append("")

    return PlainTextResponse("\n".join(lines), media_type="text/markdown")
