"""
Tropelex Web API - FastAPI server for Tropelex web interface
Linux-native, portable — no hardcoded paths.
"""

import os
import logging
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# --- .env loader (no dependency on python-dotenv) ---
_env_path = Path(__file__).parent.parent.parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and "=" in _line and not _line.startswith("#"):
            _key, _val = _line.split("=", 1)
            _val = _val.strip().strip('"').strip("'")  # strip quotes
            os.environ.setdefault(_key.strip(), _val)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tropelex")

app = FastAPI(title="Tropelex API", version="1.1.0")

# CORS — localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8765", "http://127.0.0.1:8765"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Paths (fully computed, no hardcoding) ---
SCRIPT_DIR = Path(__file__).parent
WEB_DIR = SCRIPT_DIR.parent
CORE_DIR = WEB_DIR.parent
BASE_DIR = CORE_DIR.parent
UI_DIR = BASE_DIR / "UI"
UI_DASHBOARD_PATH = UI_DIR / "animated_tropebook_dashboard" / "code.html"

# Debug: print paths on startup
print(f"[TROPELEX] BASE_DIR: {BASE_DIR}")
print(f"[TROPELEX] UI_DASHBOARD_PATH: {UI_DASHBOARD_PATH}")
print(f"[TROPELEX] File exists: {UI_DASHBOARD_PATH.exists()}")

try:
    app.mount(
        "/static", StaticFiles(directory=str(SCRIPT_DIR / "static")), name="static"
    )
except Exception as exc:
    logger.warning("Static files not mounted: %s", exc)


# --- Request body models ---
class CitationCreate(BaseModel):
    title: str = Field(..., max_length=500)
    url: str = Field(..., max_length=2000)
    summary: str = Field("", max_length=5000)
    source: str = Field("", max_length=200)
    tags: List[str] = Field(default_factory=list, max_length=20)
    entities: List[str] = Field(default_factory=list, max_length=20)


class CitationUpdate(BaseModel):
    summary: Optional[str] = Field(None, max_length=5000)
    tags: Optional[List[str]] = Field(None, max_length=20)
    entities: Optional[List[str]] = Field(None, max_length=20)


class CompressRequest(BaseModel):
    prompt: str = Field(..., max_length=8000)
    level: int = Field(2, ge=1, le=3)


class LinkRequest(BaseModel):
    source_url: str = Field(..., max_length=2000)
    target_url: str = Field(..., max_length=2000)
    relationship: str = Field(..., max_length=100)


class ImportRequest(BaseModel):
    data: Dict[str, Any]
    source_type: str = "deep_research"


class MemoryProjectCreate(BaseModel):
    project_name: str = Field(..., max_length=100, pattern=r"^[a-zA-Z0-9_\-]+$")


class MemoryUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=1000)
    tech_stack: Optional[List[str]] = Field(None, max_length=50)
    preferences: Optional[Dict[str, Any]] = None


# --- App state (lazy init) ---
_state: Dict[str, Any] = {"tropebook": None, "memory_manager": None}


def get_tropebook():
    if _state["tropebook"] is None:
        from core.tropebook import Tropebook

        _state["tropebook"] = Tropebook(
            storage_path=str(BASE_DIR / "memory" / "tropebook")
        )
    return _state["tropebook"]


def get_memory_manager():
    if _state["memory_manager"] is None:
        from core.memory.manager import MemoryManager

        _state["memory_manager"] = MemoryManager(str(BASE_DIR))
    return _state["memory_manager"]


def _sanitise_project(name: str) -> str:
    """Strip path components to prevent traversal."""
    return Path(name).name


# ============================
#  Routes — static / UI
# ============================


@app.get("/")
async def root():
    from fastapi.responses import HTMLResponse

    with open(UI_DASHBOARD_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/hijacker")
@app.get("/compressor")
@app.get("/prompt-lab")
async def hijacker():
    """Redirect to main dashboard Prompt Lab section."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/#section-pipeline", status_code=302)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.1.0"}


@app.get("/api/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables (localhost only)."""
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    return {
        "openai_key_present": bool(openai_key),
        "openai_key_valid": openai_key.startswith("sk-") if openai_key else False,
        "openai_key_preview": openai_key[:10] + "..." if openai_key else None,
        "brave_key_present": bool(brave_key),
        "env_file_path": str(_env_path),
        "env_file_exists": _env_path.exists(),
    }


# ============================
#  Citations — NOTE: specific
#  routes BEFORE parameterised
# ============================


@app.delete("/api/citations/clear")
async def clear_all_citations():
    """Wipe all citations and graph."""
    import traceback

    try:
        tb = get_tropebook()
        tb.clear()
        return {"cleared": True}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}, 500


