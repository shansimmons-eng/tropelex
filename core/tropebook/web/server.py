"""
Tropelex Web API - FastAPI server for Tropelex web interface
Linux-native, portable — no hardcoded paths.
"""

import json
import logging
import os
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
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

# --- Background scheduler ---
_scheduler = None


@asynccontextmanager
async def lifespan(app_instance):
    """Start background scheduler on startup, stop on shutdown."""
    global _scheduler
    from core.scheduler import BackgroundScheduler
    # Compute BASE_DIR at call time (module-level BASE_DIR is set later)
    _base = Path(__file__).parent.parent.parent.parent
    _scheduler = BackgroundScheduler(base_dir=_base)
    await _scheduler.start()
    logger.info("Tropelex started with background scheduler")
    yield
    if _scheduler:
        await _scheduler.stop()
    logger.info("Tropelex shutdown complete")


app = FastAPI(title="Tropelex API", version="1.3.0", lifespan=lifespan)

# CORS — localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8766", "http://127.0.0.1:8766"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rate limiting (in-memory, per-IP) ---
_rate_limits: dict[str, list[float]] = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 120    # requests per window (generous for SPA dashboards)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiter: 120 requests per 60s. Skipped for localhost/127.0.0.1."""
    client_ip = request.client.host if request.client else "unknown"
    # Skip rate limiting for localhost — this is a local dev dashboard
    if client_ip in ("127.0.0.1", "::1", "unknown"):
        return await call_next(request)
    now = time.time()
    # Clean old entries
    if client_ip in _rate_limits:
        _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < RATE_LIMIT_WINDOW]
    else:
        _rate_limits[client_ip] = []
    # Check limit
    if len(_rate_limits[client_ip]) >= RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
        )
    _rate_limits[client_ip].append(now)
    return await call_next(request)

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

try:
    app.mount(
        "/images", StaticFiles(directory=str(BASE_DIR / "images")), name="images"
    )
except Exception as exc:
    logger.warning("Images not mounted: %s", exc)

# --- Mount quick-wins routers ---
from core.webhooks.router import webhook_router       # noqa: E402
from core.sync.router import sync_router               # noqa: E402
from core.collaboration.router import router as collaboration_router  # noqa: E402
from core.health.router import health_router            # noqa: E402
from core.rag_router import rag_router                  # noqa: E402
from core.tropebook.feed_intelligence_router import feed_intel_router  # noqa: E402
from core.impact.router import impact_router             # noqa: E402
from core.graph_router import graph_router                # noqa: E402
from core.search_router import search_router              # noqa: E402
from core.analytics_router import analytics_router        # noqa: E402
from core.tropebook.alert_router import alert_router      # noqa: E402
from core.ghost.router import ghost_router                  # noqa: E402
from core.explain.router import explain_router              # noqa: E402
from core.handoff.router import handoff_router              # noqa: E402
from core.ghost.preventive_router import preventive_router  # noqa: E402
from core.compaction.router import compaction_router        # noqa: E402
from core.corroboration.router import corroboration_router  # noqa: E402
from core.cost.router import cost_router                    # noqa: E402
from core.friction.router import friction_router            # noqa: E402
from core.prefetch.router import prefetch_router            # noqa: E402
from core.prbot.router import prbot_router                  # noqa: E402
from core.narrative.router import narrative_router          # noqa: E402
from core.lens.router import lens_router                    # noqa: E402
from core.market.router import market_router                # noqa: E402
from core.slack.router import slack_router                  # noqa: E402
from core.timetravel.router import timetravel_router        # noqa: E402
from core.contradictions.router import contradiction_router  # noqa: E402
from core.personas.router import persona_router            # noqa: E402
from core.federation.router import federation_router        # noqa: E402

# Point sync router's BASE_DIR at the actual project root
import core.sync.router as _sync_mod                   # noqa: E402
_sync_mod.BASE_DIR = BASE_DIR

app.include_router(webhook_router)
app.include_router(sync_router)
app.include_router(collaboration_router)
app.include_router(health_router)
app.include_router(rag_router)
app.include_router(feed_intel_router)
app.include_router(impact_router)
app.include_router(graph_router)
app.include_router(search_router)
app.include_router(analytics_router)
app.include_router(alert_router)
app.include_router(ghost_router)
app.include_router(explain_router)
app.include_router(handoff_router)
app.include_router(preventive_router)
app.include_router(compaction_router)
app.include_router(corroboration_router)
app.include_router(cost_router)
app.include_router(friction_router)
app.include_router(prefetch_router)
app.include_router(prbot_router)
app.include_router(narrative_router)
app.include_router(lens_router)
app.include_router(market_router)
app.include_router(slack_router)
app.include_router(timetravel_router)
app.include_router(contradiction_router)
app.include_router(persona_router)
app.include_router(federation_router)


# --- Request body models ---
class CitationCreate(BaseModel):
    title: str = Field(..., max_length=500)
    url: str = Field(..., max_length=2000)
    summary: str = Field("", max_length=5000)
    source: str = Field("", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=20)


class CitationUpdate(BaseModel):
    summary: str | None = Field(None, max_length=5000)
    tags: list[str] | None = Field(None, max_length=20)
    entities: list[str] | None = Field(None, max_length=20)


class CompressRequest(BaseModel):
    prompt: str = Field(..., max_length=8000)
    level: int = Field(2, ge=1, le=3)


class LinkRequest(BaseModel):
    source_url: str = Field(..., max_length=2000)
    target_url: str = Field(..., max_length=2000)
    relationship: str = Field(..., max_length=100)


class ImportRequest(BaseModel):
    data: dict[str, Any]
    source_type: str = "deep_research"


class MemoryProjectCreate(BaseModel):
    project_name: str = Field(..., max_length=100, pattern=r"^[a-zA-Z0-9_\-]+$")


class MemoryUpdate(BaseModel):
    description: str | None = Field(None, max_length=1000)
    tech_stack: list[str] | None = Field(None, max_length=50)
    preferences: dict[str, Any] | None = None