@app.get("/api/citations")
async def list_citations(tag: Optional[str] = None, source: Optional[str] = None):
    tb = get_tropebook()
    if tag:
        citations = tb.find_by_tag(tag)
    elif source:
        from core.tropebook import SourceType

        source_type = (
            SourceType(source)
            if source in [s.value for s in SourceType]
            else SourceType.MANUAL
        )
        citations = tb.find_by_source(source_type)
    else:
        citations = list(tb.citations.values())
    return {
        "citations": [c.to_dict(id=cid) for cid, c in tb.citations.items()],
        "count": len(citations),
    }


@app.post("/api/citations")
async def create_citation(citation: CitationCreate):
    tb = get_tropebook()
    cid = tb.add(
        title=citation.title,
        url=citation.url,
        summary=citation.summary,
        source=citation.source,
        tags=citation.tags,
        entities=citation.entities,
    )
    return {"id": cid, "citation": tb.get(cid).to_dict()}


@app.get("/api/citations/{cid}")
async def get_citation(cid: str):
    tb = get_tropebook()
    citation = tb.get(cid)
    if not citation:
        raise HTTPException(status_code=404, detail="Citation not found")
    return citation.to_dict()


@app.patch("/api/citations/{cid}")
async def update_citation(cid: str, update: CitationUpdate):
    tb = get_tropebook()
    updated = tb.update(cid, **update.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Citation not found")
    return {"updated": True}


@app.delete("/api/citations/{cid}")
async def delete_citation(cid: str):
    tb = get_tropebook()
    if not tb.delete(cid):
        raise HTTPException(status_code=404, detail="Citation not found")
    return {"deleted": True}


# ============================
#  Search / tags / entities
# ============================


@app.get("/api/search")
async def search_citations(
    q: str = Query(..., min_length=1, max_length=200), limit: int = Query(20, le=100)
):
    tb = get_tropebook()
    results = tb.search(q, limit)
    return {"results": [r.to_dict() for r in results], "count": len(results)}


@app.get("/api/tags")
async def list_tags():
    tb = get_tropebook()
    return {"tags": list(tb._index["by_tag"].keys())}


@app.get("/api/entities")
async def list_entities():
    tb = get_tropebook()
    return {"entities": list(tb._index["by_entity"].keys())}


@app.get("/api/stats")
async def get_stats():
    tb = get_tropebook()
    return tb.stats()


@app.post("/api/import")
async def import_sources(import_req: ImportRequest):
    tb = get_tropebook()
    count = tb.import_from_deep_research(import_req.data)
    return {"imported": count}


@app.get("/api/export")
async def export_all():
    tb = get_tropebook()
    return tb.export_json()


@app.post("/api/link")
async def link_citations(req: LinkRequest):
    tb = get_tropebook()
    tb.add_relationship(req.source_url, req.target_url, req.relationship)
    return {"linked": True}


# ============================
#  Memory — specific BEFORE
#  parameterised
# ============================


@app.delete("/api/memory/reset")
async def reset_all_memory():
    mm = get_memory_manager()
    for project_file in mm.memory_dir.glob("*.json"):
        project_file.unlink()
    return {"reset": True}


@app.get("/api/memory")
async def list_memory_projects():
    mm = get_memory_manager()
    return {"projects": [{"name": p} for p in mm.list_projects()]}


@app.post("/api/memory")
async def create_memory_project(data: MemoryProjectCreate):
    mm = get_memory_manager()
    name = _sanitise_project(data.project_name)
    memory = mm.get_project_memory(name)
    mm.save_project_memory(name, memory)
    return {"created": True, "project": name}


@app.get("/api/memory/{project}")
async def get_memory_project(project: str):
    project = _sanitise_project(project)
    mm = get_memory_manager()
    return mm.get_project_memory(project)


@app.patch("/api/memory/{project}")
async def update_memory_project(project: str, data: MemoryUpdate):
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    payload = data.model_dump(exclude_none=True)
    # Whitelist-only merge
    if "description" in payload:
        memory["description"] = payload["description"]
    if "tech_stack" in payload:
        memory["tech_stack"] = payload["tech_stack"]
    if "preferences" in payload and isinstance(payload["preferences"], dict):
        memory.setdefault("preferences", {}).update(payload["preferences"])
    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    mm.save_project_memory(project, memory)
    return {"updated": True}


class DecisionCreate(BaseModel):
    decision: str = Field(..., max_length=500)
    context: str = Field("", max_length=1000)


class SessionCreate(BaseModel):
    summary: str = Field(..., max_length=2000)


@app.post("/api/memory/{project}/decisions")
async def add_decision(project: str, data: DecisionCreate):
    """Add a decision to project memory."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    decision_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": data.decision,
        "context": data.context,
    }

    memory.setdefault("decisions", []).append(decision_entry)
    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    mm.save_project_memory(project, memory)
    return {"added": True, "decision": decision_entry}


@app.post("/api/memory/{project}/sessions")
async def add_session(project: str, data: SessionCreate):
    """Add a session summary and trigger pattern learning."""
    project = _sanitise_project(project)
    mm = get_memory_manager()

    try:
        from core.learner.learner import PatternLearner

        learner = PatternLearner(mm)
        analysis = learner.analyze_session(project, data.summary)
        learner.update_project_from_session(project, analysis)

        return {
            "added": True,
            "insights": analysis.get("insights", []),
            "categories": analysis.get("categories", []),
        }
    except Exception as e:
        logger.error(f"Session analysis failed: {e}")
        # Still add the session even if analysis fails
        memory = mm.get_project_memory(project)
        session_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "session_summary",
            "summary": data.summary,
        }
        memory.setdefault("session_history", []).append(session_entry)
        memory["last_updated"] = datetime.now(timezone.utc).isoformat()
        mm.save_project_memory(project, memory)
        return {"added": True, "error": str(e)}


class QuickCapture(BaseModel):
    text: str = Field(..., max_length=1000)
    type: str = Field("thought", max_length=50)  # thought, decision, note
    project: Optional[str] = None


@app.post("/api/capture")
async def quick_capture(data: QuickCapture, project_name: Optional[str] = None):
    """Quick capture endpoint - can capture to any project without selecting it first."""
    target_project = data.project or project_name or "inbox"

    mm = get_memory_manager()
    memory = mm.get_project_memory(target_project)

    timestamp = datetime.now(timezone.utc).isoformat()

    if data.type == "decision":
        memory.setdefault("decisions", []).append(
            {
                "timestamp": timestamp,
                "decision": data.text,
                "context": "Quick capture",
                "source": "quick",
            }
        )
    else:
        memory.setdefault("quick_captures", []).append(
            {"timestamp": timestamp, "text": data.text, "type": data.type}
        )

    memory["last_updated"] = timestamp
    mm.save_project_memory(target_project, memory)

    return {"captured": True, "project": target_project, "type": data.type}


@app.get("/api/memory/{project}/insights")
async def get_project_insights(project: str):
    """Get time-based insights and suggestions for a project."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    # Analyze day-of-week patterns
    day_counts = defaultdict(int)
    category_counts = defaultdict(int)

    for session in memory.get("session_history", []):
        if "day" in session:
            day_counts[session["day"]] += 1
        if "insights" in session:
            for insight in session["insights"]:
                for cat in ["ui", "backend", "bug", "architecture", "performance"]:
                    if cat in insight.lower():
                        category_counts[cat] += 1

    # Find best day
    best_day = max(day_counts.items(), key=lambda x: x[1])[0] if day_counts else None

    # Suggest next based on patterns
    suggestions = []
    if category_counts:
        top_cat = max(category_counts.items(), key=lambda x: x[1])[0]
        suggestions.append(f"You often work on {top_cat} - continue building momentum")

    if best_day:
        suggestions.append(f"Your most productive day is {best_day}s")

    # Similar project suggestions based on tech stack
    project_tech = set(memory.get("tech_stack", []))

    return {
        "best_day": best_day,
        "day_counts": dict(day_counts),
        "category_counts": dict(category_counts),
        "suggestions": suggestions,
        "total_sessions": len(memory.get("session_history", [])),
        "total_decisions": len(memory.get("decisions", [])),
    }


# ============================
#  Patterns (live from learner)
# ============================


@app.get("/api/patterns")
async def get_patterns(project: Optional[str] = None):
    mm = get_memory_manager()
    try:
        from core.learner.learner import PatternLearner

        learner = PatternLearner(mm)
        if project:
            patterns = learner.get_common_patterns(_sanitise_project(project))
            suggestions = learner.suggest_next_steps(_sanitise_project(project))
        else:
            # Aggregate across all projects
            patterns = []
            suggestions = []
            for proj in mm.list_projects():
                patterns.extend(learner.get_common_patterns(proj))
                suggestions.extend(learner.suggest_next_steps(proj))
        return {"patterns": patterns, "suggestions": suggestions}
    except Exception as exc:
        logger.warning("Patterns unavailable: %s", exc)
        return {"patterns": [], "suggestions": []}


@app.get("/api/projects")
async def list_projects():
    mm = get_memory_manager()
    return {"projects": mm.list_projects()}


@app.post("/api/analyze/decisions")
async def detect_decisions(data: Dict[str, str]):
    """Analyze text to detect potential decisions worth recording."""
    mm = get_memory_manager()
    try:
        from core.learner.learner import PatternLearner

        learner = PatternLearner(mm)
        text = data.get("text", "")
        if not text:
            return {"detected": [], "message": "No text provided"}
        detected = learner.detect_decisions(text)
        return {"detected": detected}
    except Exception as exc:
        logger.warning("Decision detection failed: %s", exc)
        return {"detected": [], "error": str(exc)}


@app.get("/api/memory/{project}/similar")
async def get_similar_projects(project: str):
    """Get projects with similar tech stacks or patterns."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    try:
        from core.learner.learner import PatternLearner

        learner = PatternLearner(mm)
        similar = learner.get_similar_projects(project)
        return {"similar": similar}
    except Exception as exc:
        logger.warning("Similar projects lookup failed: %s", exc)
        return {"similar": [], "error": str(exc)}


@app.get("/api/memory/{project}/suggestions")
async def get_project_suggestions(project: str):
    """Get next-step suggestions for a project based on patterns."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    try:
        from core.learner.learner import PatternLearner

        learner = PatternLearner(mm)
        suggestions = learner.suggest_next_steps(project)
        return {"suggestions": suggestions}
    except Exception as exc:
        logger.warning("Suggestions unavailable: %s", exc)
        return {"suggestions": []}


# ============================
#  Ollama Integration (future)
# ============================
#  Compression + LLM backends
# ============================


@app.get("/api/backends")
async def get_backends():
    """Report which LLM backends are available."""
    from core.llm import available_backends

    return await available_backends()


@app.post("/api/compress")
async def compress_prompt(req: CompressRequest):
    from core.llm import compress as llm_compress

    result = await llm_compress(req.prompt)
    compressed = result["compressed"]
    return {
        "compressed": compressed,
        "backend": result["backend"],
        "error": result.get("error"),
        "original_length": len(req.prompt),
        "compressed_length": len(compressed),
        "saved_pct": round((1 - len(compressed) / max(len(req.prompt), 1)) * 100, 1),
    }


class ApiKeyRequest(BaseModel):
    key: str = Field(..., pattern=r"^[A-Z_]+$", max_length=64)
    value: str = Field(..., max_length=512)


@app.post("/api/settings/apikey")
async def save_api_key(req: ApiKeyRequest):
    """Write an API key to the .env file (localhost only)."""
    # Only allow known safe key names
    ALLOWED_KEYS = {"OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY", "ANTHROPIC_API_KEY"}
    if req.key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Key '{req.key}' not allowed")

    env_path = BASE_DIR / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []

    # Update existing line or append
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{req.key}=") or line.startswith(f"{req.key} ="):
            new_lines.append(f"{req.key}={req.value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{req.key}={req.value}")

    env_path.write_text("\n".join(new_lines) + "\n")

    # Also set in current process so it takes effect without restart
    os.environ[req.key] = req.value
    logger.info("API key %s updated", req.key)
    return {
        "saved": True,
        "note": "Key applied immediately; also written to .env for persistence",
    }


# ============================
#  Semantic Search
# ============================


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., max_length=1000)
    top_k: int = Field(10, ge=1, le=50)
    min_score: float = Field(0.5, ge=0.0, le=1.0)
    scope: str = Field("citations", pattern=r"^(citations|memory|all)$")


def _get_embed_store(scope: str = "citations"):
    from core.embeddings import EmbeddingStore

    return EmbeddingStore(str(BASE_DIR / "memory" / "embeddings" / f"{scope}.json"))


@app.post("/api/semantic-search")
async def semantic_search(req: SemanticSearchRequest):
    from core.llm import embed_one

    vec = await embed_one(req.query)
    if vec is None:
        raise HTTPException(
            status_code=503, detail="Embeddings unavailable — configure OPENAI_API_KEY"
        )
    store = _get_embed_store(req.scope)
    results = store.search(vec, top_k=req.top_k, min_score=req.min_score)
    return {"results": results, "count": len(results), "query": req.query}


@app.post("/api/citations/{cid}/embed")
async def embed_citation(cid: str):
    """Generate and store embedding for a citation."""
    from core.llm import embed_one

    tb = get_tropebook()
    citation = tb.get(cid)
    if not citation:
        raise HTTPException(status_code=404, detail="Citation not found")
    text = f"{citation.title}. {citation.summary}. Tags: {', '.join(citation.tags)}"
    vec = await embed_one(text)
    if vec is None:
        raise HTTPException(status_code=503, detail="Embeddings unavailable")
    store = _get_embed_store("citations")
    store.put(cid, text, vec, meta={"title": citation.title, "url": citation.url})
    return {"embedded": True, "id": cid}