# --- App state (lazy init) ---
_state: dict[str, Any] = {"tropebook": None, "memory_manager": None}


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

    if not UI_DASHBOARD_PATH.exists():
        return HTMLResponse(
            content=f"<h1>Tropelex</h1><p>Dashboard not found at {UI_DASHBOARD_PATH}</p>",
            status_code=500,
        )
    with open(UI_DASHBOARD_PATH, encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/guide")
async def docs():
    from fastapi.responses import HTMLResponse

    docs_path = SCRIPT_DIR / "static" / "docs.html"
    if not docs_path.exists():
        return HTMLResponse(
            content="<h1>Tropelex Docs</h1><p>Documentation not found.</p>",
            status_code=404,
        )
    with open(docs_path, encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)


@app.get("/hijacker")
@app.get("/compressor")
@app.get("/prompt-lab")
async def hijacker():
    """Redirect to main dashboard Prompt Lab section."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/#section-pipeline", status_code=302)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.2.0"}


@app.get("/api/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables (localhost only, DEBUG=1 required)."""
    if os.environ.get("DEBUG") != "1":
        raise HTTPException(status_code=403, detail="Set DEBUG=1 to enable")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    return {
        "openai_key_present": bool(openai_key),
        "openai_key_valid": openai_key.startswith("sk-") if openai_key else False,
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
async def list_citations(tag: str | None = None, source: str | None = None):
    """List citations, optionally filtered by tag or source."""
    try:
        tb = get_tropebook()
        if tag:
            # Sanitize tag input
            tag = tag.strip()[:100]
            filtered_cids = tb._index["by_tag"].get(tag, [])
            citations = [
                (cid, tb.citations[cid])
                for cid in filtered_cids
                if cid in tb.citations
            ]
        elif source:
            from core.tropebook import SourceType

            source = source.strip()[:50]
            source_type = (
                SourceType(source)
                if source in [s.value for s in SourceType]
                else SourceType.MANUAL
            )
            filtered_cids = tb._index["by_source"].get(source_type.value, [])
            citations = [
                (cid, tb.citations[cid])
                for cid in filtered_cids
                if cid in tb.citations
            ]
        else:
            citations = list(tb.citations.items())
        return {
            "citations": [c.to_dict(id=cid) for cid, c in citations],
            "count": len(citations),
        }
    except Exception as e:
        logger.error("list_citations failed: %s", e)
        raise HTTPException(500, f"Failed to list citations: {e}")


@app.post("/api/citations")
async def create_citation(citation: CitationCreate):
    """Create a new citation."""
    try:
        tb = get_tropebook()
        # Sanitize inputs
        title = citation.title.strip()[:500]
        url = citation.url.strip()[:2000]
        summary = citation.summary.strip()[:5000]
        source = citation.source.strip()[:200]
        tags = [t.strip()[:50] for t in citation.tags[:20]]
        entities = [e.strip()[:50] for e in citation.entities[:20]]
        
        cid = tb.add(
            title=title, url=url, summary=summary,
            source=source, tags=tags, entities=entities,
        )
        return {"id": cid, "citation": tb.get(cid).to_dict()}
    except Exception as e:
        logger.error("create_citation failed: %s", e)
        raise HTTPException(500, f"Failed to create citation: {e}")


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
    q: str = Query(..., min_length=1, max_length=200), limit: int = Query(20, le=500)
):
    """Search citations by query."""
    try:
        tb = get_tropebook()
        # Sanitize query
        q = q.strip()[:200]
        results = tb.search(q, limit)
        return {"results": [c.to_dict(id=cid) for cid, c in results], "count": len(results)}
    except Exception as e:
        logger.error("search_citations failed: %s", e)
        raise HTTPException(500, f"Search failed: {e}")


@app.get("/api/tags")
async def list_tags():
    """List all tags across citations."""
    try:
        tb = get_tropebook()
        return {"tags": list(tb._index["by_tag"].keys())}
    except Exception as e:
        logger.error("list_tags failed: %s", e)
        raise HTTPException(500, f"Failed to list tags: {e}")


@app.get("/api/entities")
async def list_entities():
    """List all entities across citations."""
    try:
        tb = get_tropebook()
        return {"entities": list(tb._index["by_entity"].keys())}
    except Exception as e:
        logger.error("list_entities failed: %s", e)
        raise HTTPException(500, f"Failed to list entities: {e}")


@app.get("/api/stats")
async def get_stats():
    """Get aggregate statistics for the tropebook."""
    try:
        tb = get_tropebook()
        return tb.stats()
    except Exception as e:
        logger.error("get_stats failed: %s", e)
        raise HTTPException(500, f"Failed to get stats: {e}")


@app.post("/api/import")
async def import_sources(import_req: ImportRequest):
    """Import citations from JSON data."""
    try:
        tb = get_tropebook()
        count = tb.import_from_deep_research(import_req.data)
        return {"imported": count}
    except Exception as e:
        logger.error("import_sources failed: %s", e)
        raise HTTPException(500, f"Import failed: {e}")


@app.get("/api/export")
async def export_all():
    """Export all citations and graph as JSON."""
    try:
        tb = get_tropebook()
        return tb.export_json()
    except Exception as e:
        logger.error("export_all failed: %s", e)
        raise HTTPException(500, f"Export failed: {e}")


@app.get("/api/account/export")
async def account_export():
    """Export everything: memory, tropebook, feeds, settings (no secrets)."""
    try:
        mm = get_memory_manager()
        tb = get_tropebook()
        fm = _get_feed_manager()
        # Memory: all projects
        projects = {}
        for f in mm.memory_dir.glob("*.json"):
            projects[f.stem] = json.loads(f.read_text())
        # Tropebook
        tropebook = tb.export_json()
        # Feeds
        feeds = [feed.to_dict() for feed in fm.list_feeds()]
        # Settings (exclude secrets)
        settings = {}
        env_path = BASE_DIR / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k not in ("OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY", "ANTHROPIC_API_KEY",
                                 "EXA_API_KEY", "SERPER_API_KEY", "CUSTOM_LLM_API_KEY"):
                        settings[k] = v.strip()
        return {
            "version": "1.0",
            "projects": projects,
            "tropebook": tropebook,
            "feeds": feeds,
            "settings": settings,
        }
    except Exception as e:
        logger.error("account_export failed: %s", e)
        raise HTTPException(500, f"Account export failed: {e}")


@app.post("/api/account/import")
async def account_import(req: ImportRequest):
    """Import a full account export (memory + tropebook + feeds)."""
    try:
        data = req.data
        imported_counts = {"projects": 0, "citations": 0, "feeds": 0}
        # Import projects
        for name, proj_data in (data.get("projects") or {}).items():
            mm = get_memory_manager()
            proj_file = mm.memory_dir / f"{name}.json"
            proj_file.write_text(json.dumps(proj_data, indent=2))
            imported_counts["projects"] += 1
        # Import tropebook citations
        tb = get_tropebook()
        for citation in (data.get("tropebook", {}).get("citations") or []):
            if isinstance(citation, dict) and citation.get("url"):
                tb.add(
                    title=citation.get("title", ""),
                    url=citation["url"],
                    summary=citation.get("summary", ""),
                    tags=citation.get("tags", []),
                    source_type=citation.get("source_type", "imported"),
                )
                imported_counts["citations"] += 1
        # Import feeds
        fm = _get_feed_manager()
        for feed_data in (data.get("feeds") or []):
            try:
                fm.create(
                    name=feed_data.get("name", "Imported Feed"),
                    query=feed_data.get("query", ""),
                    description=feed_data.get("description", ""),
                    interval=feed_data.get("interval", "weekly"),
                    sources=feed_data.get("sources", ["web"]),
                    tags=feed_data.get("tags", []),
                )
                imported_counts["feeds"] += 1
            except Exception:
                pass  # Skip duplicates
        return {"imported": imported_counts}
    except Exception as e:
        logger.error("account_import failed: %s", e)
        raise HTTPException(500, f"Account import failed: {e}")


@app.post("/api/link")
async def link_citations(req: LinkRequest):
    """Create a relationship between two citations."""
    try:
        tb = get_tropebook()
        # Sanitize inputs
        source_url = req.source_url.strip()[:2000]
        target_url = req.target_url.strip()[:2000]
        relationship = req.relationship.strip()[:100]
        tb.add_relationship(source_url, target_url, relationship)
        return {"linked": True}
    except Exception as e:
        logger.error("link_citations failed: %s", e)
        raise HTTPException(500, f"Failed to link citations: {e}")


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
    """List all projects in memory."""
    try:
        mm = get_memory_manager()
        return {"projects": [{"name": p} for p in mm.list_projects()]}
    except Exception as e:
        logger.error("list_memory_projects failed: %s", e)
        raise HTTPException(500, f"Failed to list projects: {e}")


@app.post("/api/memory")
async def create_memory_project(data: MemoryProjectCreate):
    """Create a new project in memory."""
    try:
        mm = get_memory_manager()
        name = _sanitise_project(data.project_name)
        memory = mm.get_project_memory(name)
        mm.save_project_memory(name, memory)
        return {"created": True, "project": name}
    except Exception as e:
        logger.error("create_memory_project failed: %s", e)
        raise HTTPException(500, f"Failed to create project: {e}")


@app.get("/api/memory/{project}")
async def get_memory_project(project: str):
    """Get a project's memory data."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        return mm.get_project_memory(project)
    except Exception as e:
        logger.error("get_memory_project failed: %s", e)
        raise HTTPException(500, f"Failed to get project: {e}")


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
    project: str | None = None


@app.post("/api/capture")
async def quick_capture(data: QuickCapture, project_name: str | None = None):
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
async def get_patterns(project: str | None = None):
    """Get learned patterns and suggestions."""
    try:
        mm = get_memory_manager()
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
    """List all projects."""
    try:
        mm = get_memory_manager()
        return {"projects": mm.list_projects()}
    except Exception as e:
        logger.error("list_projects failed: %s", e)
        raise HTTPException(500, f"Failed to list projects: {e}")


@app.post("/api/analyze/decisions")
async def detect_decisions(data: dict[str, str]):
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
    """Compress a prompt using AI."""
    try:
        from core.llm import compress as llm_compress

        # Sanitize input
        prompt = req.prompt.strip()[:8000]
        result = await llm_compress(prompt)
        compressed = result["compressed"]
        return {
            "compressed": compressed,
            "backend": result["backend"],
            "error": result.get("error"),
            "original_length": len(prompt),
            "compressed_length": len(compressed),
            "saved_pct": round((1 - len(compressed) / max(len(prompt), 1)) * 100, 1),
        }
    except Exception as e:
        logger.error("compress_prompt failed: %s", e)
        raise HTTPException(500, f"Compression failed: {e}")


class ApiKeyRequest(BaseModel):
    key: str = Field(..., pattern=r"^[A-Z0-9_]+$", max_length=64)
    value: str = Field(..., max_length=512)


@app.post("/api/settings/apikey")
async def save_api_key(req: ApiKeyRequest):
    """Write an API key to the .env file (localhost only)."""
    # Only allow known safe key names
    ALLOWED_KEYS = {
        "OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY", "ANTHROPIC_API_KEY",
        "EXA_API_KEY", "SERPER_API_KEY",
        "CUSTOM_LLM_HOST", "CUSTOM_LLM_MODEL", "CUSTOM_LLM_API_KEY",
        # Deep research (last30days engine) sources
        "XAI_API_KEY", "SCRAPECREATORS_API_KEY",
        "BSKY_HANDLE", "BSKY_APP_PASSWORD",
        "AUTH_TOKEN", "CT0", "PARALLEL_API_KEY",
        # Gemini (last30days engine planning + reranking)
        "GOOGLE_API_KEY", "GEMINI_API_KEY",
    }
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


def _mask_key(value: str) -> str:
    """Mask an API key for display: random number of asterisks, no characters revealed."""
    import random
    if not value:
        return ""
    return "*" * random.randint(8, 16)


@app.get("/api/settings")
async def get_settings():
    """Return current key status (masked) and non-secret settings."""
    settings_keys = [
        "OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY", "EXA_API_KEY",
        "SERPER_API_KEY", "CUSTOM_LLM_HOST", "CUSTOM_LLM_MODEL", "CUSTOM_LLM_API_KEY",
        "XAI_API_KEY", "SCRAPECREATORS_API_KEY",
        "BSKY_HANDLE", "BSKY_APP_PASSWORD",
        "AUTH_TOKEN", "CT0", "PARALLEL_API_KEY",
        "GOOGLE_API_KEY", "GEMINI_API_KEY",
    ]
    keys = {}
    # Non-secret values returned in the clear; everything else is masked.
    NON_SECRET = {"CUSTOM_LLM_HOST", "CUSTOM_LLM_MODEL", "BSKY_HANDLE"}
    for k in settings_keys:
        val = os.environ.get(k, "")
        if k in NON_SECRET:
            keys[k] = {"configured": bool(val), "value": val}
        else:
            keys[k] = {"configured": bool(val), "masked": _mask_key(val)}
    return {"keys": keys}


@app.post("/api/test-key")
async def test_api_key(req: ApiKeyRequest):
    """Test if an API key works by making a lightweight call to the provider."""
    import httpx

    # If sentinel value, test whatever key the server already has in os.environ
    key = req.value.strip() if req.value.strip() != "__USE_SERVER_ENV__" else ""
    if not key:
        key = os.environ.get(req.key, "")
    if not key:
        raise HTTPException(400, f"No key configured for {req.key}")

    try:
        if req.key == "OPENAI_API_KEY":
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "OpenAI key is valid"}
                return {"ok": False, "message": f"OpenAI returned {resp.status_code}"}

        elif req.key == "BRAVE_SEARCH_API_KEY":
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": key, "Accept": "application/json"},
                    params={"q": "test", "count": 1},
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "Brave Search key is valid"}
                return {"ok": False, "message": f"Brave returned {resp.status_code}"}

        elif req.key == "EXA_API_KEY":
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": key, "Content-Type": "application/json"},
                    json={"query": "test", "numResults": 1},
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "Exa key is valid"}
                return {"ok": False, "message": f"Exa returned {resp.status_code}"}

        elif req.key == "SERPER_API_KEY":
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": key, "Content-Type": "application/json"},
                    json={"q": "test"},
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "Serper key is valid"}
                return {"ok": False, "message": f"Serper returned {resp.status_code}"}

        elif req.key == "CUSTOM_LLM_API_KEY":
            host = os.environ.get("CUSTOM_LLM_HOST", "")
            if not host:
                return {"ok": False, "message": "No custom host configured yet"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{host.rstrip('/')}/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "Custom provider key is valid"}
                return {"ok": False, "message": f"Custom provider returned {resp.status_code}"}

        elif req.key == "XAI_API_KEY":
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": "xAI key is valid"}
                return {"ok": False, "message": f"xAI returned {resp.status_code}"}

        else:
            raise HTTPException(400, f"Cannot test key type: {req.key}")

    except httpx.TimeoutException:
        return {"ok": False, "message": "Connection timed out"}
    except httpx.ConnectError:
        return {"ok": False, "message": "Could not connect to provider"}
    except Exception as e:
        return {"ok": False, "message": f"Test failed: {e}"}


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
    """Semantic search across citations using embeddings."""
    try:
        from core.llm import embed_one

        # Sanitize query
        query = req.query.strip()[:1000]
        vec = await embed_one(query)
        if vec is None:
            raise HTTPException(
                status_code=503, detail="Embeddings unavailable — configure OPENAI_API_KEY"
            )
        store = _get_embed_store(req.scope)
        results = store.search(vec, top_k=req.top_k, min_score=req.min_score)
        return {"results": results, "count": len(results), "query": query}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("semantic_search failed: %s", e)
        raise HTTPException(500, f"Semantic search failed: {e}")


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
    for idx, ((cid, c), vec) in enumerate(zip(to_embed, vecs)):
        store.put(cid, texts[idx], vec, meta={"title": c.title, "url": c.url})
    return {"embedded": len(to_embed)}


# ============================
#  Git Integration
# ============================


class GitSyncRequest(BaseModel):
    repo_path: str = Field(..., max_length=500)
    project: str = Field(..., max_length=100)


@app.post("/api/git/sync")
async def git_sync(req: GitSyncRequest):
    """Sync git commits to project memory."""
    try:
        from core.git_integration import sync_repo_to_memory

        mm = get_memory_manager()
        # Sanitize inputs
        repo_path = req.repo_path.strip()[:500]
        project = _sanitise_project(req.project)
        result = await sync_repo_to_memory(repo_path, project, mm)
        return result
    except Exception as e:
        logger.error("git_sync failed: %s", e)
        raise HTTPException(500, f"Git sync failed: {e}")


@app.get("/api/git/summary")
async def git_summary(repo_path: str = Query(..., max_length=500)):
    """Get basic repo summary."""
    try:
        from core.git_integration import get_repo_summary

        repo_path = repo_path.strip()[:500]
        return get_repo_summary(repo_path)
    except Exception as e:
        logger.error("git_summary failed: %s", e)
        raise HTTPException(500, f"Git summary failed: {e}")


@app.get("/api/git/deep-summary")
async def git_deep_summary(repo_path: str = Query(..., max_length=500)):
    """Enhanced repo summary with deep commit analysis."""
    try:
        from core.git_integration import get_deep_repo_summary

        repo_path = repo_path.strip()[:500]
        return get_deep_repo_summary(repo_path)
    except Exception as e:
        logger.error("git_deep_summary failed: %s", e)
        raise HTTPException(500, f"Git deep summary failed: {e}")


@app.post("/api/git/sync-deep")
async def git_sync_deep(req: GitSyncRequest):
    """Deep sync: extracts decisions, rationale, dependency changes, patterns."""
    from core.git_integration import sync_repo_to_memory

    mm = get_memory_manager()
    result = await sync_repo_to_memory(
        req.repo_path, _sanitise_project(req.project), mm
    )
    return result


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
#  Decision Trees
# ============================


@app.get("/api/memory/{project}/decision-tree")
async def get_decision_tree(project: str):
    """Get the full decision tree with relationships."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    decisions = memory.get("decisions", [])

    from core.decision_tree import DecisionTree

    tree = DecisionTree.from_decisions(decisions)
    return {"tree": tree.to_dict(), "stats": tree.stats()}


@app.get("/api/memory/{project}/decision-tree/timeline")
async def get_decision_tree_timeline(project: str):
    """Get decisions as a timeline with relationship info."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    decisions = memory.get("decisions", [])

    from core.decision_tree import DecisionTree

    tree = DecisionTree.from_decisions(decisions)
    return {"timeline": tree.get_timeline(), "stats": tree.stats()}


@app.get("/api/memory/{project}/decision-tree/chains")
async def get_decision_chains(project: str):
    """Get decision chains (A caused B caused C)."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    decisions = memory.get("decisions", [])

    from core.decision_tree import DecisionTree

    tree = DecisionTree.from_decisions(decisions)
    chains = tree.get_chains()
    return {"chains": chains, "count": len(chains)}


@app.get("/api/memory/{project}/decision-tree/{decision_id}")
async def get_decision_detail(project: str, decision_id: str):
    """Get a single decision with its ancestors and descendants."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    decisions = memory.get("decisions", [])

    from core.decision_tree import DecisionTree

    tree = DecisionTree.from_decisions(decisions)
    node = tree.get_decision(decision_id)
    if not node:
        raise HTTPException(status_code=404, detail="Decision not found")

    ancestors = tree.get_ancestors(decision_id)
    descendants = tree.get_descendants(decision_id)

    return {
        "decision": node,
        "ancestors": ancestors,
        "descendants": descendants,
    }


# ============================
#  Living ADRs
# ============================


@app.get("/api/memory/{project}/adrs")
async def generate_adrs(
    project: str,
    format: str = Query("tropelex", pattern=r"^(nygard|madr|tropelex)$"),
    only_significant: bool = Query(True),
):
    """Generate ADRs for all decisions in a project."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.adr_generator import generate_adrs_for_project

    adrs = generate_adrs_for_project(memory, format, only_significant)
    return {"adrs": adrs, "count": len(adrs), "format": format}


@app.get("/api/memory/{project}/adrs/bundle")
async def generate_adr_bundle(
    project: str,
    format: str = Query("tropelex", pattern=r"^(nygard|madr|tropelex)$"),
):
    """Generate a single markdown file with all ADRs."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.adr_generator import generate_adr_markdown_bundle

    bundle = generate_adr_markdown_bundle(memory, format)
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        content=bundle,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={project}-adrs.md"},
    )


# ============================
#  Session Replay
# ============================


@app.get("/api/memory/{project}/sessions")
async def get_sessions(project: str, limit: int = Query(20, ge=1, le=100)):
    """Get recent sessions for a project."""
    project = _sanitise_project(project)
    from core.session_replay import SessionReplay

    replay = SessionReplay(str(BASE_DIR))
    sessions = replay.get_sessions(project, limit)
    return {"sessions": sessions, "count": len(sessions)}


@app.get("/api/memory/{project}/sessions/{session_id}")
async def get_session_detail(project: str, session_id: str):
    """Get full session detail including snapshots."""
    project = _sanitise_project(project)
    from core.session_replay import SessionReplay

    replay = SessionReplay(str(BASE_DIR))
    session = replay.get_session(project, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/api/memory/{project}/sessions/{session_id}/changes")
async def get_session_changes(project: str, session_id: str):
    """Get just the changes for a session."""
    project = _sanitise_project(project)
    from core.session_replay import SessionReplay

    replay = SessionReplay(str(BASE_DIR))
    changes = replay.get_session_changes(project, session_id)
    if changes is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"changes": changes, "count": len(changes)}


class SessionRecordRequest(BaseModel):
    summary: str = Field("", max_length=2000)
    session_type: str = Field("manual", max_length=50)


@app.post("/api/memory/{project}/sessions/record")
async def record_session(project: str, req: SessionRecordRequest):
    """Record current memory state as a session snapshot."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    from core.session_replay import SessionReplay

    replay = SessionReplay(str(BASE_DIR))
    current = mm.get_project_memory(project)

    # Get previous snapshot for diffing
    sessions = replay.get_sessions(project, limit=1)
    if sessions:
        prev = replay.get_session(project, sessions[0]["session_id"])
        before = prev.get("snapshot_after", current) if prev else current
    else:
        before = current

    result = replay.record_session(
        project, before, current,
        summary=req.summary,
        session_type=req.session_type,
    )
    return result


@app.post("/api/memory/{project}/sessions/{session_id}/rollback")
async def rollback_session(project: str, session_id: str):
    """Rollback memory to the state before a session."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    from core.session_replay import SessionReplay

    replay = SessionReplay(str(BASE_DIR))
    result = replay.rollback_session(project, session_id, mm)
    if not result.get("rolled_back"):
        raise HTTPException(status_code=400, detail=result.get("error", "Rollback failed"))
    return result


@app.get("/api/memory/{project}/sessions/weekly-summary")
async def get_weekly_summary(project: str):
    """Get a summary of what changed this week."""
    project = _sanitise_project(project)
    from core.session_replay import SessionReplay

    replay = SessionReplay(str(BASE_DIR))
    return replay.get_weekly_summary(project)


# ============================
#  Knowledge Decay & Confidence
# ============================


@app.get("/api/memory/{project}/confidence")
async def get_confidence(project: str):
    """Get confidence summary for a project's decisions."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.knowledge_decay import get_confidence_summary

    return get_confidence_summary(memory)


@app.get("/api/memory/{project}/stale")
async def get_stale_decisions(
    project: str,
    threshold: float = Query(0.3, ge=0.0, le=1.0),
    max_age_days: float = Query(180, ge=1, le=3650),
):
    """Get stale decisions (low confidence or old)."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.knowledge_decay import get_stale_decisions

    stale = get_stale_decisions(memory.get("decisions", []), threshold, max_age_days)
    return {"stale": stale, "count": len(stale)}


@app.get("/api/memory/{project}/decisions/scored")
async def get_scored_decisions(project: str):
    """Get all decisions with confidence scores."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.knowledge_decay import score_decisions

    scored = score_decisions(memory.get("decisions", []))
    return {"decisions": scored, "count": len(scored)}


@app.post("/api/memory/{project}/decay/apply")
async def apply_decay(project: str):
    """Apply confidence scores to all decisions in memory."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.knowledge_decay import apply_decay_to_memory
    from datetime import datetime, timezone

    memory = apply_decay_to_memory(memory)
    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    mm.save_project_memory(project, memory)

    return {"applied": True, "summary": memory.get("confidence_summary", {})}


# ============================
#  Research Chains
# ============================


class ResearchChainCreate(BaseModel):
    goal: str = Field(..., max_length=500)


class ResearchStepAdd(BaseModel):
    chain_id: str = Field(..., max_length=64)
    query: str = Field(..., max_length=300)
    findings: list[dict] = Field(default_factory=list, max_length=20)
    gaps: list[str] = Field(default_factory=list, max_length=10)


@app.get("/api/memory/{project}/research-chains")
async def list_research_chains(project: str, status: str | None = None):
    """List research chains for a project."""
    project = _sanitise_project(project)
    from core.research_chains import ResearchChainManager

    manager = ResearchChainManager(str(BASE_DIR))
    chains = manager.list_chains(project, status)
    return {"chains": chains, "count": len(chains)}


@app.post("/api/memory/{project}/research-chains")
async def create_research_chain(project: str, req: ResearchChainCreate):
    """Create a new research chain."""
    project = _sanitise_project(project)
    from core.research_chains import ResearchChain, ResearchChainManager

    manager = ResearchChainManager(str(BASE_DIR))
    chain = ResearchChain(req.goal)
    chain_id = manager.save_chain(project, chain)
    return {"chain_id": chain_id, "goal": req.goal}


@app.get("/api/memory/{project}/research-chains/{chain_id}")
async def get_research_chain(project: str, chain_id: str):
    """Get a full research chain."""
    project = _sanitise_project(project)
    from core.research_chains import ResearchChainManager

    manager = ResearchChainManager(str(BASE_DIR))
    chain = manager.load_chain(project, chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")
    return chain.to_dict()


@app.post("/api/memory/{project}/research-chains/{chain_id}/step")
async def add_research_step(project: str, chain_id: str, req: ResearchStepAdd):
    """Add a step to a research chain."""
    project = _sanitise_project(project)
    from core.research_chains import ResearchChainManager

    manager = ResearchChainManager(str(BASE_DIR))
    chain = manager.load_chain(project, chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    chain.add_step(req.query, req.findings, req.gaps)
    manager.save_chain(project, chain)
    return {"step_count": len(chain.steps)}


@app.post("/api/memory/{project}/research-chains/{chain_id}/complete")
async def complete_research_chain(project: str, chain_id: str, synthesis: str = ""):
    """Complete a research chain with a synthesis."""
    project = _sanitise_project(project)
    from core.research_chains import ResearchChainManager

    manager = ResearchChainManager(str(BASE_DIR))
    chain = manager.load_chain(project, chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    chain.complete(synthesis or f"Completed with {len(chain.steps)} steps")
    manager.save_chain(project, chain)
    return {"status": "completed", "synthesis": chain.synthesis}


# ============================
#  Memory-Driven RAG & Cross-Pollination
# ============================


class RAGQuery(BaseModel):
    query: str = Field(..., max_length=500)
    top_k: int = Field(5, ge=1, le=20)


@app.post("/api/memory/{project}/rag")
async def memory_rag(project: str, req: RAGQuery):
    """Retrieve relevant memory snippets for a query."""
    project = _sanitise_project(project)
    mm = get_memory_manager()

    from core.rag import MemoryRAG

    rag = MemoryRAG(mm)
    results = rag.retrieve(project, req.query, req.top_k)
    return {"results": results, "count": len(results), "query": req.query}


@app.post("/api/memory/{project}/rag/context")
async def memory_rag_context(project: str, req: RAGQuery):
    """Retrieve relevant memory as formatted context string."""
    project = _sanitise_project(project)
    mm = get_memory_manager()

    from core.rag import MemoryRAG

    rag = MemoryRAG(mm)
    context = rag.retrieve_with_context(project, req.query, req.top_k)
    return {"context": context, "query": req.query}


@app.get("/api/memory/{project}/cross-pollinate")
async def cross_pollinate(project: str, query: str = Query("", max_length=500)):
    """Find transferable knowledge from similar projects."""
    project = _sanitise_project(project)
    mm = get_memory_manager()

    from core.rag import CrossPollinator

    cp = CrossPollinator(mm)
    transfers = cp.find_transferable_knowledge(project, query or None)
    return {"transfers": transfers, "count": len(transfers)}


@app.get("/api/memory/{project}/cross-pollinate/briefing")
async def cross_pollinate_briefing(project: str, query: str = Query("", max_length=500)):
    """Get a briefing of cross-project knowledge."""
    project = _sanitise_project(project)
    mm = get_memory_manager()

    from core.rag import CrossPollinator

    cp = CrossPollinator(mm)
    briefing = cp.get_project_briefing(project, query or None)
    return {"briefing": briefing, "project": project}


class ApproachRequest(BaseModel):
    problem: str = Field(..., max_length=500)


@app.post("/api/memory/{project}/suggest-approaches")
async def suggest_approaches(project: str, req: ApproachRequest):
    """Suggest approaches from similar projects for a problem."""
    project = _sanitise_project(project)
    mm = get_memory_manager()

    from core.rag import CrossPollinator

    cp = CrossPollinator(mm)
    approaches = cp.suggest_approaches(project, req.problem)
    return {"approaches": approaches, "count": len(approaches)}


# ============================
#  Agent Skills & Prompt Genealogy
# ============================


class SkillRecordRequest(BaseModel):
    session_type: str = Field("manual", max_length=50)
    categories: list[str] = Field(default_factory=list, max_length=10)
    outcome: str = Field("success", pattern=r"^(success|partial|failure)$")
    details: str = Field("", max_length=500)


@app.get("/api/memory/{project}/agent-skills")
async def get_agent_skills(project: str):
    """Get agent skill scores for a project."""
    project = _sanitise_project(project)
    from core.agent_skills import AgentSkillGraph

    graph = AgentSkillGraph(str(BASE_DIR))
    skills = graph.get_skills(project)
    return {"skills": skills, "count": len(skills)}


@app.post("/api/memory/{project}/agent-skills/record")
async def record_agent_skill(project: str, req: SkillRecordRequest):
    """Record a session outcome to update agent skills."""
    project = _sanitise_project(project)
    from core.agent_skills import AgentSkillGraph

    graph = AgentSkillGraph(str(BASE_DIR))
    graph.record_session_outcome(
        project, req.session_type, req.categories, req.outcome, req.details
    )
    return {"recorded": True, "categories": req.categories}


@app.get("/api/memory/{project}/agent-skills/briefing")
async def get_agent_briefing(project: str):
    """Get agent proficiency briefing for context injection."""
    project = _sanitise_project(project)
    from core.agent_skills import AgentSkillGraph

    graph = AgentSkillGraph(str(BASE_DIR))
    briefing = graph.get_briefing(project)
    return {"briefing": briefing, "project": project}


class PromptRecordRequest(BaseModel):
    original: str = Field(..., max_length=5000)
    compressed: str = Field(..., max_length=5000)
    strategy: str = Field("default", max_length=100)
    compression_ratio: float = Field(0.0, ge=0.0, le=1.0)


class PromptOutcomeRequest(BaseModel):
    prompt_id: str = Field(..., max_length=64)
    outcome: str = Field(..., pattern=r"^(good|rephrased|failed)$")


@app.get("/api/memory/{project}/prompt-genealogy")
async def get_prompt_genealogy(project: str):
    """Get prompt genealogy stats."""
    project = _sanitise_project(project)
    from core.agent_skills import PromptGenealogy

    pg = PromptGenealogy(str(BASE_DIR))
    return pg.get_stats(project)


@app.post("/api/memory/{project}/prompt-genealogy/record")
async def record_prompt_compression(project: str, req: PromptRecordRequest):
    """Record a prompt compression event."""
    project = _sanitise_project(project)
    from core.agent_skills import PromptGenealogy

    pg = PromptGenealogy(str(BASE_DIR))
    prompt_id = pg.record_compression(
        project, req.original, req.compressed, req.strategy, req.compression_ratio
    )
    return {"prompt_id": prompt_id}


@app.post("/api/memory/{project}/prompt-genealogy/outcome")
async def record_prompt_outcome(project: str, req: PromptOutcomeRequest):
    """Record the outcome of a compressed prompt."""
    project = _sanitise_project(project)
    from core.agent_skills import PromptGenealogy

    pg = PromptGenealogy(str(BASE_DIR))
    pg.record_outcome(project, req.prompt_id, req.outcome)
    return {"recorded": True, "prompt_id": req.prompt_id}


@app.get("/api/memory/{project}/prompt-genealogy/rankings")
async def get_strategy_rankings(project: str):
    """Get compression strategy rankings."""
    project = _sanitise_project(project)
    from core.agent_skills import PromptGenealogy

    pg = PromptGenealogy(str(BASE_DIR))
    rankings = pg.get_strategy_rankings(project)
    return {"rankings": rankings, "count": len(rankings)}


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
    """Run automated research on a query."""
    try:
        from core.research_pipeline import auto_research as _auto_research

        tb = get_tropebook()
        # Sanitize query
        query = req.query.strip()[:300]
        return await _auto_research(query, tb, req.max_results)
    except Exception as e:
        logger.error("auto_research failed: %s", e)
        raise HTTPException(500, f"Auto research failed: {e}")


@app.get("/api/research/stale")
async def stale_citations(max_age_days: int = Query(90, ge=1, le=3650)):
    """Find stale citations that need updating."""
    try:
        from core.research_pipeline import check_staleness

        tb = get_tropebook()
        stale = check_staleness(
            {k: v.to_dict() for k, v in tb.citations.items()}, max_age_days
        )
        return {"stale": stale, "count": len(stale)}
    except Exception as e:
        logger.error("stale_citations failed: %s", e)
        raise HTTPException(500, f"Staleness check failed: {e}")


@app.get("/api/research/duplicates")
async def semantic_duplicates(threshold: float = Query(0.92, ge=0.5, le=1.0)):
    """Find semantically duplicate citations."""
    try:
        from core.research_pipeline import find_semantic_duplicates

        tb = get_tropebook()
        store = _get_embed_store("citations")
        dups = await find_semantic_duplicates(tb, store, threshold)
        return {"duplicates": dups, "count": len(dups)}
    except Exception as e:
        logger.error("semantic_duplicates failed: %s", e)
        raise HTTPException(500, f"Duplicate detection failed: {e}")


@app.get("/api/citations/{cid}/related")
async def get_related_citations(cid: str, top_k: int = Query(5, ge=1, le=20)):
    from core.research_pipeline import suggest_related

    tb = get_tropebook()
    store = _get_embed_store("citations")
    return {"related": await suggest_related(cid, tb, store, top_k)}


# ============================
#  Research Feeds
# ============================

_feed_manager = None
_feed_scheduler = None
_feed_run_timestamps: list[float] = []
_FEED_RUN_RATE_LIMIT = 5  # max 5 feed runs per minute


def _check_feed_rate_limit():
    """Stricter rate limit for expensive feed operations."""
    now = time.time()
    _feed_run_timestamps[:] = [t for t in _feed_run_timestamps if now - t < 60]
    if len(_feed_run_timestamps) >= _FEED_RUN_RATE_LIMIT:
        raise HTTPException(429, "Feed run rate limit exceeded. Max 5 runs per minute.")
    _feed_run_timestamps.append(now)


def _get_feed_manager():
    global _feed_manager
    if _feed_manager is None:
        from core.tropebook.research_feeds import ResearchFeedManager

        _feed_manager = ResearchFeedManager(storage_path=str(BASE_DIR / "memory"))
    return _feed_manager


def _get_feed_scheduler():
    global _feed_scheduler
    if _feed_scheduler is None:
        from core.tropebook.scheduler import FeedScheduler

        _feed_scheduler = FeedScheduler(
            feed_manager=_get_feed_manager(),
            brave_api_key=os.environ.get("BRAVE_SEARCH_API_KEY"),
            storage_path=str(BASE_DIR / "memory" / "tropebook"),
        )
    return _feed_scheduler


def _sanitize_feed_id(feed_id: str) -> str:
    """Reject feed IDs that aren't alphanumeric/hyphen/underscore."""
    import re

    if not re.match(r"^[a-zA-Z0-9_-]{4,64}$", feed_id):
        raise HTTPException(400, "Invalid feed ID format")
    return feed_id


class FeedCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    query: str = Field(..., min_length=1, max_length=500)
    description: str = Field("", max_length=1000)
    interval: str = Field("weekly")
    sources: list[str] = Field(default_factory=lambda: ["web"])
    tags: list[str] = Field(default_factory=list)
    max_results_per_run: int = Field(20, ge=1, le=100)
    research_provider: str = Field("web_search", pattern=r"^(web_search|deep_research)$")


class FeedUpdateRequest(BaseModel):
    name: str | None = None
    query: str | None = None
    description: str | None = None
    interval: str | None = None
    sources: list[str] | None = None
    tags: list[str] | None = None
    max_results_per_run: int | None = None
    enabled: bool | None = None
    research_provider: str | None = None


@app.get("/api/research-feeds")
async def list_feeds(
    enabled_only: bool = Query(False),
    tag: str | None = Query(None),
):
    """List all research feeds, optionally filtered by enabled state or tag."""
    fm = _get_feed_manager()
    feeds = fm.list_feeds(enabled_only=enabled_only, tag=tag)
    return {"feeds": [f.to_dict() for f in feeds], "count": len(feeds)}


@app.post("/api/research-feeds")
async def create_feed(req: FeedCreateRequest):
    """Create a new research feed with the given query and schedule."""
    fm = _get_feed_manager()
    try:
        feed = fm.create(
            name=req.name, query=req.query, description=req.description,
            interval=req.interval, sources=req.sources, tags=req.tags,
            max_results_per_run=req.max_results_per_run,
            research_provider=req.research_provider,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return feed.to_dict()


# ── Last30Days Deep Research ───────────────────────────────────────────

_DEEP_RESEARCH_DIR = BASE_DIR / "memory" / "deep_research"
_DEEP_RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
_DEEP_RESEARCH_INDEX = _DEEP_RESEARCH_DIR / "index.json"


def _atomic_write(path: Path, data: str) -> None:
    """Write data to path atomically via temp file + replace."""
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_deep_research_index() -> list[dict]:
    """Load the deep research runs index."""
    if not _DEEP_RESEARCH_INDEX.exists():
        return []
    try:
        return json.loads(_DEEP_RESEARCH_INDEX.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_deep_research_index(runs: list[dict]) -> None:
    """Atomically save the deep research runs index."""
    _atomic_write(_DEEP_RESEARCH_INDEX, json.dumps(runs, indent=2))


def _save_deep_research_run(query: str, html: str, citations: list[dict]) -> dict:
    """Persist a deep research run. Returns the run metadata."""
    import uuid
    run_id = uuid.uuid4().hex[:12]
    timestamp = datetime.now(timezone.utc).isoformat()

    # Save HTML output
    html_file = _DEEP_RESEARCH_DIR / f"{run_id}.html"
    html_file.write_text(html, encoding="utf-8")

    run = {
        "id": run_id,
        "timestamp": timestamp,
        "query": query,
        "citations_count": len(citations),
        "html_file": f"{run_id}.html",
    }

    # Update index (prepend — newest first)
    runs = _load_deep_research_index()
    runs.insert(0, run)
    # Keep last 50 runs
    if len(runs) > 50:
        # Clean up orphaned HTML files
        keep_ids = {r["id"] for r in runs[:50]}
        for old_run in runs[50:]:
            old_file = _DEEP_RESEARCH_DIR / old_run["html_file"]
            try:
                old_file.unlink(missing_ok=True)
            except OSError:
                pass
        runs = runs[:50]
    _save_deep_research_index(runs)

    return run


class Last30DaysRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    emit: str = Field("html", pattern=r"^(html|md|compact)$")
    timeout: int | None = Field(None, ge=30, le=600)


@app.post("/api/last30days/query")
async def last30days_query(req: Last30DaysRequest):
    """Run a deep research query via the last30days engine. Returns HTML output."""
    try:
        from core.last30days.runner import run_query, run_query_and_extract_citations

        html, citations = run_query_and_extract_citations(
            req.query, timeout=req.timeout, emit=req.emit,
        )

        # Persist the run
        run = _save_deep_research_run(req.query, html, citations)

        return {
            "query": req.query,
            "output": html,
            "citations": citations[:50],
            "citations_count": len(citations),
            "run_id": run["id"],
            "timestamp": run["timestamp"],
        }
    except ImportError as e:
        raise HTTPException(503, f"last30days engine not available: {e}")
    except TimeoutError as e:
        raise HTTPException(504, str(e))
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@app.get("/api/last30days/runs")
async def list_deep_research_runs(limit: int = Query(50, ge=1, le=100)):
    """List deep research runs (newest first)."""
    runs = _load_deep_research_index()
    return {"runs": runs[:limit], "count": len(runs)}


@app.get("/api/last30days/runs/{run_id}")
async def get_deep_research_run(run_id: str):
    """Get a specific deep research run's HTML output."""
    if not re.match(r"^[a-f0-9]{12}$", run_id):
        raise HTTPException(400, "Invalid run ID format")
    runs = _load_deep_research_index()
    run = next((r for r in runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(404, "Run not found")
    html_file = _DEEP_RESEARCH_DIR / run["html_file"]
    if not html_file.exists():
        raise HTTPException(404, "Run output file not found")
    return {
        "id": run["id"],
        "timestamp": run["timestamp"],
        "query": run["query"],
        "citations_count": run["citations_count"],
        "output": html_file.read_text(encoding="utf-8"),
    }


# ── Literal routes BEFORE parameterized /{feed_id} routes ──

@app.get("/api/research-feeds/stats")
async def feed_stats():
    """Aggregate stats: total feeds, active, total runs, total citations, by interval."""
    return _get_feed_manager().stats()


@app.post("/api/research-feeds/tick")
async def tick_feeds():
    """Run all feeds whose next_run is in the past. Returns results of each run."""
    _check_feed_rate_limit()
    scheduler = _get_feed_scheduler()
    runs = scheduler.tick()
    return {"runs": [r.to_dict() for r in runs], "count": len(runs)}


# ── Parameterized /{feed_id} routes ──

@app.get("/api/research-feeds/{feed_id}")
async def get_feed(feed_id: str):
    """Get a single feed's configuration and metadata."""
    feed_id = _sanitize_feed_id(feed_id)
    fm = _get_feed_manager()
    feed = fm.get(feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found")
    return feed.to_dict()


@app.put("/api/research-feeds/{feed_id}")
async def update_feed(feed_id: str, req: FeedUpdateRequest):
    """Update whitelisted fields on a feed (name, query, interval, etc.)."""
    feed_id = _sanitize_feed_id(feed_id)
    fm = _get_feed_manager()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    feed = fm.update(feed_id, **updates)
    if not feed:
        raise HTTPException(404, "Feed not found")
    return feed.to_dict()


@app.delete("/api/research-feeds/{feed_id}")
async def delete_feed(feed_id: str):
    """Delete a feed, its run history, and its markdown output."""
    feed_id = _sanitize_feed_id(feed_id)
    fm = _get_feed_manager()
    if not fm.delete(feed_id):
        raise HTTPException(404, "Feed not found")
    return {"deleted": feed_id}


@app.post("/api/research-feeds/{feed_id}/run")
async def run_feed_now(feed_id: str):
    """Trigger an immediate execution of the given feed."""
    _check_feed_rate_limit()
    feed_id = _sanitize_feed_id(feed_id)
    fm = _get_feed_manager()
    feed = fm.get(feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found")
    scheduler = _get_feed_scheduler()
    run = scheduler.run_feed(feed)
    return run.to_dict()


@app.get("/api/research-feeds/{feed_id}/markdown")
async def get_feed_markdown(feed_id: str):
    """Return the persistent markdown output for a feed."""
    feed_id = _sanitize_feed_id(feed_id)
    fm = _get_feed_manager()
    if not fm.get(feed_id):
        raise HTTPException(404, "Feed not found")
    return {"feed_id": feed_id, "markdown": fm.get_feed_markdown(feed_id)}


@app.get("/api/research-feeds/{feed_id}/runs")
async def get_feed_runs(feed_id: str, limit: int = Query(20, ge=1, le=100)):
    """Return recent run history for a feed."""
    feed_id = _sanitize_feed_id(feed_id)
    fm = _get_feed_manager()
    runs = fm.get_runs(feed_id=feed_id, limit=limit)
    return {"runs": [r.to_dict() for r in runs], "count": len(runs)}


@app.get("/api/research-feeds/{feed_id}/citations")
async def get_feed_citations(feed_id: str, limit: int = Query(50, ge=1, le=200)):
    """Return citations accumulated by a feed, most recent first."""
    feed_id = _sanitize_feed_id(feed_id)
    fm = _get_feed_manager()
    feed = fm.get(feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found")
    tb = get_tropebook()
    citations = [
        {"id": cid, **tb.get(cid).to_dict()}
        for cid in feed.citation_ids[-limit:]
        if tb.get(cid)
    ]
    return {"citations": citations, "count": len(citations)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8766, reload=False)