@app.post("/api/embed-all")
async def embed_all_citations():
    """Batch embed all citations that don't have vectors yet."""
    from core.llm import embed

    tb = get_tropebook()
    store = _get_embed_store("citations")
    to_embed = [(cid, c) for cid, c in tb.citations.items() if not store.has(cid)]
    if not to_embed:
        return {"embedded": 0, "message": "All citations already embedded"}
    texts = [f"{c.title}. {c.summary}. Tags: {', '.join(c.tags)}" for _, c in to_embed]
    vecs = await embed(texts)
    if vecs is None:
        raise HTTPException(status_code=503, detail="Embeddings unavailable")
    for (cid, c), vec in zip(to_embed, vecs):
        store.put(cid, texts[0], vec, meta={"title": c.title, "url": c.url})
    return {"embedded": len(to_embed)}


# ============================
#  Git Integration
# ============================


class GitSyncRequest(BaseModel):
    repo_path: str = Field(..., max_length=500)
    project: str = Field(..., max_length=100)


@app.post("/api/git/sync")
async def git_sync(req: GitSyncRequest):
    from core.git_integration import sync_repo_to_memory

    mm = get_memory_manager()
    result = await sync_repo_to_memory(
        req.repo_path, _sanitise_project(req.project), mm
    )
    return result


@app.get("/api/git/summary")
async def git_summary(repo_path: str = Query(..., max_length=500)):
    from core.git_integration import get_repo_summary

    return get_repo_summary(repo_path)


# ============================
#  Decision Diffing
# ============================


@app.get("/api/memory/{project}/decisions/timeline")
async def decision_timeline(project: str):
    """Return decisions as a timeline, detecting reversals."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    decisions = memory.get("decisions", [])

    # Detect reversals: look for "Reverted" or pairs where subject appears twice with opposite verbs
    reversal_keywords = {
        "revert",
        "undo",
        "roll back",
        "switch back",
        "replaced",
        "removed",
    }
    timeline = []
    for i, d in enumerate(decisions):
        text = d.get("decision", "").lower()
        flags = []
        if any(kw in text for kw in reversal_keywords):
            flags.append("reversal")
        # Check if any earlier decision looks like it's being undone
        for prev in decisions[:i]:
            prev_text = prev.get("decision", "").lower()
            # Simple heuristic: share 3+ words and current is a reversal
            shared = set(text.split()) & set(prev_text.split()) - {
                "the",
                "a",
                "to",
                "and",
                "of",
            }
            if len(shared) >= 3 and "reversal" in flags:
                flags.append("reverses_prior")
                break
        timeline.append({**d, "flags": flags, "index": i})

    return {"timeline": timeline, "total": len(timeline)}


# ============================
#  Multi-project Context
# ============================


class ProjectDepRequest(BaseModel):
    project: str = Field(..., max_length=100)
    depends_on: str = Field(..., max_length=100)


@app.post("/api/memory/{project}/dependencies")
async def add_dependency(project: str, req: ProjectDepRequest):
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    deps = memory.setdefault("dependencies", [])
    dep = _sanitise_project(req.depends_on)
    if dep not in deps:
        deps.append(dep)
        from datetime import datetime, timezone

        memory["last_updated"] = datetime.now(timezone.utc).isoformat()
        mm.save_project_memory(project, memory)
    return {"dependencies": deps}


@app.get("/api/memory/{project}/context")
async def get_full_context(project: str, include_deps: bool = True):
    """
    Return aggregated context for a project, optionally pulling in
    context from dependency projects too.
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    context = mm.get_context_for_project(project)

    if include_deps:
        memory = mm.get_project_memory(project)
        for dep in memory.get("dependencies", []):
            try:
                dep_context = mm.get_context_for_project(dep)
                context += f"\n\n--- Dependency: {dep} ---\n{dep_context}"
            except Exception:
                pass

    return {"project": project, "context": context}


# ============================
#  Pattern-driven Templates
# ============================


@app.get("/api/memory/{project}/template")
async def get_prompt_template(project: str):
    """
    Generate a prompt template pre-loaded with project context,
    preferences, and common patterns for this project.
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.learner.learner import PatternLearner

    learner = PatternLearner(mm)
    patterns = learner.get_common_patterns(project, 3)
    top_cats = [p["name"].replace("category:", "") for p in patterns]
    prefs = memory.get("preferences", {})
    stack = memory.get("tech_stack", [])
    decisions = memory.get("decisions", [])[-3:]

    lines = [f"# Working on: {project}"]
    if stack:
        lines.append(f"Stack: {', '.join(stack)}")
    if top_cats:
        lines.append(f"Common work areas: {', '.join(top_cats)}")
    if prefs:
        pref_str = ", ".join(f"{k}={v}" for k, v in prefs.items())
        lines.append(f"Preferences: {pref_str}")
    if decisions:
        lines.append("\nRecent decisions:")
        for d in decisions:
            lines.append(f"  - {d.get('decision', '')}")
    lines.append("\nTask:")

    return {
        "project": project,
        "template": "\n".join(lines),
        "patterns": top_cats,
    }


# ============================
#  Export: Agent Context Formats
# ============================


@app.get("/api/memory/{project}/export/claude")
async def export_claude_context(project: str):
    """Export project memory as Claude-style <context> XML block."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    context = mm.get_context_for_project(project)
    xml = f"<context>\n{context}\n</context>"
    return {"format": "claude_xml", "content": xml}


@app.get("/api/memory/{project}/export/openai")
async def export_openai_system(project: str):
    """Export project memory as an OpenAI system message."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    context = mm.get_context_for_project(project)
    return {
        "format": "openai_system",
        "message": {"role": "system", "content": context},
    }


# ============================
#  Research Pipeline
# ============================


class AutoResearchRequest(BaseModel):
    query: str = Field(..., max_length=300)
    max_results: int = Field(5, ge=1, le=20)


@app.post("/api/research/auto")
async def auto_research(req: AutoResearchRequest):
    from core.research_pipeline import auto_research as _auto_research

    tb = get_tropebook()
    return await _auto_research(req.query, tb, req.max_results)


@app.get("/api/research/stale")
async def stale_citations(max_age_days: int = Query(90, ge=1, le=3650)):
    from core.research_pipeline import check_staleness

    tb = get_tropebook()
    stale = check_staleness(
        {k: v.to_dict() for k, v in tb.citations.items()}, max_age_days
    )
    return {"stale": stale, "count": len(stale)}


@app.get("/api/research/duplicates")
async def semantic_duplicates(threshold: float = Query(0.92, ge=0.5, le=1.0)):
    from core.research_pipeline import find_semantic_duplicates

    tb = get_tropebook()
    store = _get_embed_store("citations")
    dups = await find_semantic_duplicates(tb, store, threshold)
    return {"duplicates": dups, "count": len(dups)}


@app.get("/api/citations/{cid}/related")
async def get_related_citations(cid: str, top_k: int = Query(5, ge=1, le=20)):
    from core.research_pipeline import suggest_related

    tb = get_tropebook()
    store = _get_embed_store("citations")
    return {"related": await suggest_related(cid, tb, store, top_k)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8766, reload=False)
