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

# Every .env key that holds a credential (API key, token, password, cookie).
# Single source of truth for both the settings-write allowlist and the
# account-export secret filter — account_export previously kept its own,
# much shorter exclusion list that had drifted out of sync with this one
# and was silently leaking BSKY_APP_PASSWORD, CT0, and other live
# credentials into "Export All" backups.
SECRET_ENV_KEYS = {
    "OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY", "ANTHROPIC_API_KEY",
    "EXA_API_KEY", "SERPER_API_KEY",
    "CUSTOM_LLM_HOST", "CUSTOM_LLM_MODEL", "CUSTOM_LLM_API_KEY",
    "XAI_API_KEY", "SCRAPECREATORS_API_KEY",
    "BSKY_HANDLE", "BSKY_APP_PASSWORD",
    "AUTH_TOKEN", "CT0", "PARALLEL_API_KEY",
    "GOOGLE_API_KEY", "GEMINI_API_KEY",
}

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


# --- Interface heartbeat (in-memory, no persistence needed) ---
_interface_last_seen: dict[str, float] = {}
KNOWN_INTERFACES = ["mcp", "tui", "opencode", "emacs"]


@app.middleware("http")
async def interface_heartbeat_middleware(request: Request, call_next):
    """Record which client interfaces are actively talking to this server.

    Each interface (MCP server, TUI, OpenCode plugin, Emacs package) sends
    an X-Tropelex-Client header identifying itself. Purely observational —
    doesn't gate anything, just powers the dashboard's Interfaces card.
    """
    client = request.headers.get("x-tropelex-client")
    if client in KNOWN_INTERFACES:
        _interface_last_seen[client] = time.time()
    return await call_next(request)


@app.get("/api/interfaces/status")
async def get_interfaces_status():
    """Last-seen timestamps for each known client interface."""
    now = time.time()
    return {
        "interfaces": {
            name: {
                "last_seen": _interface_last_seen.get(name),
                "seconds_ago": (
                    round(now - _interface_last_seen[name])
                    if name in _interface_last_seen else None
                ),
            }
            for name in KNOWN_INTERFACES
        }
    }


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
from core.handoff.router import handoff_router, list_unacknowledged_handoffs  # noqa: E402
from core.ghost.preventive_router import preventive_router  # noqa: E402
from core.compaction.router import compaction_router        # noqa: E402
from core.cost.router import cost_router                    # noqa: E402
from core.friction.router import friction_router            # noqa: E402
from core.prefetch.router import prefetch_router            # noqa: E402
from core.prbot.router import prbot_router                  # noqa: E402
from core.narrative.router import narrative_router          # noqa: E402
from core.lens.router import lens_router                    # noqa: E402
from core.market.router import market_router                # noqa: E402
from core.goals.router import goals_router                    # noqa: E402
from core.slack.router import slack_router                  # noqa: E402
from core.timetravel.router import timetravel_router        # noqa: E402
from core.contradictions.router import contradiction_router  # noqa: E402
from core.personas.router import persona_router            # noqa: E402
from core.benchmarks.router import benchmarks_router        # noqa: E402
from core.tropebook.web_researcher_router import web_research_router  # noqa: E402
from core.docmine.router import docmine_router                     # noqa: E402
from core.agent_audit.router import agent_audit_router              # noqa: E402
from core.driftbench.router import driftbench_router                # noqa: E402
from core.telemetry import telemetry_router, _emit_telemetry        # noqa: E402
from core.triggers.tag_gate import require_tag, TagRequiredError, SAFETY_CATEGORIES  # noqa: E402
from core.safety import require_safety_metadata, SafetyMetadataRequiredError  # noqa: E402
from core.goals.drift import score_trend_drift  # noqa: E402
from core.friction.miner import compute_friction_penalty  # noqa: E402
from core.session_shape.router import session_shape_router  # noqa: E402

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
app.include_router(cost_router)
app.include_router(friction_router)
app.include_router(prefetch_router)
app.include_router(prbot_router)
app.include_router(narrative_router)
app.include_router(lens_router)
app.include_router(market_router)
app.include_router(goals_router)
app.include_router(slack_router)
app.include_router(timetravel_router)
app.include_router(contradiction_router)
app.include_router(persona_router)
app.include_router(benchmarks_router)
app.include_router(web_research_router)
app.include_router(docmine_router)
app.include_router(agent_audit_router)
app.include_router(driftbench_router)
app.include_router(telemetry_router)
app.include_router(session_shape_router)


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
    project: str | None = Field(None, max_length=100)


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


@app.get("/api/tests/count")
async def get_test_suite_count():
    """Real pytest test count via `--collect-only` -- replaces the
    hardcoded "1455 Passed" the dashboard's Run Diagnostics panel and
    Getting Started card used to show regardless of the suite's actual
    size. Collection-only: fast, no execution side effects."""
    from core.test_suite_status import get_test_count
    return get_test_count(str(BASE_DIR))


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
                    if k not in SECRET_ENV_KEYS:
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
        # Import tropebook citations + their relationship graph. Citations
        # are keyed by ID in the export (see Tropebook.export_json), not a
        # list — import_bundle() preserves those IDs so graph edges (which
        # reference citations by ID) stay valid after import.
        tb = get_tropebook()
        tropebook_data = data.get("tropebook") or {}
        bundle_result = tb.import_bundle(
            tropebook_data.get("citations") or {},
            tropebook_data.get("graph"),
        )
        imported_counts["citations"] = bundle_result["citations_imported"]
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


class SafetyMetadata(BaseModel):
    """Safety metadata for decisions, aligned with AI safety research priorities."""
    risk_level: str = Field(
        default="low",
        pattern="^(low|medium|high|critical)$",
        description="Risk level: low, medium, high, or critical"
    )
    reversibility: bool = Field(
        default=True,
        description="Whether this decision can be easily reversed"
    )
    affected_systems: list[str] = Field(
        default_factory=list,
        description="List of systems/components affected by this decision"
    )
    rationale_quality: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for the decision rationale (0.0-1.0)"
    )
    alignment_considerations: str = Field(
        default="",
        max_length=500,
        description="Notes on alignment/safety considerations"
    )
    requires_review: bool = Field(
        default=False,
        description="Whether this decision requires human review"
    )
    safety_category: str | None = Field(
        default=None,
        pattern="^(general|adversarial|robustness|monitoring|governance|alignment)$",
        description=(
            "Safety category for classification. No default on purpose — "
            "add_decision requires this to be an explicit choice, not a "
            "silently-assigned one. See core/triggers/tag_gate.py."
        ),
    )


class DecisionCreate(BaseModel):
    decision: str = Field(..., max_length=500)
    context: str = Field("", max_length=1000)
    safety_metadata: SafetyMetadata | None = Field(
        default=None,
        description="Optional safety metadata for AI safety research alignment"
    )
    goal_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional link to the Goal this decision serves.",
    )


def _auto_classify_safety(decision: str, context: str) -> dict:
    """
    Auto-classify safety metadata for a decision based on content analysis.
    Uses keyword matching and heuristics to assign risk levels and categories.
    """
    decision_lower = decision.lower()
    context_lower = context.lower()
    combined = f"{decision_lower} {context_lower}"

    # Risk level classification
    risk_level = "low"
    requires_review = False

    # High-risk indicators
    high_risk_keywords = [
        "delete", "remove", "drop", "destroy", "purge", "wipe",
        "security", "auth", "permission", "access", "credential",
        "production", "live", "deploy", "release",
        "database", "schema", "migration", "backup",
        "api key", "secret", "token", "password",
    ]

    # Critical-risk indicators
    critical_risk_keywords = [
        "rm -rf", "drop table", "delete all", "purge all",
        "revoke access", "disable security", "bypass auth",
        "emergency", "hotfix", "rollback",
    ]

    # Medium-risk indicators
    medium_risk_keywords = [
        "change", "update", "modify", "refactor",
        "config", "settings", "environment",
        "dependency", "upgrade", "version",
    ]

    # Check for critical risks first
    if any(kw in combined for kw in critical_risk_keywords):
        risk_level = "critical"
        requires_review = True
    elif any(kw in combined for kw in high_risk_keywords):
        risk_level = "high"
        requires_review = True
    elif any(kw in combined for kw in medium_risk_keywords):
        risk_level = "medium"

    # Safety category classification
    safety_category = "general"

    category_keywords = {
        "adversarial": ["adversarial", "attack", "exploit", "vulnerability", "penetration", "red team"],
        "robustness": ["robust", "reliable", "fault tolerant", "resilient", "fail safe", "error handling"],
        "monitoring": ["monitor", "observe", "track", "log", "alert", "detect", "anomaly"],
        "governance": ["govern", "compliance", "audit", "policy", "standard", "regulation"],
        "alignment": ["alignment", "value", "ethical", "safety", "harm", "bias", "fairness"],
    }

    for category, keywords in category_keywords.items():
        if any(kw in combined for kw in keywords):
            safety_category = category
            break

    # Reversibility assessment
    reversible_indicators = ["add", "create", "enable", "extend", "augment"]
    irreversible_indicators = ["delete", "remove", "drop", "destroy", "migrate", "convert"]

    reversibility = True
    if any(kw in combined for kw in irreversible_indicators):
        reversibility = False
    elif any(kw in combined for kw in reversible_indicators):
        reversibility = True

    # Affected systems detection
    affected_systems = []
    system_keywords = {
        "memory": ["memory", "storage", "persistence", "database", "db"],
        "api": ["api", "endpoint", "route", "server", "http"],
        "auth": ["auth", "authentication", "authorization", "login", "session"],
        "ui": ["ui", "frontend", "dashboard", "interface", "display"],
        "security": ["security", "encryption", "hash", "token", "key"],
        "git": ["git", "commit", "branch", "merge", "repository"],
    }

    for system, keywords in system_keywords.items():
        if any(kw in combined for kw in keywords):
            affected_systems.append(system)

    return {
        "risk_level": risk_level,
        "reversibility": reversibility,
        "affected_systems": affected_systems,
        "rationale_quality": 0.5,  # Default, can be overridden
        "alignment_considerations": "",
        "requires_review": requires_review,
        "safety_category": safety_category,
    }


class CategoryPreviewRequest(BaseModel):
    decision: str = Field(..., max_length=500)
    context: str = Field("", max_length=1000)


@app.post("/api/memory/{project}/decisions/preview-category")
async def preview_decision_category(project: str, data: CategoryPreviewRequest):
    """Return the auto-classifier's suggestion without saving anything.

    Callers (dashboard, TUI) use this to show a suggested category before
    the user picks one — add_decision itself no longer accepts that
    suggestion silently, see require_tag in core/triggers/tag_gate.py.
    """
    _sanitise_project(project)
    return _auto_classify_safety(data.decision, data.context)


@app.get("/api/memory/{project}/decisions/untagged")
async def list_untagged_decisions(project: str):
    """List decisions with no explicit safety_category — the triage queue.

    Decisions captured via /{project}/slack/capture (Emacs, Slack) never go
    through add_decision's require_tag gate on purpose: that path fires
    with no human present (e.g. magit auto-capture on commit), so there's
    no one to ask. They land untagged instead and show up here for a human
    to classify later, rather than being blocked or silently defaulted.
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    untagged = [
        d for d in memory.get("decisions", [])
        if not (d.get("safety_metadata") or {}).get("safety_category")
    ]
    return {"decisions": untagged, "count": len(untagged)}


@app.get("/api/memory/{project}/decisions/flagged")
async def list_flagged_decisions(project: str):
    """List decisions with non-empty content_flags (#40) -- stored-prompt-
    injection markers found in the decision/context text at write time.
    Flag, don't block: these decisions were still stored normally, this is
    just the triage queue for reviewing what tripped a marker.
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    flagged = [
        d for d in memory.get("decisions", [])
        if isinstance(d, dict) and isinstance(d.get("content_flags"), list) and d.get("content_flags")
    ]
    return {"decisions": flagged, "count": len(flagged)}


class TagDecisionRequest(BaseModel):
    safety_category: str = Field(..., max_length=32)


@app.patch("/api/memory/{project}/decisions/{decision_id}/safety-category")
async def tag_decision(project: str, decision_id: str, data: TagDecisionRequest):
    """Attach an explicit safety_category to a decision captured without
    one — the write side of the untagged-decisions triage queue above.
    This is the only way an item leaves that queue: decisions from
    /{project}/slack/capture never go through add_decision, so there's no
    other path that sets safety_metadata on them after the fact.
    """
    project = _sanitise_project(project)
    try:
        category = require_tag(data.safety_category)
    except TagRequiredError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict())

    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    for d in memory.get("decisions", []):
        if d.get("id") == decision_id:
            safety = d.setdefault("safety_metadata", {})
            safety["safety_category"] = category
            memory["last_updated"] = datetime.now(timezone.utc).isoformat()
            mm.save_project_memory(project, memory)
            return {"tagged": True, "decision": d}
    raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")


@app.post("/api/memory/{project}/decisions")
async def add_decision(project: str, data: DecisionCreate):
    """Add a decision to project memory. Requires an explicit safety_category.

    Auto-classification still runs, but only to produce a *suggestion* on
    the 422 a caller gets back if it omits the category — it no longer
    writes that guess to disk unasked. See core/triggers/tag_gate.py for
    the rationale (an omitted or invalid category is an unmade choice, not
    a "general" one).
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    suggestion = _auto_classify_safety(data.decision, data.context)
    provided_category = data.safety_metadata.safety_category if data.safety_metadata else None
    try:
        category = require_tag(provided_category, suggested=suggestion["safety_category"])
    except TagRequiredError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict())

    # Start from the auto-classified suggestion and overlay only the fields
    # the caller actually set (via model_fields_set, not model_dump) — a
    # caller sending just {"safety_category": "..."} still gets a real
    # heuristic risk_level/affected_systems instead of silently falling
    # back to SafetyMetadata's bare field defaults (low/True/[]/...).
    if data.safety_metadata:
        explicit = data.safety_metadata.model_dump(include=data.safety_metadata.model_fields_set)
        safety_metadata = {**suggestion, **explicit}
    else:
        safety_metadata = dict(suggestion)
    safety_metadata["safety_category"] = category

    # #54: once the *resolved* risk lands on high/critical — whether the
    # caller set that explicitly or the auto-classifier guessed it from
    # keywords — reversibility/affected_systems/requires_review can no
    # longer ride in on the guess unexamined. Same "accepting the guess is
    # a decision, not a default" principle as the safety_category gate
    # above, conditional on risk instead of universal.
    provided_fields = data.safety_metadata.model_fields_set if data.safety_metadata else set()
    try:
        require_safety_metadata(safety_metadata["risk_level"], provided_fields, suggestion)
    except SafetyMetadataRequiredError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict())

    if data.goal_id is not None:
        known_goal_ids = {g.get("id") for g in memory.get("goals", []) if g.get("id")}
        if data.goal_id not in known_goal_ids:
            raise HTTPException(status_code=404, detail=f"Goal '{data.goal_id}' not found in project '{project}'")

    import uuid as _uuid
    decision_entry = {
        "id": _uuid.uuid4().hex[:12],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": data.decision,
        "context": data.context,
        "safety_metadata": safety_metadata,
        "goal_id": data.goal_id,
    }

    # #40: flag, don't block -- screens for stored-prompt-injection markers
    # in agent/user-supplied text, same patterns Agent Surface Audit uses
    # for config scanning (core/injection_sentinel.py). Never rejects the
    # write; content_flags is only attached when something actually matched.
    from core.injection_sentinel import scan_content
    flags = scan_content(data.decision) + scan_content(data.context)
    if flags:
        decision_entry["content_flags"] = flags

    memory.setdefault("decisions", []).append(decision_entry)
    memory["last_updated"] = datetime.now(timezone.utc).isoformat()
    _append_audit_event(
        memory,
        "decision_created",
        decision_id=decision_entry["id"],
        decision=decision_entry["decision"],
        risk_level=safety_metadata.get("risk_level", "low"),
    )
    mm.save_project_memory(project, memory)
    _emit_telemetry("OK", f"Decision captured in {project}")
    return {"added": True, "decision": decision_entry}






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
        result = await llm_compress(prompt, project=req.project)
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
    if req.key not in SECRET_ENV_KEYS:
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
    # Seed/placeholder sentinels that must never render as "configured" in the UI.
    PLACEHOLDER_VALUES = {"test-value", "__USE_SERVER_ENV__", "changeme", "placeholder"}
    for k in settings_keys:
        val = os.environ.get(k, "")
        is_placeholder = val.strip() in PLACEHOLDER_VALUES
        configured = bool(val) and not is_placeholder
        if k in NON_SECRET:
            keys[k] = {"configured": configured, "value": "" if is_placeholder else val}
        else:
            keys[k] = {"configured": configured, "masked": "" if is_placeholder else _mask_key(val)}
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
    force: bool = False


@app.post("/api/git/sync")
async def git_sync(req: GitSyncRequest):
    """Sync git commits to project memory."""
    try:
        from core.git_integration import sync_repo_to_memory

        mm = get_memory_manager()
        # Sanitize inputs
        repo_path = req.repo_path.strip()[:500]
        project = _sanitise_project(req.project)
        result = await sync_repo_to_memory(repo_path, project, mm, force=req.force)
        return result
    except Exception as e:
        logger.error("git_sync failed: %s", e)
        raise HTTPException(500, f"Git sync failed: {e}")


@app.get("/api/git/summary")
async def git_summary(repo_path: str = Query("", max_length=500)):
    """Get basic repo summary. Defaults to project root if no path given."""
    try:
        from core.git_integration import get_repo_summary

        repo_path = repo_path.strip()[:500] or str(BASE_DIR)
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
        req.repo_path, _sanitise_project(req.project), mm, force=req.force
    )
    return result


# ============================
#  Decision Diffing
# ============================


@app.get("/api/memory/{project}/decisions/timeline")
async def decision_timeline(project: str):
    """Return decisions as a timeline with safety metadata and reversal detection."""
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

        # Add safety metadata to timeline entry
        entry = {**d, "flags": flags, "index": i}

        # Include safety metadata if present, otherwise use defaults
        safety = d.get("safety_metadata", {})
        if safety:
            entry["safety_metadata"] = safety
        else:
            # Provide default safety metadata for older decisions
            entry["safety_metadata"] = {
                "risk_level": "low",
                "reversibility": True,
                "affected_systems": [],
                "rationale_quality": 0.5,
                "alignment_considerations": "",
                "requires_review": False,
                "safety_category": "general",
            }

        timeline.append(entry)

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


@app.get("/api/memory/{project}/safety-stats")
async def get_safety_stats(project: str):
    """Get safety statistics for a project's decisions.
    
    Returns aggregated safety metadata across all decisions, including:
    - Risk level distribution
    - Safety category breakdown
    - Decisions requiring review
    - Reversibility statistics
    - Affected systems summary
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)
    decisions = memory.get("decisions", [])

    # Initialize counters
    risk_levels = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    safety_categories = {}
    affected_systems = {}
    requires_review_count = 0
    reversible_count = 0
    irreversible_count = 0
    total_decisions = len(decisions)

    for d in decisions:
        safety = d.get("safety_metadata", {})

        # Count risk levels
        risk_level = safety.get("risk_level", "low")
        risk_levels[risk_level] = risk_levels.get(risk_level, 0) + 1

        # Count safety categories
        category = safety.get("safety_category", "general")
        safety_categories[category] = safety_categories.get(category, 0) + 1

        # Count affected systems
        for system in safety.get("affected_systems", []):
            affected_systems[system] = affected_systems.get(system, 0) + 1

        # Count review requirements
        if safety.get("requires_review", False):
            requires_review_count += 1

        # Count reversibility
        if safety.get("reversibility", True):
            reversible_count += 1
        else:
            irreversible_count += 1

    return {
        "project": project,
        "total_decisions": total_decisions,
        "risk_levels": risk_levels,
        "safety_categories": safety_categories,
        "affected_systems": affected_systems,
        "requires_review_count": requires_review_count,
        "reversible_count": reversible_count,
        "irreversible_count": irreversible_count,
        "high_risk_decisions": risk_levels.get("high", 0) + risk_levels.get("critical", 0),
        "safety_score": _calculate_safety_score(
            risk_levels, requires_review_count, total_decisions,
            friction_penalty=_friction_penalty(memory),
        ),
        "friction_penalty": _friction_penalty(memory),
    }


def _friction_penalty(memory: dict) -> float:
    """Recent friction feeds into the safety score, not just the Health
    Dashboard — a project with a run of high-friction sessions (repeated
    corrections, retries, escalation) is a leading indicator of instability
    even before any individual decision looks risky on its own.

    Thin wrapper — the actual computation is core.friction.miner.
    compute_friction_penalty, extracted so core/goals/router.py's
    alignment aggregator can reuse it without importing from this module.
    """
    return compute_friction_penalty(memory.get("friction_history", []))


def _calculate_safety_score(
    risk_levels: dict, requires_review: int, total: int, friction_penalty: float = 0.0,
) -> float:
    """Calculate a safety score (0.0-1.0) based on risk distribution."""
    if total == 0:
        return 1.0

    # Weighted risk score: lower is safer
    weights = {"low": 0.0, "medium": 0.25, "high": 0.75, "critical": 1.0}
    weighted_sum = sum(risk_levels.get(level, 0) * weight for level, weight in weights.items())
    avg_risk = weighted_sum / total

    # Review penalty
    review_penalty = (requires_review / total) * 0.2

    # Safety score is inverse of risk (1.0 = safest)
    safety_score = max(0.0, 1.0 - avg_risk - review_penalty - friction_penalty)
    return round(safety_score, 3)


@app.get("/api/memory/{project}/safety-dashboard")
async def get_safety_dashboard(project: str):
    """Get comprehensive safety metrics dashboard for a project.
    
    Returns detailed safety analytics including:
    - Risk trend analysis over time
    - Safety category distribution
    - Decision impact matrix
    - Review status tracking
    - System risk exposure
    - Safety score history
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        _apply_persona_market_escalation(project, memory, mm)
        decisions = memory.get("decisions", [])

        # Time-based analysis
        monthly_risk = {}
        category_by_month = {}
        risk_trend = []

        # Impact analysis
        high_impact_decisions = []
        pending_reviews = []
        system_exposure = {}

        for d in decisions:
            timestamp = d.get("timestamp", "")
            safety = d.get("safety_metadata", {})
            risk_level = safety.get("risk_level", "low")
            category = safety.get("safety_category", "general")
            systems = safety.get("affected_systems", [])

            # Monthly grouping
            if timestamp:
                month_key = timestamp[:7]  # YYYY-MM
                if month_key not in monthly_risk:
                    monthly_risk[month_key] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
                monthly_risk[month_key][risk_level] = monthly_risk[month_key].get(risk_level, 0) + 1

                if month_key not in category_by_month:
                    category_by_month[month_key] = {}
                category_by_month[month_key][category] = category_by_month[month_key].get(category, 0) + 1

            # High impact decisions
            if risk_level in ["high", "critical"]:
                high_impact_decisions.append({
                    "id": d.get("id"),
                    "decision": d.get("decision"),
                    "risk_level": risk_level,
                    "timestamp": timestamp,
                    "safety_category": category,
                })

            # Pending reviews
            if safety.get("requires_review", False):
                pending_reviews.append({
                    "id": d.get("id"),
                    "decision": d.get("decision"),
                    "timestamp": timestamp,
                    "risk_level": risk_level,
                })

            # System exposure
            for system in systems:
                if system not in system_exposure:
                    system_exposure[system] = {"total": 0, "high_risk": 0, "categories": {}}
                system_exposure[system]["total"] += 1
                if risk_level in ["high", "critical"]:
                    system_exposure[system]["high_risk"] += 1
                system_exposure[system]["categories"][category] = system_exposure[system]["categories"].get(category, 0) + 1

        # Calculate trend (simple moving average of risk scores)
        risk_weights = {"low": 0.0, "medium": 0.25, "high": 0.75, "critical": 1.0}
        for month in sorted(monthly_risk.keys()):
            month_data = monthly_risk[month]
            total = sum(month_data.values())
            if total > 0:
                weighted_sum = sum(month_data[level] * risk_weights[level] for level in risk_weights)
                avg_risk = weighted_sum / total
                risk_trend.append({
                    "month": month,
                    "avg_risk": round(avg_risk, 3),
                    "total_decisions": total,
                    "distribution": month_data,
                })

        # Get basic stats for context
        stats = await get_safety_stats(project)

        return {
            "project": project,
            "summary": {
                "total_decisions": stats["total_decisions"],
                "safety_score": stats["safety_score"],
                "high_risk_decisions": stats["high_risk_decisions"],
                "pending_reviews": len(pending_reviews),
                "affected_systems_count": len(system_exposure),
            },
            "risk_trend": risk_trend,
            "category_distribution": stats["safety_categories"],
            "high_impact_decisions": high_impact_decisions[:10],  # Top 10
            "pending_reviews": pending_reviews[:10],  # Top 10
            "system_exposure": system_exposure,
            "monthly_risk": monthly_risk,
        }
    except Exception as e:
        logger.error("safety-dashboard failed: %s", e)
        raise HTTPException(500, f"Safety dashboard failed: {e}")


@app.get("/api/memory/{project}/safety-trend")
async def get_safety_trend(project: str, months: int = Query(12, ge=1, le=60)):
    """Get safety trend data for charting.
    
    Returns time-series data for visualizing safety metrics over time.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Group by month
        monthly_data = {}
        risk_weights = {"low": 0.0, "medium": 0.25, "high": 0.75, "critical": 1.0}

        for d in decisions:
            timestamp = d.get("timestamp", "")
            if not timestamp:
                continue

            month_key = timestamp[:7]
            if month_key not in monthly_data:
                monthly_data[month_key] = {
                    "risk_levels": {"low": 0, "medium": 0, "high": 0, "critical": 0},
                    "categories": {},
                    "total": 0,
                }

            safety = d.get("safety_metadata", {})
            risk_level = safety.get("risk_level", "low")
            category = safety.get("safety_category", "general")

            monthly_data[month_key]["risk_levels"][risk_level] = monthly_data[month_key]["risk_levels"].get(risk_level, 0) + 1
            monthly_data[month_key]["categories"][category] = monthly_data[month_key]["categories"].get(category, 0) + 1
            monthly_data[month_key]["total"] += 1

        # Convert to time series
        time_series = []
        for month in sorted(monthly_data.keys())[-months:]:
            data = monthly_data[month]
            total = data["total"]
            if total > 0:
                weighted_sum = sum(data["risk_levels"][level] * risk_weights[level] for level in risk_weights)
                avg_risk = weighted_sum / total
            else:
                avg_risk = 0.0

            time_series.append({
                "month": month,
                "avg_risk": round(avg_risk, 3),
                "total_decisions": total,
                "risk_levels": data["risk_levels"],
                "categories": data["categories"],
            })

        return {
            "project": project,
            "time_series": time_series,
            "period_months": months,
        }
    except Exception as e:
        logger.error("safety-trend failed: %s", e)
        raise HTTPException(500, f"Safety trend failed: {e}")


@app.get("/api/memory/{project}/decision-impact")
async def get_decision_impact(project: str):
    """Analyze the impact of decisions on system safety and dependencies.
    
    Returns:
    - Dependency graph of decisions
    - Risk propagation analysis
    - System vulnerability assessment
    - Critical path identification
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Build dependency graph
        decision_graph = {}
        system_dependencies = {}
        risk_propagation = {}

        for d in decisions:
            decision_id = d.get("id")
            safety = d.get("safety_metadata", {})
            systems = safety.get("affected_systems", [])
            risk_level = safety.get("risk_level", "low")

            # Build decision node
            decision_graph[decision_id] = {
                "id": decision_id,
                "decision": d.get("decision"),
                "risk_level": risk_level,
                "systems": systems,
                "depends_on": [],  # Will be populated
                "affects": [],     # Will be populated
            }

            # Track system dependencies
            for system in systems:
                if system not in system_dependencies:
                    system_dependencies[system] = {
                        "decisions": [],
                        "risk_levels": [],
                        "categories": [],
                    }
                system_dependencies[system]["decisions"].append(decision_id)
                system_dependencies[system]["risk_levels"].append(risk_level)
                system_dependencies[system]["categories"].append(safety.get("safety_category", "general"))

        # Analyze risk propagation (decisions affecting same systems)
        for system, data in system_dependencies.items():
            if len(data["decisions"]) > 1:
                # Calculate cumulative risk
                risk_weights = {"low": 0.0, "medium": 0.25, "high": 0.75, "critical": 1.0}
                total_risk = sum(risk_weights.get(r, 0.0) for r in data["risk_levels"])
                avg_risk = total_risk / len(data["risk_levels"])

                risk_propagation[system] = {
                    "decision_count": len(data["decisions"]),
                    "avg_risk": round(avg_risk, 3),
                    "max_risk": max(data["risk_levels"], key=lambda x: risk_weights.get(x, 0.0)),
                    "categories": list(set(data["categories"])),
                    "decisions": data["decisions"],
                }

        # Identify critical systems (high risk + multiple decisions)
        critical_systems = []
        for system, data in risk_propagation.items():
            if data["avg_risk"] > 0.5 or data["max_risk"] in ["high", "critical"]:
                critical_systems.append({
                    "system": system,
                    "risk_score": data["avg_risk"],
                    "decision_count": data["decision_count"],
                    "max_risk": data["max_risk"],
                })

        # Sort by risk score
        critical_systems.sort(key=lambda x: x["risk_score"], reverse=True)

        # Calculate overall impact metrics
        total_systems = len(system_dependencies)
        high_risk_systems = len([s for s in critical_systems if s["risk_score"] > 0.5])

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "total_systems": total_systems,
                "high_risk_systems": high_risk_systems,
                "critical_systems": len(critical_systems),
            },
            "system_dependencies": system_dependencies,
            "risk_propagation": risk_propagation,
            "critical_systems": critical_systems[:10],  # Top 10
        }
    except Exception as e:
        logger.error("decision-impact failed: %s", e)
        raise HTTPException(500, f"Decision impact analysis failed: {e}")


@app.get("/api/memory/{project}/decision-impact/{decision_id}")
async def get_decision_impact_detail(project: str, decision_id: str):
    """Get detailed impact analysis for a specific decision.
    
    Returns:
    - Direct impacts on systems
    - Related decisions (same systems)
    - Risk contribution
    - Dependency chain
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Find the target decision
        target_decision = None
        for d in decisions:
            if d.get("id") == decision_id:
                target_decision = d
                break

        if not target_decision:
            raise HTTPException(status_code=404, detail="Decision not found")

        target_safety = target_decision.get("safety_metadata", {})
        target_systems = target_safety.get("affected_systems", [])
        target_risk = target_safety.get("risk_level", "low")

        # Find related decisions (affecting same systems)
        related_decisions = []
        system_group = {}

        for d in decisions:
            if d.get("id") == decision_id:
                continue

            d_safety = d.get("safety_metadata", {})
            d_systems = d_safety.get("affected_systems", [])

            # Check for system overlap
            overlap = set(target_systems) & set(d_systems)
            if overlap:
                related_decisions.append({
                    "id": d.get("id"),
                    "decision": d.get("decision"),
                    "risk_level": d_safety.get("risk_level", "low"),
                    "shared_systems": list(overlap),
                    "timestamp": d.get("timestamp"),
                })

                # Group by system
                for system in overlap:
                    if system not in system_group:
                        system_group[system] = []
                    system_group[system].append(d.get("id"))

        # Calculate risk contribution
        risk_weights = {"low": 0.0, "medium": 0.25, "high": 0.75, "critical": 1.0}
        risk_score = risk_weights.get(target_risk, 0.0)

        # Find decisions that this one might depend on (earlier decisions on same systems)
        dependencies = []
        for d in decisions:
            if d.get("id") == decision_id:
                break
            d_safety = d.get("safety_metadata", {})
            d_systems = d_safety.get("affected_systems", [])
            overlap = set(target_systems) & set(d_systems)
            if overlap:
                dependencies.append({
                    "id": d.get("id"),
                    "decision": d.get("decision"),
                    "risk_level": d_safety.get("risk_level", "low"),
                    "shared_systems": list(overlap),
                })

        return {
            "project": project,
            "decision": {
                "id": decision_id,
                "decision": target_decision.get("decision"),
                "context": target_decision.get("context"),
                "risk_level": target_risk,
                "risk_score": risk_score,
                "safety_category": target_safety.get("safety_category", "general"),
                "affected_systems": target_systems,
                "requires_review": target_safety.get("requires_review", False),
                "timestamp": target_decision.get("timestamp"),
            },
            "impact_summary": {
                "related_decisions_count": len(related_decisions),
                "affected_systems_count": len(target_systems),
                "dependency_count": len(dependencies),
            },
            "related_decisions": related_decisions[:10],  # Top 10
            "dependencies": dependencies[:5],  # Top 5
            "system_group": system_group,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("decision-impact/%s failed: %s", decision_id, e)
        raise HTTPException(500, f"Decision impact detail failed: {e}")


# ============================
#  Safety Review Workflow
# ============================


class SafetyReviewRequest(BaseModel):
    """Request model for safety review operations."""
    reviewer: str = Field(..., max_length=100)
    status: str = Field(..., pattern=r"^(approved|rejected|needs_info|deferred)$")
    comments: str = Field("", max_length=2000)
    risk_assessment: str = Field("", max_length=1000)
    mitigation_suggestions: list[str] = Field(default_factory=list)


class SafetyReviewResponse(BaseModel):
    """Response model for safety review operations."""
    decision_id: str
    reviewer: str
    status: str
    timestamp: str
    comments: str
    risk_assessment: str
    mitigation_suggestions: list[str]


@app.post("/api/memory/{project}/decisions/{decision_id}/review")
async def submit_safety_review(
    project: str,
    decision_id: str,
    review: SafetyReviewRequest,
):
    """Submit a safety review for a decision.
    
    Records reviewer assessment, approval status, and mitigation suggestions.
    Updates the decision's safety metadata with review information.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Find the decision
        decision_found = False
        for d in decisions:
            if d.get("id") == decision_id:
                decision_found = True

                # Initialize safety_reviews if not present
                if "safety_reviews" not in d:
                    d["safety_reviews"] = []

                # Add the review
                review_entry = {
                    "reviewer": review.reviewer,
                    "status": review.status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "comments": review.comments,
                    "risk_assessment": review.risk_assessment,
                    "mitigation_suggestions": review.mitigation_suggestions,
                }
                d["safety_reviews"].append(review_entry)

                # Update requires_review based on status
                if review.status in ["approved", "rejected"]:
                    if "safety_metadata" not in d:
                        d["safety_metadata"] = {}
                    d["safety_metadata"]["requires_review"] = False

                _append_audit_event(
                    memory,
                    "review_submitted",
                    decision_id=decision_id,
                    reviewer=review.reviewer,
                    status=review.status,
                )

                # Save updated memory
                mm.save_project_memory(project, memory)
                break

        if not decision_found:
            raise HTTPException(status_code=404, detail="Decision not found")

        return {
            "success": True,
            "decision_id": decision_id,
            "review": {
                "reviewer": review.reviewer,
                "status": review.status,
                "timestamp": review_entry["timestamp"],
                "comments": review.comments,
                "risk_assessment": review.risk_assessment,
                "mitigation_suggestions": review.mitigation_suggestions,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("submit_safety_review failed: %s", e)
        raise HTTPException(500, f"Review submission failed: {e}")


def _persona_market_risk_categories(project: str, memory: dict) -> dict[str, str]:
    """Categories where this project's own persona is a known weakness AND
    Decision Market calibration is poor — the compounding signal from
    Personas + Decision Market. Neither alone is enough to auto-flag (every
    project has *some* weak category and *some* mediocre bet); both together
    is a real "poor track record here" signal worth surfacing.

    Returns {category: reason}. Empty dict if no persona/market data exists
    yet for this project — both are optional, seeded-on-use features.
    """
    try:
        from core.agent_skills import AgentSkillGraph
        from core.personas import Err as PersonaErr
        from core.personas.persona_builder import build_persona, suggest_review_focus
        from core.market import Err as MarketErr
        from core.market.calibration import compute_calibration

        graph = AgentSkillGraph(str(BASE_DIR))
        if not graph._skills_file(project).exists():
            return {}
        agent_skills = graph._load(project)
        persona_result = build_persona(agent_skills, project)
        if isinstance(persona_result, PersonaErr):
            return {}
        persona = persona_result.value
        weak_categories = set(suggest_review_focus(persona).focus_areas)
        if not weak_categories:
            return {}

        bets = memory.get("market", {}).get("bets", [])
        calibration_result = compute_calibration(bets, project)
        if isinstance(calibration_result, MarketErr):
            return {}
        category_scores = calibration_result.value.category_scores

        return {
            cat: f"persona weakness + {category_scores[cat]:.0%} bet accuracy in '{cat}'"
            for cat in weak_categories
            if category_scores.get(cat, 1.0) < 0.5
        }
    except Exception as exc:
        logger.warning("persona/market risk lookup failed for '%s': %s", project, exc)
        return {}


def _apply_persona_market_escalation(project: str, memory: dict, mm) -> int:
    """Auto-flag decisions touching a persona+market compounding-risk
    category for review, if not already flagged. Mutates memory in place,
    saves if anything changed, returns count newly escalated.
    """
    risk_categories = _persona_market_risk_categories(project, memory)
    if not risk_categories:
        return 0

    escalated = 0
    for d in memory.get("decisions", []):
        safety = d.setdefault("safety_metadata", {})
        if safety.get("requires_review"):
            continue
        # A human already reviewed this decision at least once — respect
        # that resolution rather than re-flagging it every time this signal
        # is re-evaluated. Without this, approving a decision (which sets
        # requires_review=False) just gets undone on the next pending-reviews
        # load as long as the persona/market risk category still applies,
        # so it never actually leaves the queue.
        if d.get("safety_reviews"):
            continue
        touched = {safety.get("safety_category", "general"), *safety.get("affected_systems", [])}
        matched = touched & risk_categories.keys()
        if not matched:
            continue
        safety["requires_review"] = True
        safety["escalation_reason"] = risk_categories[next(iter(matched))]
        if safety.get("risk_level", "low") == "low":
            safety["risk_level"] = "medium"
        escalated += 1

    if escalated:
        mm.save_project_memory(project, memory)
    return escalated


@app.get("/api/memory/{project}/reviews/pending")
async def get_pending_reviews(project: str):
    """Get all decisions requiring safety review.

    Returns decisions marked for review, sorted by risk level and timestamp.
    Decisions touching a category where this project's own persona has a
    known weakness *and* Decision Market calibration is poor are
    auto-escalated here too, not just ones explicitly flagged at capture time.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        _apply_persona_market_escalation(project, memory, mm)
        decisions = memory.get("decisions", [])

        pending_reviews = []
        for d in decisions:
            safety = d.get("safety_metadata", {})
            if safety.get("requires_review", False):
                reviews = d.get("safety_reviews", [])
                review_count = len(reviews)
                last_review = reviews[-1] if reviews else None

                pending_reviews.append({
                    "id": d.get("id"),
                    "decision": d.get("decision"),
                    "context": d.get("context"),
                    "risk_level": safety.get("risk_level", "low"),
                    "safety_category": safety.get("safety_category", "general"),
                    "affected_systems": safety.get("affected_systems", []),
                    "timestamp": d.get("timestamp"),
                    "review_count": review_count,
                    "last_review": last_review,
                    "alignment_considerations": safety.get("alignment_considerations", ""),
                    "escalation_reason": safety.get("escalation_reason"),
                })

        # Sort by risk level (high/critical first)
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        pending_reviews.sort(key=lambda x: risk_order.get(x["risk_level"], 4))

        return {
            "project": project,
            "pending_reviews": pending_reviews,
            "total_pending": len(pending_reviews),
        }
    except Exception as e:
        logger.error("get_pending_reviews failed: %s", e)
        raise HTTPException(500, f"Failed to get pending reviews: {e}")


def _content_flagged_detail(d: dict[str, Any]) -> str:
    """Build the Needs Attention detail string for a content_flagged item.
    Defensive against malformed persisted content_flags -- this reads
    memory written by list_flagged_decisions' own already-validated
    filter, but treats it as agent-supplied/persisted data anyway rather
    than assuming its own upstream shape held (#58's scheduler work hit
    this exact class of gap)."""
    flags = d.get("content_flags")
    if not isinstance(flags, list) or not flags:
        return "possible injected instruction"
    first = flags[0]
    pattern = first.get("pattern", "unknown") if isinstance(first, dict) else "unknown"
    detail = f"possible injected instruction ({pattern})"
    if len(flags) > 1:
        detail += f" +{len(flags) - 1} more"
    return detail


@app.get("/api/memory/{project}/needs-attention")
async def get_needs_attention(project: str) -> dict[str, Any]:
    """Aggregate everything in this project currently waiting on a human —
    feeds the dashboard's Overview-page Needs Attention panel.

    Deliberately not a one-time setup checklist: this reflects live state
    and is meant to be revisited, not completed once. Reuses the existing
    pending-reviews and untagged-decisions endpoints rather than
    re-deriving their logic, so this stays a thin aggregation layer as more
    sources get added (e.g. a future promotion of a core/triggers check
    from severity="warn" to "block").
    """
    pending = await get_pending_reviews(project)
    untagged = await list_untagged_decisions(project)
    decayed = await list_decay_reviews(project, status="pending")
    flagged = await list_flagged_decisions(project)
    unacked_handoffs = await list_unacknowledged_handoffs(project)

    items = [
        {
            "kind": "pending_review",
            "id": r["id"],
            "label": r["decision"],
            "detail": r.get("escalation_reason") or f"{r['risk_level']} risk — needs a reviewer",
        }
        for r in pending["pending_reviews"]
    ] + [
        {
            "kind": "untagged_decision",
            "id": d.get("id"),
            "label": d.get("decision"),
            # A decision can carry safety_reviews (already been through the
            # review workflow) and still show up here, since requires_review
            # and safety_category are independent flags -- without this
            # note it reads as "I just handled this, why is it still here"
            # when what's actually true is a second, unrelated gap.
            "detail": (
                "already reviewed — still needs a safety category"
                if d.get("safety_reviews")
                else "no safety category set"
            ),
        }
        for d in untagged["decisions"]
    ] + [
        {
            "kind": "decayed_decision",
            "id": r.get("id"),
            "label": r.get("decision"),
            # Informational only here, same as pending_review -- act on it
            # from the Confidence tab (pin/attest/dismiss), not inline.
            "detail": (
                f"confidence decayed to '{r.get('tier')}' "
                f"but still referenced by {r.get('reference_count', 0)} other decision(s)"
            ),
        }
        for r in decayed["decay_reviews"]
    ] + [
        {
            "kind": "content_flagged",
            "id": d.get("id"),
            "label": d.get("decision"),
            # Informational only here too -- review the flagged text
            # directly (GET /decisions/flagged), no inline action.
            "detail": _content_flagged_detail(d),
        }
        for d in flagged["decisions"]
    ] + [
        {
            "kind": "unacknowledged_handoff",
            "id": h.get("packet_hash"),
            "label": f"Handoff to '{h.get('role')}' role",
            # Informational only -- acknowledge via
            # POST /handoff/acknowledge, no inline action here.
            "detail": f"generated for {h.get('agent_name', 'unspecified')}, not yet acknowledged",
        }
        for h in unacked_handoffs["handoffs"]
    ]

    return {"items": items, "count": len(items)}


@app.get("/api/memory/{project}/reviews/history")
async def get_review_history(
    project: str,
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None, pattern=r"^(approved|rejected|needs_info|deferred)$"),
):
    """Get review history for a project.
    
    Returns past reviews with optional filtering by status.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        review_history = []
        for d in decisions:
            reviews = d.get("safety_reviews", [])
            for review in reviews:
                if status and review.get("status") != status:
                    continue

                review_history.append({
                    "decision_id": d.get("id"),
                    "decision": d.get("decision"),
                    "reviewer": review.get("reviewer"),
                    "status": review.get("status"),
                    "timestamp": review.get("timestamp"),
                    "comments": review.get("comments"),
                    "risk_level": d.get("safety_metadata", {}).get("risk_level", "low"),
                })

        # Sort by timestamp (most recent first)
        review_history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return {
            "project": project,
            "review_history": review_history[:limit],
            "total_reviews": len(review_history),
        }
    except Exception as e:
        logger.error("get_review_history failed: %s", e)
        raise HTTPException(500, f"Failed to get review history: {e}")


@app.get("/api/memory/{project}/reviews/stats")
async def get_review_stats(project: str):
    """Get review statistics for a project.
    
    Returns aggregated review metrics including approval rates,
    reviewer activity, and average review time.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Initialize counters
        status_counts = {"approved": 0, "rejected": 0, "needs_info": 0, "deferred": 0}
        reviewer_counts = {}
        review_times = []
        total_reviews = 0

        for d in decisions:
            reviews = d.get("safety_reviews", [])
            decision_timestamp = d.get("timestamp")

            for review in reviews:
                total_reviews += 1
                status = review.get("status", "needs_info")
                reviewer = review.get("reviewer", "unknown")
                review_timestamp = review.get("timestamp")

                # Count by status
                status_counts[status] = status_counts.get(status, 0) + 1

                # Count by reviewer
                reviewer_counts[reviewer] = reviewer_counts.get(reviewer, 0) + 1

                # Calculate review time if timestamps available
                if decision_timestamp and review_timestamp:
                    try:
                        from datetime import datetime
                        dt_dec = datetime.fromisoformat(decision_timestamp.replace("Z", "+00:00"))
                        dt_rev = datetime.fromisoformat(review_timestamp.replace("Z", "+00:00"))
                        review_time_hours = (dt_rev - dt_dec).total_seconds() / 3600
                        review_times.append(review_time_hours)
                    except (ValueError, TypeError):
                        pass

        # Calculate statistics
        avg_review_time = sum(review_times) / len(review_times) if review_times else 0
        approval_rate = status_counts.get("approved", 0) / total_reviews if total_reviews > 0 else 0

        # Find most active reviewers
        top_reviewers = sorted(reviewer_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "project": project,
            "total_reviews": total_reviews,
            "status_distribution": status_counts,
            "approval_rate": round(approval_rate, 3),
            "avg_review_time_hours": round(avg_review_time, 2),
            "top_reviewers": [{"reviewer": r, "count": c} for r, c in top_reviewers],
            "pending_decisions": sum(1 for d in decisions if d.get("safety_metadata", {}).get("requires_review", False)),
        }
    except Exception as e:
        logger.error("get_review_stats failed: %s", e)
        raise HTTPException(500, f"Failed to get review stats: {e}")


@app.post("/api/memory/{project}/decisions/{decision_id}/approve")
async def approve_decision(
    project: str,
    decision_id: str,
    reviewer: str = Query(..., max_length=100),
    comments: str = Query("", max_length=2000),
):
    """Quick-approve a decision (convenience endpoint)."""
    review = SafetyReviewRequest(
        reviewer=reviewer,
        status="approved",
        comments=comments,
    )
    return await submit_safety_review(project, decision_id, review)


@app.post("/api/memory/{project}/decisions/{decision_id}/reject")
async def reject_decision(
    project: str,
    decision_id: str,
    reviewer: str = Query(..., max_length=100),
    comments: str = Query("", max_length=2000),
    risk_assessment: str = Query("", max_length=1000),
):
    """Quick-reject a decision (convenience endpoint)."""
    review = SafetyReviewRequest(
        reviewer=reviewer,
        status="rejected",
        comments=comments,
        risk_assessment=risk_assessment,
    )
    return await submit_safety_review(project, decision_id, review)


# ============================
#  Alignment Evaluation & Governance
# ============================


class AlignmentCriteria(BaseModel):
    """Criteria for evaluating alignment of a decision."""
    name: str = Field(..., max_length=100)
    description: str = Field("", max_length=500)
    weight: float = Field(1.0, ge=0.0, le=10.0)
    category: str = Field("general", pattern=r"^(general|robustness|interpretability|fairness|safety|governance)$")


class AlignmentEvaluationRequest(BaseModel):
    """Request model for alignment evaluation."""
    criteria: list[AlignmentCriteria] = Field(default_factory=list)
    include_governance_check: bool = True
    include_safety_case: bool = False


class GovernancePolicy(BaseModel):
    """Governance policy definition."""
    name: str = Field(..., max_length=100)
    description: str = Field("", max_length=500)
    required: bool = Field(True)
    category: str = Field("general", max_length=50)


# Default alignment criteria
DEFAULT_ALIGNMENT_CRITERIA = [
    {"name": "transparency", "description": "Is the decision rationale clearly documented?", "weight": 1.0, "category": "interpretability"},
    {"name": "reversibility", "description": "Can this decision be easily reversed if needed?", "weight": 0.8, "category": "safety"},
    {"name": "stakeholder_impact", "description": "Have all stakeholder impacts been considered?", "weight": 1.2, "category": "fairness"},
    {"name": "risk_documentation", "description": "Are risks clearly documented and mitigated?", "weight": 1.0, "category": "robustness"},
    {"name": "governance_compliance", "description": "Does the decision comply with governance policies?", "weight": 1.5, "category": "governance"},
]


@app.get("/api/memory/{project}/alignment/evaluate")
async def evaluate_alignment(project: str):
    """Evaluate all decisions against default alignment criteria.
    
    Returns a project-wide alignment score and per-decision evaluations.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        criteria = DEFAULT_ALIGNMENT_CRITERIA
        evaluations = []

        for d in decisions:
            safety = d.get("safety_metadata", {})
            eval_result = _evaluate_decision_alignment(d, criteria)
            evaluations.append(eval_result)

        # Calculate project-wide alignment score
        if evaluations:
            avg_score = sum(e["alignment_score"] for e in evaluations) / len(evaluations)
            passing = sum(1 for e in evaluations if e["alignment_score"] >= 0.7)
            failing = len(evaluations) - passing
        else:
            avg_score = 1.0
            passing = 0
            failing = 0

        # Category breakdown: average each category's own criterion score,
        # not the decision's overall blended alignment_score (every decision
        # is evaluated against all 5 categories, so filtering evaluations by
        # "has this category" always matched everything and collapsed all
        # five categories to the same number).
        category_scores = {}
        for cat in ["interpretability", "safety", "fairness", "robustness", "governance"]:
            cat_criterion_scores = [
                c["score"]
                for e in evaluations
                for c in e["criteria_evaluated"]
                if c["category"] == cat
            ]
            if cat_criterion_scores:
                category_scores[cat] = round(sum(cat_criterion_scores) / len(cat_criterion_scores), 3)
            else:
                category_scores[cat] = 1.0

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "alignment_score": round(avg_score, 3),
                "passing_count": passing,
                "failing_count": failing,
                "pass_rate": round(passing / len(decisions), 3) if decisions else 1.0,
            },
            "category_scores": category_scores,
            "criteria_used": criteria,
            "evaluations": evaluations[:20],  # Top 20 most recent
        }
    except Exception as e:
        logger.error("alignment evaluate failed: %s", e)
        raise HTTPException(500, f"Alignment evaluation failed: {e}")


@app.post("/api/memory/{project}/decisions/{decision_id}/alignment")
async def evaluate_decision_alignment(
    project: str,
    decision_id: str,
    request: AlignmentEvaluationRequest,
):
    """Evaluate a specific decision against alignment criteria.
    
    Returns detailed alignment evaluation with criteria scoring.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Find the decision
        target_decision = None
        for d in decisions:
            if d.get("id") == decision_id:
                target_decision = d
                break

        if not target_decision:
            raise HTTPException(status_code=404, detail="Decision not found")

        criteria = request.criteria if request.criteria else DEFAULT_ALIGNMENT_CRITERIA
        eval_result = _evaluate_decision_alignment(target_decision, criteria)

        # Governance check
        governance_result = None
        if request.include_governance_check:
            governance_result = _check_governance_compliance(target_decision)

        # Safety case
        safety_case = None
        if request.include_safety_case:
            safety_case = _build_safety_case(target_decision, eval_result)

        return {
            "project": project,
            "decision_id": decision_id,
            "evaluation": eval_result,
            "governance_check": governance_result,
            "safety_case": safety_case,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("alignment evaluate/%s failed: %s", decision_id, e)
        raise HTTPException(500, f"Decision alignment evaluation failed: {e}")


@app.get("/api/memory/{project}/governance/policies")
async def get_governance_policies(project: str):
    """Get governance policies for a project.
    
    Returns default policies and any project-specific overrides.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)

        # Default governance policies
        default_policies = [
            {"name": "risk_review_required", "description": "High-risk decisions require explicit review", "required": True, "category": "risk_management"},
            {"name": "reversibility_assessment", "description": "Irreversible decisions must document justification", "required": True, "category": "safety"},
            {"name": "stakeholder_documentation", "description": "Affected stakeholders must be identified", "required": True, "category": "fairness"},
            {"name": "alignment_consideration", "description": "Alignment implications must be documented", "required": False, "category": "alignment"},
            {"name": "rollback_plan", "description": "Critical decisions should have rollback plans", "required": False, "category": "robustness"},
        ]

        # Get project-specific policies if any
        project_policies = memory.get("governance_policies", [])

        return {
            "project": project,
            "default_policies": default_policies,
            "project_policies": project_policies,
            "total_policies": len(default_policies) + len(project_policies),
        }
    except Exception as e:
        logger.error("governance/policies failed: %s", e)
        raise HTTPException(500, f"Failed to get governance policies: {e}")


@app.get("/api/memory/{project}/governance/compliance")
async def get_governance_compliance(project: str):
    """Check governance compliance for all decisions.
    
    Returns compliance status against governance policies.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        compliance_results = []
        for d in decisions:
            result = _check_governance_compliance(d)
            compliance_results.append(result)

        # Aggregate stats
        total = len(compliance_results)
        compliant = sum(1 for r in compliance_results if r["compliant"])
        non_compliant = total - compliant

        # Policy violation breakdown
        policy_violations = {}
        for r in compliance_results:
            for violation in r["violations"]:
                policy_name = violation["policy"]
                policy_violations[policy_name] = policy_violations.get(policy_name, 0) + 1

        return {
            "project": project,
            "summary": {
                "total_decisions": total,
                "compliant_count": compliant,
                "non_compliant_count": non_compliant,
                "compliance_rate": round(compliant / total, 3) if total > 1.0 else 1.0,
            },
            "policy_violations": policy_violations,
            "decisions": compliance_results[:20],  # Top 20
        }
    except Exception as e:
        logger.error("governance/compliance failed: %s", e)
        raise HTTPException(500, f"Governance compliance check failed: {e}")


@app.get("/api/memory/{project}/interpretability/{decision_id}")
async def get_interpretability_report(project: str, decision_id: str):
    """Generate an interpretability report for a decision.
    
    Returns a human-readable explanation of the decision rationale and factors.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Find the decision
        target_decision = None
        for d in decisions:
            if d.get("id") == decision_id:
                target_decision = d
                break

        if not target_decision:
            raise HTTPException(status_code=404, detail="Decision not found")

        report = _generate_interpretability_report(target_decision)

        return {
            "project": project,
            "decision_id": decision_id,
            "report": report,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("interpretability/%s failed: %s", decision_id, e)
        raise HTTPException(500, f"Interpretability report failed: {e}")


# Helper functions for alignment evaluation

def _evaluate_decision_alignment(decision: dict, criteria: list) -> dict:
    """Evaluate a decision against alignment criteria."""
    safety = decision.get("safety_metadata", {})
    criteria_evaluated = []
    total_score = 0.0
    total_weight = 0.0

    for criterion in criteria:
        # Handle both dict and Pydantic model inputs
        if hasattr(criterion, "model_dump"):
            c = criterion.model_dump()
        elif hasattr(criterion, "__dict__"):
            c = criterion.__dict__
        else:
            c = criterion

        name = c.get("name", "") if isinstance(c, dict) else getattr(criterion, "name", "")
        weight = c.get("weight", 1.0) if isinstance(c, dict) else getattr(criterion, "weight", 1.0)
        category = c.get("category", "general") if isinstance(c, dict) else getattr(criterion, "category", "general")

        # Score based on criteria type
        score = _score_criterion(name, decision, safety)

        criteria_evaluated.append({
            "name": name,
            "category": category,
            "score": score,
            "weight": weight,
            "weighted_score": round(score * weight, 3),
        })

        total_score += score * weight
        total_weight += weight

    alignment_score = round(total_score / total_weight, 3) if total_weight > 0 else 1.0

    return {
        "decision_id": decision.get("id"),
        "decision": decision.get("decision"),
        "alignment_score": alignment_score,
        "criteria_evaluated": criteria_evaluated,
        "passing": alignment_score >= 0.7,
    }


def _score_criterion(criterion_name: str, decision: dict, safety: dict) -> float:
    """Score a decision against a specific criterion."""
    if criterion_name == "transparency":
        # Check if rationale is documented
        context = decision.get("context", "")
        return 1.0 if len(context) > 10 else 0.3

    elif criterion_name == "reversibility":
        # Check reversibility metadata
        return 1.0 if safety.get("reversibility", True) else 0.4

    elif criterion_name == "stakeholder_impact":
        # Check if affected systems are documented
        systems = safety.get("affected_systems", [])
        return min(1.0, 0.5 + len(systems) * 0.1)

    elif criterion_name == "risk_documentation":
        # Check if risk level is documented
        risk_level = safety.get("risk_level", "low")
        return 1.0 if risk_level != "low" or safety.get("requires_review") else 0.6

    elif criterion_name == "governance_compliance":
        # Check review requirements
        if safety.get("requires_review", False):
            reviews = decision.get("safety_reviews", [])
            return 1.0 if reviews else 0.3
        return 0.8

    return 0.7  # Default moderate score


def _check_governance_compliance(decision: dict) -> dict:
    """Check a decision against governance policies."""
    safety = decision.get("safety_metadata", {})
    violations = []

    # Policy: High-risk decisions require review
    if safety.get("risk_level") in ["high", "critical"] and not decision.get("safety_reviews"):
        violations.append({
            "policy": "risk_review_required",
            "severity": "high",
            "message": "High-risk decision lacks review",
        })

    # Policy: Irreversible decisions need justification
    if not safety.get("reversibility", True) and not safety.get("alignment_considerations"):
        violations.append({
            "policy": "reversibility_assessment",
            "severity": "medium",
            "message": "Irreversible decision lacks justification",
        })

    # Policy: Affected systems should be documented
    if not safety.get("affected_systems"):
        violations.append({
            "policy": "stakeholder_documentation",
            "severity": "low",
            "message": "No affected systems documented",
        })

    return {
        "decision_id": decision.get("id"),
        "decision": decision.get("decision"),
        "compliant": len(violations) == 0,
        "violations": violations,
        "violation_count": len(violations),
    }


def _generate_interpretability_report(decision: dict) -> dict:
    """Generate an interpretability report for a decision."""
    safety = decision.get("safety_metadata", {})

    # Extract key factors
    factors = []
    if decision.get("context"):
        factors.append({"factor": "rationale", "value": decision["context"], "type": "documented"})
    if safety.get("risk_level"):
        factors.append({"factor": "risk_level", "value": safety["risk_level"], "type": "classified"})
    if safety.get("affected_systems"):
        factors.append({"factor": "affected_systems", "value": ", ".join(safety["affected_systems"]), "type": "documented"})
    if safety.get("alignment_considerations"):
        factors.append({"factor": "alignment", "value": safety["alignment_considerations"], "type": "documented"})

    # Generate explanation
    explanation_parts = [f"Decision: {decision.get('decision', 'Unknown')}"]
    if decision.get("context"):
        explanation_parts.append(f"Rationale: {decision['context']}")
    if safety.get("risk_level", "low") != "low":
        explanation_parts.append(f"Risk Level: {safety['risk_level']}")
    if safety.get("requires_review"):
        explanation_parts.append("This decision requires safety review.")

    return {
        "decision_id": decision.get("id"),
        "timestamp": decision.get("timestamp"),
        "factors": factors,
        "explanation": " | ".join(explanation_parts),
        "completeness_score": min(1.0, len(factors) * 0.25),
    }


def _build_safety_case(decision: dict, evaluation: dict) -> dict:
    """Build a structured safety case for a decision."""
    safety = decision.get("safety_metadata", {})

    # Claims
    claims = []
    if evaluation.get("alignment_score", 0) >= 0.7:
        claims.append({"claim": "Decision meets alignment criteria", "confidence": evaluation["alignment_score"]})
    if safety.get("reversibility", True):
        claims.append({"claim": "Decision is reversible", "confidence": 1.0})

    # Evidence
    evidence = []
    if decision.get("context"):
        evidence.append({"type": "documentation", "content": decision["context"]})
    if safety.get("safety_reviews"):
        evidence.append({"type": "review", "content": f"Reviewed by {len(safety['safety_reviews'])} reviewers"})

    # Assumptions
    assumptions = []
    if safety.get("risk_level") in ["high", "critical"]:
        assumptions.append("Risk mitigation measures are in place")

    return {
        "decision_id": decision.get("id"),
        "claims": claims,
        "evidence": evidence,
        "assumptions": assumptions,
        "overall_confidence": evaluation.get("alignment_score", 0.5),
    }


# ============================
#  Cross-Cutting Features
# ============================


@app.get("/api/memory/{project}/compliance/report")
async def get_compliance_report(project: str, framework: str = Query("eu_ai_act", pattern=r"^(eu_ai_act|nist|iso_42001|general)$")):
    """Generate compliance report for regulatory frameworks.
    
    Supports: EU AI Act, NIST AI RMF, ISO 42001, and general compliance.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Framework-specific requirements
        requirements = _get_compliance_requirements(framework)
        
        # Evaluate each requirement
        requirement_results = []
        for req in requirements:
            result = _evaluate_compliance_requirement(req, decisions)
            requirement_results.append(result)

        # Calculate overall compliance
        total = len(requirement_results)
        compliant = sum(1 for r in requirement_results if r["status"] == "compliant")
        partial = sum(1 for r in requirement_results if r["status"] == "partial")
        non_compliant = sum(1 for r in requirement_results if r["status"] == "non_compliant")

        # Generate gaps
        gaps = [r for r in requirement_results if r["status"] != "compliant"]

        return {
            "project": project,
            "framework": framework,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_requirements": total,
                "compliant": compliant,
                "partial": partial,
                "non_compliant": non_compliant,
                "compliance_score": round(compliant / total, 3) if total > 0 else 1.0,
            },
            "requirements": requirement_results,
            "gaps": gaps,
            "recommendations": _generate_compliance_recommendations(gaps),
        }
    except Exception as e:
        logger.error("compliance report failed: %s", e)
        raise HTTPException(500, f"Compliance report failed: {e}")


@app.post("/api/memory/{project}/decisions/{decision_id}/version")
async def create_decision_version(
    project: str,
    decision_id: str,
    change_reason: str = Query("", max_length=500),
):
    """Create a new version of a decision.
    
    Stores the current state as a version before any modifications.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Find the decision
        target_decision = None
        for d in decisions:
            if d.get("id") == decision_id:
                target_decision = d
                break

        if not target_decision:
            raise HTTPException(status_code=404, detail="Decision not found")

        # Initialize version history if not present
        if "version_history" not in target_decision:
            target_decision["version_history"] = []

        # Create version snapshot
        version = {
            "version": len(target_decision["version_history"]) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": target_decision.get("decision"),
            "context": target_decision.get("context"),
            "safety_metadata": target_decision.get("safety_metadata", {}),
            "change_reason": change_reason,
        }

        target_decision["version_history"].append(version)

        _append_audit_event(
            memory,
            "version_created",
            decision_id=decision_id,
            version=version["version"],
            change_reason=change_reason,
        )

        # Save
        mm.save_project_memory(project, memory)

        return {
            "success": True,
            "decision_id": decision_id,
            "version": version["version"],
            "total_versions": len(target_decision["version_history"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("create version failed: %s", e)
        raise HTTPException(500, f"Version creation failed: {e}")


@app.get("/api/memory/{project}/decisions/{decision_id}/versions")
async def get_decision_versions(project: str, decision_id: str):
    """Get version history for a decision."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Find the decision
        target_decision = None
        for d in decisions:
            if d.get("id") == decision_id:
                target_decision = d
                break

        if not target_decision:
            raise HTTPException(status_code=404, detail="Decision not found")

        versions = target_decision.get("version_history", [])

        return {
            "project": project,
            "decision_id": decision_id,
            "current_version": len(versions) + 1,
            "versions": versions,
            "total_versions": len(versions),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get versions failed: %s", e)
        raise HTTPException(500, f"Get versions failed: {e}")


@app.post("/api/memory/{project}/decisions/{decision_id}/rollback/{version}")
async def rollback_decision(project: str, decision_id: str, version: int):
    """Rollback a decision to a previous version."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Find the decision
        target_decision = None
        for d in decisions:
            if d.get("id") == decision_id:
                target_decision = d
                break

        if not target_decision:
            raise HTTPException(status_code=404, detail="Decision not found")

        versions = target_decision.get("version_history", [])
        
        # Find the target version
        target_version = None
        for v in versions:
            if v.get("version") == version:
                target_version = v
                break

        if not target_version:
            raise HTTPException(status_code=404, detail=f"Version {version} not found")

        # Save current state as a version before rollback
        current_version = {
            "version": len(versions) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": target_decision.get("decision"),
            "context": target_decision.get("context"),
            "safety_metadata": target_decision.get("safety_metadata", {}),
            "change_reason": f"Rollback to version {version}",
        }
        versions.append(current_version)

        # Apply rollback
        target_decision["decision"] = target_version["decision"]
        target_decision["context"] = target_version["context"]
        target_decision["safety_metadata"] = target_version.get("safety_metadata", {})

        # Save
        mm.save_project_memory(project, memory)

        return {
            "success": True,
            "decision_id": decision_id,
            "rolled_back_to": version,
            "new_version": len(versions) + 1,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rollback failed: %s", e)
        raise HTTPException(500, f"Rollback failed: {e}")


@app.get("/api/memory/{project}/stakeholder-impact")
async def get_stakeholder_impact(project: str):
    """Get stakeholder impact matrix for all decisions.
    
    Returns a matrix showing which systems/stakeholders are affected by which decisions.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Build impact matrix
        impact_matrix = {}
        decision_impacts = []

        for d in decisions:
            safety = d.get("safety_metadata", {})
            systems = safety.get("affected_systems", [])
            risk_level = safety.get("risk_level", "low")

            decision_entry = {
                "id": d.get("id"),
                "decision": d.get("decision"),
                "risk_level": risk_level,
                "affected_systems": systems,
                "timestamp": d.get("timestamp"),
            }
            decision_impacts.append(decision_entry)

            # Update impact matrix
            for system in systems:
                if system not in impact_matrix:
                    impact_matrix[system] = {
                        "decision_count": 0,
                        "high_risk_count": 0,
                        "decisions": [],
                    }
                impact_matrix[system]["decision_count"] += 1
                if risk_level in ["high", "critical"]:
                    impact_matrix[system]["high_risk_count"] += 1
                impact_matrix[system]["decisions"].append(d.get("id"))

        # Sort systems by impact (most impacted first)
        sorted_systems = sorted(
            impact_matrix.items(),
            key=lambda x: x[1]["decision_count"],
            reverse=True,
        )

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "total_systems": len(impact_matrix),
                "most_impacted_systems": [s[0] for s in sorted_systems[:5]],
            },
            "impact_matrix": dict(sorted_systems),
            "decisions": decision_impacts,
        }
    except Exception as e:
        logger.error("stakeholder impact failed: %s", e)
        raise HTTPException(500, f"Stakeholder impact analysis failed: {e}")


@app.get("/api/memory/{project}/risk-heatmap")
async def get_risk_heatmap(project: str):
    """Get risk heatmap data for visualization.
    
    Returns risk distribution across time and categories for heatmap rendering.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Build heatmap data
        heatmap_data = []
        risk_by_category = {}
        risk_by_month = {}

        for d in decisions:
            safety = d.get("safety_metadata", {})
            risk_level = safety.get("risk_level", "low")
            category = safety.get("safety_category", "general")
            timestamp = d.get("timestamp", "")

            # Risk by category
            if category not in risk_by_category:
                risk_by_category[category] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            risk_by_category[category][risk_level] = risk_by_category[category].get(risk_level, 0) + 1

            # Risk by month
            if timestamp:
                month_key = timestamp[:7]
                if month_key not in risk_by_month:
                    risk_by_month[month_key] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
                risk_by_month[month_key][risk_level] = risk_by_month[month_key].get(risk_level, 0) + 1

            # Individual decision heatmap entry
            heatmap_data.append({
                "id": d.get("id"),
                "decision": d.get("decision"),
                "risk_level": risk_level,
                "category": category,
                "timestamp": timestamp,
                "risk_score": {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}.get(risk_level, 0),
            })

        # Sort heatmap data by risk score (highest first)
        heatmap_data.sort(key=lambda x: x["risk_score"], reverse=True)

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "high_risk_count": sum(1 for d in heatmap_data if d["risk_level"] in ["high", "critical"]),
                "categories": list(risk_by_category.keys()),
                "months": sorted(risk_by_month.keys()),
            },
            "heatmap": heatmap_data[:50],  # Top 50 for visualization
            "risk_by_category": risk_by_category,
            "risk_by_month": risk_by_month,
        }
    except Exception as e:
        logger.error("risk heatmap failed: %s", e)
        raise HTTPException(500, f"Risk heatmap failed: {e}")


@app.post("/api/memory/{project}/safety-check")
async def run_safety_check(project: str, decision_text: str = Query(...), context: str = Query("")):
    """Run automated safety checks on a proposed decision.
    
    Returns safety analysis before the decision is recorded.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)

        # Analyze the proposed decision
        analysis = _analyze_proposed_decision(decision_text, context, memory)

        return {
            "project": project,
            "decision_text": decision_text,
            "analysis": analysis,
            "recommendation": analysis["recommendation"],
            "safety_score": analysis["safety_score"],
            "flags": analysis["flags"],
        }
    except Exception as e:
        logger.error("safety check failed: %s", e)
        raise HTTPException(500, f"Safety check failed: {e}")


# Helper functions for cross-cutting features

def _get_compliance_requirements(framework: str) -> list:
    """Get compliance requirements for a framework."""
    if framework == "eu_ai_act":
        return [
            {"id": "EU-AI-1", "name": "Risk Management", "description": "Risk management system established", "category": "risk"},
            {"id": "EU-AI-2", "name": "Data Governance", "description": "Data governance measures implemented", "category": "data"},
            {"id": "EU-AI-3", "name": "Transparency", "description": "Transparency obligations met", "category": "transparency"},
            {"id": "EU-AI-4", "name": "Human Oversight", "description": "Human oversight measures in place", "category": "oversight"},
            {"id": "EU-AI-5", "name": "Documentation", "description": "Technical documentation maintained", "category": "documentation"},
            {"id": "EU-AI-6", "name": "Record Keeping", "description": "Automatic recording of events", "category": "logging"},
            {"id": "EU-AI-7", "name": "Accuracy & Robustness", "description": "Accuracy and robustness ensured", "category": "robustness"},
        ]
    elif framework == "nist":
        return [
            {"id": "NIST-1", "name": "Governance", "description": "AI governance policies established", "category": "governance"},
            {"id": "NIST-2", "name": "Risk Assessment", "description": "Regular risk assessments conducted", "category": "risk"},
            {"id": "NIST-3", "name": "Testing", "description": "AI systems tested for safety", "category": "testing"},
            {"id": "NIST-4", "name": "Monitoring", "description": "Continuous monitoring in place", "category": "monitoring"},
        ]
    else:  # general
        return [
            {"id": "GEN-1", "name": "Decision Documentation", "description": "All decisions documented", "category": "documentation"},
            {"id": "GEN-2", "name": "Risk Assessment", "description": "Risks assessed and documented", "category": "risk"},
            {"id": "GEN-3", "name": "Review Process", "description": "Review process for high-risk decisions", "category": "review"},
            {"id": "GEN-4", "name": "Audit Trail", "description": "Complete audit trail maintained", "category": "audit"},
        ]


def _evaluate_compliance_requirement(requirement: dict, decisions: list) -> dict:
    """Evaluate a compliance requirement against decisions."""
    req_id = requirement["id"]
    category = requirement.get("category", "")

    # Evaluate based on category
    if category == "documentation":
        documented = sum(1 for d in decisions if d.get("context"))
        total = len(decisions)
        ratio = documented / total if total > 0 else 1.0
        status = "compliant" if ratio >= 0.8 else "partial" if ratio >= 0.5 else "non_compliant"
        evidence = f"{documented}/{total} decisions documented"

    elif category == "risk":
        risk_assessed = sum(1 for d in decisions if d.get("safety_metadata", {}).get("risk_level"))
        total = len(decisions)
        ratio = risk_assessed / total if total > 0 else 1.0
        status = "compliant" if ratio >= 0.9 else "partial" if ratio >= 0.6 else "non_compliant"
        evidence = f"{risk_assessed}/{total} decisions have risk assessment"

    elif category == "review":
        high_risk = [d for d in decisions if d.get("safety_metadata", {}).get("risk_level") in ["high", "critical"]]
        reviewed = sum(1 for d in high_risk if d.get("safety_reviews"))
        total = len(high_risk)
        ratio = reviewed / total if total > 0 else 1.0
        status = "compliant" if ratio >= 0.9 else "partial" if ratio >= 0.5 else "non_compliant"
        evidence = f"{reviewed}/{total} high-risk decisions reviewed"

    elif category == "audit":
        has_safety = sum(1 for d in decisions if d.get("safety_metadata"))
        total = len(decisions)
        ratio = has_safety / total if total > 0 else 1.0
        status = "compliant" if ratio >= 0.9 else "partial" if ratio >= 0.6 else "non_compliant"
        evidence = f"{has_safety}/{total} decisions have safety metadata"

    else:
        status = "compliant"
        evidence = "Requirement evaluated"

    return {
        "requirement_id": req_id,
        "name": requirement["name"],
        "description": requirement["description"],
        "status": status,
        "evidence": evidence,
    }


def _generate_compliance_recommendations(gaps: list) -> list:
    """Generate recommendations for compliance gaps."""
    recommendations = []
    for gap in gaps:
        category = gap.get("description", "").lower()
        if "document" in category:
            recommendations.append(f"Improve documentation for: {gap['name']}")
        elif "risk" in category:
            recommendations.append(f"Conduct risk assessment for: {gap['name']}")
        elif "review" in category:
            recommendations.append(f"Implement review process for: {gap['name']}")
        else:
            recommendations.append(f"Address gap in: {gap['name']}")
    return recommendations


def _analyze_proposed_decision(decision_text: str, context: str, memory: dict) -> dict:
    """Analyze a proposed decision for safety concerns."""
    flags = []
    safety_score = 1.0

    # Check for high-risk keywords
    high_risk_keywords = ["critical", "production", "security", "emergency", "urgent", "immediate"]
    for keyword in high_risk_keywords:
        if keyword.lower() in decision_text.lower():
            flags.append(f"High-risk keyword: {keyword}")
            safety_score -= 0.1

    # Check for reversibility concerns
    irreversible_keywords = ["permanent", "irreversible", "delete", "remove", "destroy"]
    for keyword in irreversible_keywords:
        if keyword.lower() in decision_text.lower():
            flags.append(f"Irreversibility keyword: {keyword}")
            safety_score -= 0.15

    # Check context quality
    if not context or len(context) < 20:
        flags.append("Insufficient context provided")
        safety_score -= 0.2

    # Check against recent decisions
    recent_decisions = memory.get("decisions", [])[-10:]
    similar_count = 0
    for d in recent_decisions:
        if decision_text.lower() in d.get("decision", "").lower() or d.get("decision", "").lower() in decision_text.lower():
            similar_count += 1

    if similar_count > 0:
        flags.append(f"Similar decision found {similar_count} time(s) recently")
        safety_score -= 0.05

    safety_score = max(0.0, min(1.0, safety_score))

    # Determine recommendation
    if safety_score >= 0.8:
        recommendation = "Approved - Low risk"
    elif safety_score >= 0.6:
        recommendation = "Caution - Moderate risk, consider review"
    elif safety_score >= 0.4:
        recommendation = "Warning - High risk, review recommended"
    else:
        recommendation = "Critical - Very high risk, review required"

    return {
        "safety_score": round(safety_score, 3),
        "flags": flags,
        "recommendation": recommendation,
        "similar_decisions": similar_count,
    }


# ============================
#  Fairness, Accountability, Robustness Features
# ============================


@app.get("/api/memory/{project}/fairness/audit")
async def get_fairness_audit(project: str):
    """Audit decisions for fairness and bias patterns.
    
    Analyzes decisions for potential bias across:
    - Risk level distribution (are some categories over-represented as high-risk?)
    - Review patterns (are some decision types reviewed more?)
    - System impact distribution (are some systems disproportionately affected?)
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Analyze risk distribution by category
        category_risk = {}
        for d in decisions:
            safety = d.get("safety_metadata", {})
            category = safety.get("safety_category", "general")
            risk = safety.get("risk_level", "low")
            if category not in category_risk:
                category_risk[category] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            category_risk[category][risk] = category_risk[category].get(risk, 0) + 1

        # Detect bias patterns
        bias_flags = []
        risk_weights = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        for cat, risks in category_risk.items():
            total = sum(risks.values())
            if total > 0:
                weighted = sum(risks[r] * risk_weights[r] for r in risks)
                avg_risk = weighted / total
                if avg_risk > 1.5:
                    bias_flags.append({
                        "type": "elevated_risk",
                        "category": cat,
                        "avg_risk": round(avg_risk, 2),
                        "message": f"Category '{cat}' has elevated average risk ({avg_risk:.2f})",
                    })

        # Review pattern analysis
        reviewed_by_category = {}
        for d in decisions:
            safety = d.get("safety_metadata", {})
            cat = safety.get("safety_category", "general")
            if d.get("safety_reviews"):
                reviewed_by_category[cat] = reviewed_by_category.get(cat, 0) + 1

        # System impact analysis
        system_impact = {}
        for d in decisions:
            safety = d.get("safety_metadata", {})
            for system in safety.get("affected_systems", []):
                if system not in system_impact:
                    system_impact[system] = 0
                system_impact[system] += 1

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "bias_flags": len(bias_flags),
                "categories_analyzed": len(category_risk),
                "systems_analyzed": len(system_impact),
            },
            "category_risk_distribution": category_risk,
            "bias_flags": bias_flags,
            "review_patterns": reviewed_by_category,
            "system_impact_distribution": system_impact,
        }
    except Exception as e:
        logger.error("fairness audit failed: %s", e)
        raise HTTPException(500, f"Fairness audit failed: {e}")


@app.get("/api/memory/{project}/accountability/report")
async def get_accountability_report(project: str):
    """Generate accountability report showing decision chains and responsibility.
    
    Tracks:
    - Who reviewed what
    - Decision chains (what caused what)
    - Accountability gaps (unreviewed high-risk decisions)
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Build reviewer accountability
        reviewer_stats = {}
        for d in decisions:
            for review in d.get("safety_reviews", []):
                reviewer = review.get("reviewer", "unknown")
                if reviewer not in reviewer_stats:
                    reviewer_stats[reviewer] = {"total_reviews": 0, "approved": 0, "rejected": 0}
                reviewer_stats[reviewer]["total_reviews"] += 1
                if review.get("status") == "approved":
                    reviewer_stats[reviewer]["approved"] += 1
                elif review.get("status") == "rejected":
                    reviewer_stats[reviewer]["rejected"] += 1

        # Find accountability gaps
        accountability_gaps = []
        for d in decisions:
            safety = d.get("safety_metadata", {})
            if safety.get("risk_level") in ["high", "critical"] and not d.get("safety_reviews"):
                accountability_gaps.append({
                    "id": d.get("id"),
                    "decision": d.get("decision"),
                    "risk_level": safety.get("risk_level"),
                    "timestamp": d.get("timestamp"),
                })

        # Decision chain analysis (decisions affecting same systems)
        chains = []
        systems_map = {}
        for d in decisions:
            safety = d.get("safety_metadata", {})
            for system in safety.get("affected_systems", []):
                if system not in systems_map:
                    systems_map[system] = []
                systems_map[system].append(d.get("id"))

        for system, ids in systems_map.items():
            if len(ids) > 1:
                chains.append({"system": system, "decision_count": len(ids), "decisions": ids[:5]})

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "total_reviewers": len(reviewer_stats),
                "accountability_gaps": len(accountability_gaps),
                "decision_chains": len(chains),
            },
            "reviewer_stats": reviewer_stats,
            "accountability_gaps": accountability_gaps[:10],
            "decision_chains": chains[:10],
        }
    except Exception as e:
        logger.error("accountability report failed: %s", e)
        raise HTTPException(500, f"Accountability report failed: {e}")


@app.get("/api/memory/{project}/robustness/test")
async def run_robustness_test(project: str):
    """Test decision robustness against edge cases and adversarial scenarios.
    
    Checks for:
    - Single points of failure (decisions with no alternatives)
    - Irreversibility risks (irreversible decisions without reviews)
    - Concentration risk (too many decisions affecting one system)
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        robustness_issues = []

        # Check for irreversible decisions without reviews
        for d in decisions:
            safety = d.get("safety_metadata", {})
            if not safety.get("reversibility", True) and not d.get("safety_reviews"):
                robustness_issues.append({
                    "type": "irreversible_no_review",
                    "severity": "high",
                    "decision_id": d.get("id"),
                    "decision": d.get("decision"),
                    "message": "Irreversible decision lacks review",
                })

        # Check concentration risk
        system_counts = {}
        for d in decisions:
            safety = d.get("safety_metadata", {})
            for system in safety.get("affected_systems", []):
                system_counts[system] = system_counts.get(system, 0) + 1

        for system, count in system_counts.items():
            if count > len(decisions) * 0.3 and len(decisions) > 5:
                robustness_issues.append({
                    "type": "concentration_risk",
                    "severity": "medium",
                    "system": system,
                    "decision_count": count,
                    "message": f"System '{system}' is affected by {count} decisions ({count/len(decisions)*100:.0f}%)",
                })

        # Check for decisions without context
        no_context = sum(1 for d in decisions if not d.get("context"))
        if no_context > len(decisions) * 0.2:
            robustness_issues.append({
                "type": "documentation_gap",
                "severity": "medium",
                "count": no_context,
                "message": f"{no_context} decisions lack context documentation",
            })

        # Calculate robustness score
        total_checks = 3
        passed_checks = total_checks - len(set(i["type"] for i in robustness_issues))
        robustness_score = passed_checks / total_checks

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "issues_found": len(robustness_issues),
                "robustness_score": round(robustness_score, 3),
            },
            "issues": robustness_issues,
            "system_concentration": system_counts,
        }
    except Exception as e:
        logger.error("robustness test failed: %s", e)
        raise HTTPException(500, f"Robustness test failed: {e}")


@app.get("/api/memory/{project}/transparency/report")
async def get_transparency_report(project: str):
    """Generate transparency report with human-readable explanations.
    
    Provides:
    - Summary of all decisions with rationale
    - Risk distribution overview
    - Review coverage statistics
    - Key decision factors
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Build decision summaries
        decision_summaries = []
        for d in decisions:
            safety = d.get("safety_metadata", {})
            summary = {
                "id": d.get("id"),
                "decision": d.get("decision"),
                "rationale": d.get("context", "No rationale provided"),
                "risk_level": safety.get("risk_level", "low"),
                "category": safety.get("safety_category", "general"),
                "affected_systems": safety.get("affected_systems", []),
                "reviewed": bool(d.get("safety_reviews")),
                "timestamp": d.get("timestamp"),
            }
            decision_summaries.append(summary)

        # Risk overview
        risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for d in decisions:
            risk = d.get("safety_metadata", {}).get("risk_level", "low")
            risk_counts[risk] = risk_counts.get(risk, 0) + 1

        # Review coverage
        reviewed = sum(1 for d in decisions if d.get("safety_reviews"))
        coverage = reviewed / len(decisions) if decisions else 1.0

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "review_coverage": round(coverage, 3),
                "risk_distribution": risk_counts,
            },
            "decisions": decision_summaries[:30],
            "key_insights": _generate_transparency_insights(decisions),
        }
    except Exception as e:
        logger.error("transparency report failed: %s", e)
        raise HTTPException(500, f"Transparency report failed: {e}")


def _generate_transparency_insights(decisions: list) -> list:
    """Generate key insights for transparency report."""
    insights = []
    if not decisions:
        return insights

    # High risk decisions
    high_risk = [d for d in decisions if d.get("safety_metadata", {}).get("risk_level") in ["high", "critical"]]
    if high_risk:
        insights.append(f"{len(high_risk)} high/critical risk decisions require attention")

    # Unreviewed high risk
    unreviewed = [d for d in high_risk if not d.get("safety_reviews")]
    if unreviewed:
        insights.append(f"{len(unreviewed)} high-risk decisions lack reviews")

    # Documentation gaps
    no_context = sum(1 for d in decisions if not d.get("context"))
    if no_context:
        insights.append(f"{no_context} decisions lack rationale documentation")

    return insights


# ============================
#  Alignment, Safety Envelope, Drift Detection Features
# ============================


@app.get("/api/memory/{project}/alignment/values")
async def check_value_alignment(project: str, values: str = Query("")):
    """Check decisions against organizational values.
    
    Provides a list of default values or accepts custom values via query param.
    Evaluates each decision's alignment with specified values.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Default values if none provided
        if values:
            value_list = [v.strip() for v in values.split(",")]
        else:
            value_list = ["safety", "transparency", "accountability", "fairness", "robustness"]

        # Evaluate alignment
        alignment_results = []
        for d in decisions:
            safety = d.get("safety_metadata", {})
            decision_text = d.get("decision", "").lower()
            context = d.get("context", "").lower()

            value_scores = {}
            for value in value_list:
                # Simple keyword-based alignment scoring
                score = _score_value_alignment(value, decision_text, context, safety)
                value_scores[value] = score

            avg_score = sum(value_scores.values()) / len(value_scores) if value_scores else 0

            alignment_results.append({
                "id": d.get("id"),
                "decision": d.get("decision"),
                "value_scores": value_scores,
                "overall_alignment": round(avg_score, 3),
            })

        # Summary statistics
        if alignment_results:
            avg_alignment = sum(r["overall_alignment"] for r in alignment_results) / len(alignment_results)
            low_alignment = [r for r in alignment_results if r["overall_alignment"] < 0.5]
        else:
            avg_alignment = 1.0
            low_alignment = []

        return {
            "project": project,
            "values_evaluated": value_list,
            "summary": {
                "total_decisions": len(decisions),
                "avg_alignment": round(avg_alignment, 3),
                "low_alignment_count": len(low_alignment),
            },
            "results": alignment_results[:20],
            "low_alignment_decisions": low_alignment[:10],
        }
    except Exception as e:
        logger.error("value alignment check failed: %s", e)
        raise HTTPException(500, f"Value alignment check failed: {e}")


def _score_value_alignment(value: str, decision: str, context: str, safety: dict) -> float:
    """Score alignment with a specific value."""
    value_lower = value.lower()

    # Safety-related values
    if value_lower in ["safety", "security"]:
        if safety.get("risk_level") in ["high", "critical"] and safety.get("requires_review"):
            return 0.9  # Good: high-risk decisions flagged for review
        if safety.get("risk_level") in ["high", "critical"] and not safety.get("requires_review"):
            return 0.3  # Bad: high-risk without review
        return 0.7

    # Transparency
    if value_lower == "transparency":
        if context and len(context) > 20:
            return 0.9  # Good: well-documented rationale
        if context:
            return 0.6  # Partial: some context
        return 0.3  # Bad: no context

    # Accountability
    if value_lower == "accountability":
        if d := safety.get("safety_reviews"):
            return 0.9  # Good: has reviews
        if safety.get("requires_review"):
            return 0.5  # Partial: needs review
        return 0.7  # Default

    # Fairness
    if value_lower == "fairness":
        if safety.get("affected_systems"):
            return 0.8  # Good: systems documented
        return 0.5

    # Robustness
    if value_lower == "robustness":
        if safety.get("reversibility", True):
            return 0.8  # Good: reversible
        return 0.4  # Concern: irreversible

    return 0.7  # Default moderate score


@app.get("/api/memory/{project}/safety-envelope")
async def get_safety_envelope(project: str):
    """Monitor safety envelope - track when decisions approach safety boundaries.
    
    Identifies:
    - Decisions near risk thresholds
    - Systems approaching capacity limits
    - Review backlog trends
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Risk threshold monitoring
        risk_weights = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        recent_decisions = decisions[-20:] if len(decisions) > 20 else decisions

        if recent_decisions:
            avg_risk = sum(risk_weights.get(d.get("safety_metadata", {}).get("risk_level", "low"), 0) for d in recent_decisions) / len(recent_decisions)
        else:
            avg_risk = 0

        # System capacity monitoring
        system_counts = {}
        for d in decisions:
            for system in d.get("safety_metadata", {}).get("affected_systems", []):
                system_counts[system] = system_counts.get(system, 0) + 1

        system_warnings = []
        for system, count in system_counts.items():
            if count > 10:
                system_warnings.append({
                    "system": system,
                    "decision_count": count,
                    "warning": f"System '{system}' has {count} associated decisions",
                })

        # Review backlog
        pending_reviews = sum(1 for d in decisions if d.get("safety_metadata", {}).get("requires_review"))
        reviewed = sum(1 for d in decisions if d.get("safety_reviews"))
        backlog_ratio = pending_reviews / len(decisions) if decisions else 0

        # Envelope status
        envelope_status = "healthy"
        if avg_risk > 1.5:
            envelope_status = "warning"
        if avg_risk > 2.0 or backlog_ratio > 0.3:
            envelope_status = "critical"

        return {
            "project": project,
            "envelope_status": envelope_status,
            "metrics": {
                "avg_recent_risk": round(avg_risk, 3),
                "pending_reviews": pending_reviews,
                "reviewed_decisions": reviewed,
                "backlog_ratio": round(backlog_ratio, 3),
                "systems_at_capacity": len(system_warnings),
            },
            "system_warnings": system_warnings,
            "recommendations": _generate_envelope_recommendations(envelope_status, avg_risk, backlog_ratio),
        }
    except Exception as e:
        logger.error("safety envelope failed: %s", e)
        raise HTTPException(500, f"Safety envelope check failed: {e}")


def _generate_envelope_recommendations(status: str, avg_risk: float, backlog: float) -> list:
    """Generate recommendations based on safety envelope status."""
    recommendations = []
    if status == "critical":
        recommendations.append("URGENT: Address high-risk decisions immediately")
    if avg_risk > 1.5:
        recommendations.append("Review recent high-risk decisions")
    if backlog > 0.2:
        recommendations.append(f"Clear review backlog ({backlog*100:.0f}% pending)")
    if not recommendations:
        recommendations.append("Safety envelope is healthy - continue monitoring")
    return recommendations


@app.get("/api/memory/{project}/alignment/drift")
async def get_alignment_drift(project: str, window: int = Query(10, ge=5, le=50)):
    """Detect alignment drift - changes in decision patterns over time.

    Compares recent decisions against historical patterns to detect drift.
    The comparison itself lives in core.goals.drift.score_trend_drift (a
    pure function, extracted so it can also be scoped to a single goal's
    linked decisions in GET /goals/{goal_id}/alignment) — this endpoint is
    now just the project-wide caller of it.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])
        return {"project": project, **score_trend_drift(decisions, window=window)}
    except Exception as e:
        logger.error("alignment drift detection failed: %s", e)
        raise HTTPException(500, f"Alignment drift detection failed: {e}")


@app.get("/api/memory/{project}/corrigibility")
async def get_corrigibility_tracker(project: str):
    """Track corrigibility - ability to correct or override decisions.
    
    Measures:
    - Reversibility rate
    - Review coverage
    - Override/reversal history
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        # Calculate corrigibility metrics
        reversible = sum(1 for d in decisions if d.get("safety_metadata", {}).get("reversibility", True))
        reviewed = sum(1 for d in decisions if d.get("safety_reviews"))
        has_rollback = sum(1 for d in decisions if d.get("version_history"))

        # Identify non-corrigible decisions
        non_corrigible = []
        for d in decisions:
            safety = d.get("safety_metadata", {})
            if not safety.get("reversibility", True) and not d.get("safety_reviews"):
                non_corrigible.append({
                    "id": d.get("id"),
                    "decision": d.get("decision"),
                    "risk_level": safety.get("risk_level", "low"),
                })

        # Corrigibility score
        total = len(decisions) if decisions else 1
        corrigibility_score = (reversible + reviewed) / (total * 2)

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "reversible_count": reversible,
                "reviewed_count": reviewed,
                "versioned_count": has_rollback,
                "non_corrigible_count": len(non_corrigible),
                "corrigibility_score": round(corrigibility_score, 3),
            },
            "non_corrigible_decisions": non_corrigible[:10],
        }
    except Exception as e:
        logger.error("corrigibility tracker failed: %s", e)
        raise HTTPException(500, f"Corrigibility tracking failed: {e}")


# ============================
#  Provenance, Integrity, Security Features
# ============================


from core.audit import append_audit_event as _append_audit_event
from core.audit import compute_hash as _compute_decision_hash
from core.audit import verify_audit_log_chain as _verify_audit_log_chain


@app.get("/api/memory/{project}/provenance/chain")
async def get_provenance_chain(project: str):
    """Get the provenance chain for decision-creation events.

    Reads memory["audit_log"] — an append-only store written to at the
    moment each event happens (see _append_audit_event), not recomputed
    from the current decisions list. Each entry's hash was computed once,
    at write time, chained from the previous *stored* entry's hash, so
    chain_valid here reflects a real comparison, not a hardcoded literal.

    Known limitation: audit_log only captures events from this point
    forward — decisions created before this endpoint was hardened have no
    corresponding audit_log entry and won't appear in the chain. That's
    surfaced honestly via chain_length rather than backfilled/faked.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        audit_log = memory.get("audit_log", [])
        decision_events = [e for e in audit_log if e.get("event_type") == "decision_created"]

        chain = []
        for i, e in enumerate(decision_events):
            stored_hash = e.get("hash")
            recomputed = _compute_decision_hash({k: v for k, v in e.items() if k != "hash"})
            chain.append({
                "index": i,
                "decision_id": e.get("decision_id"),
                "decision": e.get("decision"),
                "timestamp": e.get("timestamp"),
                "hash": stored_hash,
                "previous_hash": e.get("previous_hash"),
                "chain_valid": stored_hash == recomputed,
            })

        return {
            "project": project,
            "summary": {
                "chain_length": len(chain),
                "genesis_hash": chain[0]["hash"] if chain else None,
                "latest_hash": chain[-1]["hash"] if chain else None,
            },
            "chain": chain[-20:],  # Return last 20
        }
    except Exception as e:
        logger.error("provenance chain failed: %s", e)
        raise HTTPException(500, f"Provenance chain failed: {e}")


@app.get("/api/memory/{project}/integrity/verify")
async def verify_integrity(project: str):
    """Verify the integrity of the decision history.

    Checks:
    - Audit log hash-chain integrity (real comparison against audit_log,
      not a computed-but-unused hash like the old implementation had)
    - Decision structure validity
    - Timestamp ordering
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])
        audit_log = memory.get("audit_log", [])

        issues = _verify_audit_log_chain(audit_log)
        previous_timestamp = None

        for i, d in enumerate(decisions):
            # Verify structure
            if not d.get("decision"):
                issues.append({
                    "type": "missing_decision_text",
                    "index": i,
                    "severity": "high",
                })

            # Verify timestamp ordering
            current_ts = d.get("timestamp")
            if current_ts and previous_timestamp:
                if current_ts < previous_timestamp:
                    issues.append({
                        "type": "timestamp_order_violation",
                        "index": i,
                        "severity": "medium",
                        "message": f"Timestamp {current_ts} is before {previous_timestamp}",
                    })
            previous_timestamp = current_ts

        integrity_score = 1.0 - (len(issues) / max(len(decisions), 1))

        return {
            "project": project,
            "summary": {
                "total_decisions": len(decisions),
                "issues_found": len(issues),
                "integrity_score": round(max(0, integrity_score), 3),
            },
            "issues": issues[:20],
            "valid": len(issues) == 0,
        }
    except Exception as e:
        logger.error("integrity verification failed: %s", e)
        raise HTTPException(500, f"Integrity verification failed: {e}")


@app.get("/api/memory/{project}/tamper-detection")
async def detect_tampering(project: str):
    """Detect potential tampering with decision history.
    
    Checks for:
    - Missing decisions (gaps in sequence)
    - Modified decisions (hash mismatches)
    - Anomalous patterns
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        decisions = memory.get("decisions", [])

        tamper_flags = []

        # Check for ID continuity — duplicate IDs can only happen via direct
        # file manipulation; the API always generates unique ones.
        ids = [d.get("id") for d in decisions if d.get("id")]
        if len(ids) != len(set(ids)):
            tamper_flags.append({
                "type": "duplicate_ids",
                "severity": "high",
                "message": "Duplicate decision IDs found — the API never generates these, so this points to direct file edits rather than normal use.",
            })

        # Check for malformed ID format — the API always generates 12-char
        # lowercase hex IDs (uuid4().hex[:12]); anything else means the
        # record wasn't created through the normal decision-capture path.
        _ID_RE = re.compile(r"^[0-9a-f]{12}$")
        malformed = [d.get("id") for d in decisions if d.get("id") and not _ID_RE.match(d.get("id"))]
        if malformed:
            tamper_flags.append({
                "type": "malformed_ids",
                "severity": "high",
                "count": len(malformed),
                "message": f"{len(malformed)} decision ID(s) don't match the format the API generates — likely written outside the normal decision-capture path.",
            })

        # Check for empty decisions — the API requires non-empty decision
        # text, so an empty one means the record was edited directly.
        empty_count = sum(1 for d in decisions if not d.get("decision"))
        if empty_count > 0:
            tamper_flags.append({
                "type": "empty_decisions",
                "severity": "high",
                "count": empty_count,
                "message": f"{empty_count} decision(s) have empty decision text, which the API's validation would normally reject.",
            })

        # Check for timestamp anomalies — lower confidence than the checks
        # above: this can happen from clock skew, backdated test data, or
        # concurrent writes, not just tampering, so it's flagged as an
        # ordering irregularity worth a look rather than asserted as proof
        # of anything.
        timestamps = [d.get("timestamp") for d in decisions if d.get("timestamp")]
        for i in range(1, len(timestamps)):
            if timestamps[i] < timestamps[i-1]:
                tamper_flags.append({
                    "type": "timestamp_anomaly",
                    "severity": "low",
                    "index": i,
                    "message": f"Decision at index {i} has an earlier timestamp than the one before it — could be reordering, backdated data, clock skew, or (less likely) tampering. Not conclusive on its own.",
                })

        # Status reflects the most severe flag type present, not just how
        # many flags there are — a pile of low-confidence timestamp
        # irregularities shouldn't read the same as one duplicate-ID hit.
        # "compromised" is reserved for flags the API's own validation
        # would never allow (duplicate/malformed IDs, empty text) — genuine
        # structural evidence, not just statistical noise.
        severities_present = {f["severity"] for f in tamper_flags}
        if not tamper_flags:
            status = "clean"
        elif "high" in severities_present:
            status = "compromised"
        else:
            status = "alert"
        tamper_risk = len(tamper_flags) / max(len(decisions), 1)

        return {
            "project": project,
            "status": status,
            "summary": {
                "total_decisions": len(decisions),
                "tamper_flags": len(tamper_flags),
                "tamper_risk": round(tamper_risk, 3),
            },
            "flags": tamper_flags,
        }
    except Exception as e:
        logger.error("tamper detection failed: %s", e)
        raise HTTPException(500, f"Tamper detection failed: {e}")


@app.get("/api/memory/{project}/security/audit-log")
async def get_security_audit_log(project: str, limit: int = Query(50, ge=1, le=200)):
    """Get the security audit log.

    Reads memory["audit_log"] directly — the append-only store written to
    at the moment each security-relevant event happens (see
    _append_audit_event), rather than reconstructing events after the fact
    from the current decisions list. That distinction matters: the old
    reconstruction only ever saw whatever safety_reviews/version_history
    currently exist on a decision, so editing or deleting one of those
    entries directly in the memory JSON silently removed it from the
    "immutable" log on the very next call. This version doesn't share that
    entries with those records — it's a separate, independently-written
    trail.

    Known limitation: only events written after this endpoint was hardened
    appear here — no backfill for history that predates it.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        audit_log = memory.get("audit_log", [])

        audit_events = sorted(audit_log, key=lambda x: x.get("timestamp", ""), reverse=True)

        return {
            "project": project,
            "summary": {
                "total_events": len(audit_events),
                "decision_events": sum(1 for e in audit_events if e["event_type"] == "decision_created"),
                "review_events": sum(1 for e in audit_events if e["event_type"] == "review_submitted"),
                "version_events": sum(1 for e in audit_events if e["event_type"] == "version_created"),
            },
            "events": audit_events[:limit],
        }
    except Exception as e:
        logger.error("security audit log failed: %s", e)
        raise HTTPException(500, f"Security audit log failed: {e}")


# ============================
#  Synthetic Data Policy
# ============================


class SyntheticDataPolicy(BaseModel):
    """Synthetic Data Policy - A Living Record following EU AI Act Articles 10 & 50, NIST guidance."""
    
    # Identification & Provenance
    dataset_name: str = Field(..., max_length=200, description="Standard unique identifier with domain/use case")
    version: str = Field("1.0", max_length=50, description="Dataset and schema versioning")
    generated_by: str = Field(..., max_length=200, description="Entity and specific software tool (e.g., Tonic Fabricate, MOSTLY AI, Gretel)")
    authorized_by: str = Field("", max_length=200, description="Approver and role (must include DPO for regulated sectors)")
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_seed_data: str = Field(..., max_length=500, description="Origin and Lawful Basis (e.g., GDPR Art. 6)")
    synthetic_real_ratio: str = Field(..., max_length=100, description="Proportion (e.g., 10 real:1000 synthetic)")
    
    # Architecture Details
    models_used: str = Field(..., max_length=300, description="Architecture and parameters (e.g., CTGAN, Diffusion)")
    architecture_type: str = Field("unknown", pattern=r"^(gan|vae|diffusion|llm|other|unknown)$")
    
    # Modality & Schema
    data_types: list[str] = Field(default_factory=list, description="Tabular, Relational, Time-Series, Unstructured, Multi-camera Video")
    referential_integrity: str = Field("", max_length=500, description="How PK/FK constraints were preserved")
    
    # Intended Use & Risk
    eu_ai_act_tier: str = Field("minimal", pattern=r"^(high|minimal|limited|unacceptable)$")
    purpose: str = Field(..., max_length=500, description="Plain language description of intended use")
    operational_constraints: str = Field("", max_length=500, description="What this data should never be used for")
    legal_traceability: str = Field("", max_length=500, description="Suitability for legal provenance use cases")
    
    # Quality Matrix
    fidelity_score: str = Field("", max_length=200, description="Statistical similarity (KS, Wasserstein, cardinality)")
    utility_validation: str = Field("", max_length=500, description="TSTR protocol results")
    
    # Privacy
    privacy_parameters: str = Field("", max_length=300, description="DP parameters (ε, δ) or SBPM scores (IMS, DCR, NNDR)")
    dp_epsilon: float = Field(0.0, ge=0.0, description="Differential Privacy epsilon value")
    dp_delta: float = Field(0.0, ge=0.0, description="Differential Privacy delta value")
    
    # Risk Assessment
    bias_audit_results: str = Field("", max_length=500, description="Demographic parity or disparate impact audit results")
    adversarial_testing: str = Field("", max_length=500, description="MIA, AIA, Reconstruction attack results")
    outlier_vulnerability: str = Field("", max_length=500, description="Assessment of rare record reproduction risk")
    
    # Environment Assumptions
    environment_assumptions: str = Field("", max_length=500, description="What the simulation silently assumes")
    adversary_knowledge: str = Field("", max_length=300, description="Assumed background knowledge (quasi-identifiers)")
    
    # Lifecycle
    model_collapse_prevention: str = Field("", max_length=500, description="Provenance to prevent recursive training")
    retention_deletion: str = Field("", max_length=300, description="When the dataset expires (GDPR Art. 17)")
    
    # Transparency
    distinguishability_marking: str = Field("", max_length=300, description="Watermarking method (EU AI Act Art. 50(2))")
    rationale: str = Field(..., max_length=500, description="Motivation for synthetic use")
    
    # Verification
    attested_by: str = Field("", max_length=200, description="Independent verifier identity")
    human_oversight: str = Field("", max_length=300, description="Oversight mechanism for AI system use")
    review_date: str = Field("", max_length=50, description="Next review date")
    superseded_version: str = Field("", max_length=100, description="Ancestral real data or previous synthetic versions")
    appeal_path: str = Field("", max_length=300, description="Where data subjects can contest inferences")


class SyntheticDataPolicyResponse(BaseModel):
    """Response model for synthetic data policy."""
    id: str
    policy: SyntheticDataPolicy
    compliance_status: str
    blocking_gates: dict
    created_at: str
    updated_at: str


@app.post("/api/memory/{project}/synthetic-data-policies")
async def create_synthetic_data_policy(project: str, policy: SyntheticDataPolicy):
    """Create a new Synthetic Data Policy record.
    
    This is a mandatory "nutritional label" for synthetic datasets following
    EU AI Act Articles 10 & 50, NIST synthetic content guidance, and
    Datasheets for Datasets best practices.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        
        # Initialize policies list if not present
        if "synthetic_data_policies" not in memory:
            memory["synthetic_data_policies"] = []
        
        # Generate ID
        import uuid as _uuid
        policy_id = _uuid.uuid4().hex[:12]
        
        # Run compliance validation
        compliance_result = _validate_synthetic_data_compliance(policy)
        
        # Create policy entry
        policy_entry = {
            "id": policy_id,
            "policy": policy.model_dump(),
            "compliance_status": compliance_result["status"],
            "blocking_gates": compliance_result["blocking_gates"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        memory["synthetic_data_policies"].append(policy_entry)
        memory["last_updated"] = datetime.now(timezone.utc).isoformat()
        mm.save_project_memory(project, memory)
        
        return {
            "success": True,
            "policy_id": policy_id,
            "compliance_status": compliance_result["status"],
            "blocking_gates": compliance_result["blocking_gates"],
            "warnings": compliance_result.get("warnings", []),
        }
    except Exception as e:
        logger.error("create synthetic data policy failed: %s", e)
        raise HTTPException(500, f"Failed to create policy: {e}")


@app.get("/api/memory/{project}/synthetic-data-policies")
async def list_synthetic_data_policies(project: str):
    """List all Synthetic Data Policies for a project."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        
        policies = memory.get("synthetic_data_policies", [])
        
        return {
            "project": project,
            "total_policies": len(policies),
            "policies": policies,
        }
    except Exception as e:
        logger.error("list synthetic data policies failed: %s", e)
        raise HTTPException(500, f"Failed to list policies: {e}")


@app.get("/api/memory/{project}/synthetic-data-policies/{policy_id}")
async def get_synthetic_data_policy(project: str, policy_id: str):
    """Get a specific Synthetic Data Policy with full details."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        
        policies = memory.get("synthetic_data_policies", [])
        
        for p in policies:
            if p.get("id") == policy_id:
                return p
        
        raise HTTPException(status_code=404, detail="Policy not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get synthetic data policy failed: %s", e)
        raise HTTPException(500, f"Failed to get policy: {e}")


@app.put("/api/memory/{project}/synthetic-data-policies/{policy_id}")
async def update_synthetic_data_policy(project: str, policy_id: str, policy: SyntheticDataPolicy):
    """Update an existing Synthetic Data Policy."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        
        policies = memory.get("synthetic_data_policies", [])
        
        for i, p in enumerate(policies):
            if p.get("id") == policy_id:
                # Run compliance validation
                compliance_result = _validate_synthetic_data_compliance(policy)
                
                # Update policy
                policies[i] = {
                    "id": policy_id,
                    "policy": policy.model_dump(),
                    "compliance_status": compliance_result["status"],
                    "blocking_gates": compliance_result["blocking_gates"],
                    "created_at": p.get("created_at"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                
                memory["last_updated"] = datetime.now(timezone.utc).isoformat()
                mm.save_project_memory(project, memory)
                
                return {
                    "success": True,
                    "policy_id": policy_id,
                    "compliance_status": compliance_result["status"],
                    "blocking_gates": compliance_result["blocking_gates"],
                    "warnings": compliance_result.get("warnings", []),
                }
        
        raise HTTPException(status_code=404, detail="Policy not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update synthetic data policy failed: %s", e)
        raise HTTPException(500, f"Failed to update policy: {e}")


@app.delete("/api/memory/{project}/synthetic-data-policies/{policy_id}")
async def delete_synthetic_data_policy(project: str, policy_id: str):
    """Delete a Synthetic Data Policy."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        
        policies = memory.get("synthetic_data_policies", [])
        original_length = len(policies)
        
        memory["synthetic_data_policies"] = [p for p in policies if p.get("id") != policy_id]
        
        if len(memory["synthetic_data_policies"]) == original_length:
            raise HTTPException(status_code=404, detail="Policy not found")
        
        memory["last_updated"] = datetime.now(timezone.utc).isoformat()
        mm.save_project_memory(project, memory)
        
        return {"success": True, "deleted": policy_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete synthetic data policy failed: %s", e)
        raise HTTPException(500, f"Failed to delete policy: {e}")


@app.get("/api/memory/{project}/synthetic-data-policies/{policy_id}/compliance")
async def check_synthetic_data_compliance(project: str, policy_id: str):
    """Run compliance check on a Synthetic Data Policy.
    
    Validates against blocking gates:
    - Fidelity threshold
    - Privacy parameters (ε/δ)
    - Bias audit requirements
    - Adversarial testing requirements
    - EU AI Act tier requirements
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        
        policies = memory.get("synthetic_data_policies", [])
        
        for p in policies:
            if p.get("id") == policy_id:
                policy_data = p.get("policy", {})
                # Reconstruct policy object for validation
                policy = SyntheticDataPolicy(**policy_data)
                compliance_result = _validate_synthetic_data_compliance(policy)
                
                return {
                    "policy_id": policy_id,
                    "compliance_status": compliance_result["status"],
                    "blocking_gates": compliance_result["blocking_gates"],
                    "warnings": compliance_result.get("warnings", []),
                    "recommendations": compliance_result.get("recommendations", []),
                }
        
        raise HTTPException(status_code=404, detail="Policy not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("compliance check failed: %s", e)
        raise HTTPException(500, f"Compliance check failed: {e}")


@app.get("/api/memory/{project}/synthetic-data/summary")
async def get_synthetic_data_summary(project: str):
    """Get summary of all Synthetic Data Policies for a project."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        
        policies = memory.get("synthetic_data_policies", [])
        
        # Aggregate statistics
        total = len(policies)
        compliant = sum(1 for p in policies if p.get("compliance_status") == "compliant")
        non_compliant = sum(1 for p in policies if p.get("compliance_status") == "non_compliant")
        partial = sum(1 for p in policies if p.get("compliance_status") == "partial")
        
        # Risk tier distribution
        tier_distribution = {}
        for p in policies:
            tier = p.get("policy", {}).get("eu_ai_act_tier", "minimal")
            tier_distribution[tier] = tier_distribution.get(tier, 0) + 1
        
        # Architecture distribution
        architecture_distribution = {}
        for p in policies:
            arch = p.get("policy", {}).get("architecture_type", "unknown")
            architecture_distribution[arch] = architecture_distribution.get(arch, 0) + 1
        
        # Privacy parameter summary
        dp_enabled = sum(1 for p in policies if p.get("policy", {}).get("dp_epsilon", 0) > 0)
        
        return {
            "project": project,
            "summary": {
                "total_policies": total,
                "compliant": compliant,
                "non_compliant": non_compliant,
                "partial": partial,
                "compliance_rate": round(compliant / total, 3) if total > 0 else 1.0,
            },
            "tier_distribution": tier_distribution,
            "architecture_distribution": architecture_distribution,
            "privacy_summary": {
                "dp_enabled_count": dp_enabled,
                "total_policies": total,
            },
        }
    except Exception as e:
        logger.error("synthetic data summary failed: %s", e)
        raise HTTPException(500, f"Summary failed: {e}")


def _validate_synthetic_data_compliance(policy: SyntheticDataPolicy) -> dict:
    """Validate a Synthetic Data Policy against compliance requirements.
    
    Implements blocking gates as specified in the framework:
    - Fidelity threshold
    - Privacy parameters
    - Bias audit requirements
    - Adversarial testing
    - EU AI Act tier requirements
    """
    blocking_gates = {}
    warnings = []
    recommendations = []
    
    # Gate 1: Fidelity Score (blocking gate)
    has_fidelity = bool(policy.fidelity_score and len(policy.fidelity_score) > 0)
    blocking_gates["fidelity"] = {
        "passed": has_fidelity,
        "required": True,
        "message": "Fidelity score documented" if has_fidelity else "MISSING: Fidelity score required",
    }
    if not has_fidelity:
        recommendations.append("Run Kolmogorov-Smirnov or Wasserstein distance tests")
    
    # Gate 2: Privacy Parameters (blocking gate for high-risk)
    has_privacy = bool(policy.privacy_parameters and len(policy.privacy_parameters) > 0)
    has_dp = policy.dp_epsilon > 0
    blocking_gates["privacy"] = {
        "passed": has_privacy or has_dp,
        "required": policy.eu_ai_act_tier == "high",
        "message": "Privacy parameters documented" if (has_privacy or has_dp) else "Privacy parameters not documented",
    }
    if policy.eu_ai_act_tier == "high" and not (has_privacy or has_dp):
        warnings.append("HIGH-RISK: Privacy parameters (ε/δ) required for high-risk tier")
        recommendations.append("Implement Differential Privacy with explicit ε/δ values")
    
    # Gate 3: Bias Audit (blocking gate)
    has_bias_audit = bool(policy.bias_audit_results and len(policy.bias_audit_results) > 0)
    blocking_gates["bias_audit"] = {
        "passed": has_bias_audit,
        "required": True,
        "message": "Bias audit documented" if has_bias_audit else "MISSING: Bias audit results required",
    }
    if not has_bias_audit:
        recommendations.append("Run demographic parity or disparate impact audits")
    
    # Gate 4: Adversarial Testing (blocking gate for high-risk)
    has_adversarial = bool(policy.adversarial_testing and len(policy.adversarial_testing) > 0)
    blocking_gates["adversarial_testing"] = {
        "passed": has_adversarial,
        "required": policy.eu_ai_act_tier == "high",
        "message": "Adversarial testing documented" if has_adversarial else "Adversarial testing not documented",
    }
    if policy.eu_ai_act_tier == "high" and not has_adversarial:
        warnings.append("HIGH-RISK: MIA/AIA/Reconstruction attack results required")
        recommendations.append("Run Membership Inference, Attribute Inference, and Reconstruction attacks")
    
    # Gate 5: Source Seed Data (always required)
    has_source = bool(policy.source_seed_data and len(policy.source_seed_data) > 10)
    blocking_gates["source_data"] = {
        "passed": has_source,
        "required": True,
        "message": "Source seed data documented" if has_source else "MISSING: Source seed data origin required",
    }
    
    # Gate 6: Rationale (always required)
    has_rationale = bool(policy.rationale and len(policy.rationale) > 10)
    blocking_gates["rationale"] = {
        "passed": has_rationale,
        "required": True,
        "message": "Rationale documented" if has_rationale else "MISSING: Rationale for synthetic use required",
    }
    
    # Gate 7: Distinguishability Marking (EU AI Act Art. 50(2))
    has_marking = bool(policy.distinguishability_marking and len(policy.distinguishability_marking) > 0)
    blocking_gates["distinguishability"] = {
        "passed": has_marking,
        "required": policy.eu_ai_act_tier == "high",
        "message": "Distinguishability marking documented" if has_marking else "Distinguishability marking not documented",
    }
    if policy.eu_ai_act_tier == "high" and not has_marking:
        warnings.append("HIGH-RISK: EU AI Act Art. 50(2) requires labeling of AI-generated content")
    
    # Gate 8: Model Collapse Prevention
    has_collapse = bool(policy.model_collapse_prevention and len(policy.model_collapse_prevention) > 0)
    blocking_gates["model_collapse"] = {
        "passed": has_collapse,
        "required": False,
        "message": "Model collapse prevention documented" if has_collapse else "Model collapse prevention not documented",
    }
    if not has_collapse:
        recommendations.append("Document training ratios to prevent recursive degradation")
    
    # Gate 9: Retention/Deletion
    has_retention = bool(policy.retention_deletion and len(policy.retention_deletion) > 0)
    blocking_gates["retention"] = {
        "passed": has_retention,
        "required": True,
        "message": "Retention/deletion policy documented" if has_retention else "MISSING: Retention/deletion policy required (GDPR Art. 17)",
    }
    
    # Gate 10: Attestation
    has_attestation = bool(policy.attested_by and len(policy.attested_by) > 0)
    blocking_gates["attestation"] = {
        "passed": has_attestation,
        "required": policy.eu_ai_act_tier == "high",
        "message": "Independent attestation documented" if has_attestation else "Attestation not documented",
    }
    
    # Calculate overall status
    required_gates = [g for g in blocking_gates.values() if g["required"]]
    passed_required = sum(1 for g in required_gates if g["passed"])
    
    if len(required_gates) == 0:
        status = "compliant"
    elif passed_required == len(required_gates):
        status = "compliant"
    elif passed_required >= len(required_gates) * 0.7:
        status = "partial"
    else:
        status = "non_compliant"
    
    return {
        "status": status,
        "blocking_gates": blocking_gates,
        "warnings": warnings,
        "recommendations": recommendations,
        "gates_passed": sum(1 for g in blocking_gates.values() if g["passed"]),
        "gates_total": len(blocking_gates),
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


@app.get("/api/memory/{project}/sessions/weekly-summary")
async def get_weekly_summary(project: str):
    """Get a summary of what changed this week."""
    project = _sanitise_project(project)
    from core.session_replay import SessionReplay

    replay = SessionReplay(str(BASE_DIR))
    return replay.get_weekly_summary(project)


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


class SessionShapeInput(BaseModel):
    """Behavioral telemetry captured by mcp_server/server.py's _request()
    wrapper across one MCP session — see wishlist.md #45. Fully optional on
    SessionRecordRequest: only MCP-routed sessions can populate this (the
    dashboard's manual "End Session" button, VSCode/Emacs/OpenCode clients
    don't route through that chokepoint), which is an honest scope limit,
    not a bug.
    """

    tool_call_count: int = Field(..., ge=0)
    unique_tools_used: int = Field(..., ge=0)
    avg_call_duration_ms: float = Field(..., ge=0)
    max_call_duration_ms: float = Field(..., ge=0)
    error_count: int = Field(..., ge=0)
    avg_output_bytes: float = Field(..., ge=0)
    total_duration_s: float = Field(..., ge=0)


class SessionRecordRequest(BaseModel):
    summary: str = Field("", max_length=2000)
    session_type: str = Field("manual", max_length=50)
    agent_name: str = Field("unspecified", max_length=100)
    session_shape: SessionShapeInput | None = None


@app.post("/api/memory/{project}/sessions/record")
async def record_session(project: str, req: SessionRecordRequest):
    """Record a session: a Time Travel snapshot (before/after diff),
    pattern learning (category/day patterns, session_history with the raw
    summary), and — when the caller supplies it — session-shape baselining
    (#45). The single way to end a session, agent or dashboard alike --
    this used to be two disconnected endpoints (this one, snapshot-only,
    and the now-removed POST /sessions, pattern-learning-only), so ending a
    session through one path silently skipped what the other did.
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    from core.agent_identity import normalize_agent_name
    from core.learner.learner import PatternLearner
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
        agent=normalize_agent_name(req.agent_name),
    )

    learner = PatternLearner(mm)
    analysis = learner.analyze_session(project, req.summary)
    learner.update_project_from_session(project, analysis)

    # session_shape is written last and against a FRESH read, not the
    # `current` captured at the top of this handler: learner.
    # update_project_from_session() just did its own independent
    # get_project_memory -> mutate -> save_project_memory cycle
    # (MemoryManager.get_project_memory re-reads from disk every call, no
    # shared-object caching -- confirmed against core/memory/manager.py).
    # Reusing the stale `current` here would silently clobber whatever the
    # learner just wrote. This is an ordering fix, not a new locking
    # mechanism -- the same accepted per-router read/mutate/save risk
    # profile every other router in this codebase already lives with.
    shape_result = None
    if req.session_shape is not None:
        try:
            from core.session_shape.baseline import record_session_shape

            fresh_memory = mm.get_project_memory(project)
            fresh_memory, shape_result = record_session_shape(
                fresh_memory, req.agent_name, req.session_shape.model_dump()
            )
            mm.save_project_memory(project, fresh_memory)
        except Exception as exc:
            # Session-shape is additive telemetry, not the point of this
            # endpoint -- a bug here must never fail the actual session
            # recording (snapshot + pattern learning) that already
            # succeeded above.
            logger.error("session-shape recording failed for %s: %s", project, exc)
            shape_result = None

    _emit_telemetry("OK", f"Session recorded for {project}")
    return {
        **result,
        "detected_categories": analysis["detected_categories"],
        "key_insights": analysis["key_insights"],
        **({"session_shape": shape_result} if shape_result else {}),
    }


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
    """Get all decisions with confidence scores.

    Uses score_decisions_with_inheritance (#58) rather than score_decisions
    directly: each result carries the existing `score` (own decay only,
    unchanged meaning) plus `inherited_discount`/`effective_score` --
    additive fields, so this stays backward compatible with the existing
    dashboard consumer.
    """
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    from core.knowledge_decay import score_decisions_with_inheritance

    scored = score_decisions_with_inheritance(memory.get("decisions", []))
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
    _emit_telemetry("DECAY", f"Confidence scores re-evaluated for {project}")

    return {"applied": True, "summary": memory.get("confidence_summary", {})}


class DecayAgentActionRequest(BaseModel):
    """Body for pin/attest/unpin -- low-ceremony on purpose, matching the
    friction-dismiss pattern (core/friction/router.py) for non-blocking
    metadata changes: agent_name is attributable but optional."""
    agent_name: str = Field("", max_length=100)


def _find_decision(memory: dict[str, Any], decision_id: str) -> dict[str, Any] | None:
    """Look up one decision by id, same linear-scan pattern already used
    throughout this file (e.g. submit_safety_review)."""
    for d in memory.get("decisions", []):
        if isinstance(d, dict) and d.get("id") == decision_id:
            return d
    return None


@app.post("/api/memory/{project}/decisions/{decision_id}/pin")
async def pin_decision(project: str, decision_id: str, body: DecayAgentActionRequest = DecayAgentActionRequest()):
    """Mark a decision "constitutional" (#58): exempt from decay while
    re-attested within REATTESTATION_PERIOD_DAYS. Not a permanent
    exemption -- see core/knowledge_decay.py's decay_score docstring.
    """
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)

        decision = _find_decision(memory, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found in project '{project}'")

        now = datetime.now(timezone.utc).isoformat()
        decision["pinned"] = True
        decision["last_attested"] = now
        _append_audit_event(
            memory, "decision_pinned",
            decision_id=decision_id, agent_name=body.agent_name,
        )
        mm.save_project_memory(project, memory)

        from core.knowledge_decay import score_decision
        return {"decision_id": decision_id, "pinned": True, "confidence": score_decision(decision)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("pin_decision failed: %s", exc)
        raise HTTPException(500, f"Failed to pin decision: {exc}")


@app.post("/api/memory/{project}/decisions/{decision_id}/attest")
async def attest_decision(project: str, decision_id: str, body: DecayAgentActionRequest = DecayAgentActionRequest()):
    """Refresh a pinned decision's re-attestation clock. 409s if the
    decision isn't currently pinned -- attesting something unpinned has
    no meaning."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)

        decision = _find_decision(memory, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found in project '{project}'")
        if not decision.get("pinned"):
            raise HTTPException(status_code=409, detail="Decision is not pinned -- pin it first")

        now = datetime.now(timezone.utc).isoformat()
        decision["last_attested"] = now
        _append_audit_event(
            memory, "decision_attested",
            decision_id=decision_id, agent_name=body.agent_name,
        )
        mm.save_project_memory(project, memory)

        from core.knowledge_decay import score_decision
        return {"decision_id": decision_id, "last_attested": now, "confidence": score_decision(decision)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("attest_decision failed: %s", exc)
        raise HTTPException(500, f"Failed to attest decision: {exc}")


@app.post("/api/memory/{project}/decisions/{decision_id}/unpin")
async def unpin_decision(project: str, decision_id: str, body: DecayAgentActionRequest = DecayAgentActionRequest()):
    """Remove a decision's pinned/constitutional status. `last_attested`
    is left as history rather than cleared -- harmless once `pinned` is
    False, and preserves when it was last affirmed if re-pinned later."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)

        decision = _find_decision(memory, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found in project '{project}'")

        decision["pinned"] = False
        _append_audit_event(
            memory, "decision_unpinned",
            decision_id=decision_id, agent_name=body.agent_name,
        )
        mm.save_project_memory(project, memory)

        from core.knowledge_decay import score_decision
        return {"decision_id": decision_id, "pinned": False, "confidence": score_decision(decision)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("unpin_decision failed: %s", exc)
        raise HTTPException(500, f"Failed to unpin decision: {exc}")


class DecayReviewDismissRequest(BaseModel):
    """Body for dismissing a decay review (#58). Observational, not
    high-severity gated like #62's friction dismissal -- both fields stay
    optional."""
    agent_name: str = Field("", max_length=100)
    reason: str = Field("", max_length=500)


@app.get("/api/memory/{project}/decay-reviews")
async def list_decay_reviews(project: str, status: str | None = Query(None, pattern="^(pending|dismissed)$")):
    """List decisions flagged by the background scheduler as stale-but-
    still-referenced (#58). Mirrors #62's review_status pending/dismissed
    query-param filter shape."""
    project = _sanitise_project(project)
    mm = get_memory_manager()
    memory = mm.get_project_memory(project)

    reviews = memory.get("decay_reviews", [])
    if not isinstance(reviews, list):
        reviews = []
    if status is not None:
        reviews = [r for r in reviews if isinstance(r, dict) and r.get("review_status") == status]
    return {"decay_reviews": reviews, "count": len(reviews)}


@app.post("/api/memory/{project}/decay-reviews/{review_id}/dismiss")
async def dismiss_decay_review(project: str, review_id: str, body: DecayReviewDismissRequest = DecayReviewDismissRequest()):
    """Dismiss a pending decay review -- removes it from Needs Attention
    without touching the underlying decision."""
    try:
        project = _sanitise_project(project)
        mm = get_memory_manager()
        memory = mm.get_project_memory(project)

        reviews = memory.get("decay_reviews", [])
        if not isinstance(reviews, list):
            reviews = []
        review = next((r for r in reviews if isinstance(r, dict) and r.get("id") == review_id), None)
        if review is None:
            raise HTTPException(status_code=404, detail=f"Decay review '{review_id}' not found in project '{project}'")

        review["review_status"] = "dismissed"
        review["dismissed_by"] = body.agent_name
        review["dismissed_reason"] = body.reason
        memory["decay_reviews"] = reviews
        _append_audit_event(
            memory, "decay_review_dismissed",
            review_id=review_id, decision_id=review.get("decision_id"), agent_name=body.agent_name,
        )
        mm.save_project_memory(project, memory)

        return {"review_id": review_id, "review_status": "dismissed"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("dismiss_decay_review failed: %s", exc)
        raise HTTPException(500, f"Failed to dismiss decay review: {exc}")


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
    agent_name: str = Field("unspecified", max_length=100)


@app.get("/api/memory/{project}/agent-skills")
async def get_agent_skills(project: str):
    """Get agent skill scores for a project (aggregate across all agents)."""
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
        project, req.session_type, req.categories, req.outcome, req.details, req.agent_name
    )
    return {"recorded": True, "categories": req.categories, "agent_name": req.agent_name}


@app.get("/api/memory/{project}/agent-skills/briefing")
async def get_agent_briefing(project: str):
    """Get agent proficiency briefing for context injection."""
    project = _sanitise_project(project)
    from core.agent_skills import AgentSkillGraph

    graph = AgentSkillGraph(str(BASE_DIR))
    briefing = graph.get_briefing(project)
    return {"briefing": briefing, "project": project}


@app.get("/api/memory/{project}/agents")
async def list_project_agents(project: str):
    """Distinct agent names ever recorded for this project, across skills,
    sessions, and friction scans. Feeds the UI's agent-name autocomplete."""
    project = _sanitise_project(project)
    from core.agent_skills import AgentSkillGraph
    from core.session_replay import SessionReplay

    graph = AgentSkillGraph(str(BASE_DIR))
    replay = SessionReplay(str(BASE_DIR))
    memory = get_memory_manager().get_project_memory(project)
    friction_agents = {
        h.get("agent_name") for h in memory.get("friction_history", [])
        if h.get("agent_name") and h.get("agent_name") != "unspecified"
    }
    names = sorted(set(graph.list_agents(project)) | set(replay.list_agents(project)) | friction_agents)
    return {"agents": names, "count": len(names)}


@app.get("/api/memory/{project}/agents/{agent}/summary")
async def get_agent_summary(project: str, agent: str):
    """Aggregate skill, friction, and session stats for one agent within a project."""
    project = _sanitise_project(project)
    from core.agent_identity import normalize_agent_name
    from core.agent_skills import AgentSkillGraph
    from core.friction.miner import compute_friction_by_agent
    from core.session_replay import SessionReplay

    agent = normalize_agent_name(agent)
    graph = AgentSkillGraph(str(BASE_DIR))
    replay = SessionReplay(str(BASE_DIR))
    memory = get_memory_manager().get_project_memory(project)

    skills = graph.get_skills(project, agent_name=agent)
    sessions = [s for s in replay.get_sessions(project, limit=1000) if s.get("agent", "unspecified") == agent]
    friction = compute_friction_by_agent(memory.get("friction_history", []), agent)
    session_types = {s.get("session_type") for s in sessions}

    return {
        "agent_name": agent,
        "skills": skills,
        "strengths": graph.get_strengths(project, agent_name=agent),
        "weaknesses": graph.get_weaknesses(project, agent_name=agent),
        "friction": friction,
        "sessions": {
            "total": len(sessions),
            "by_type": {t: sum(1 for s in sessions if s.get("session_type") == t) for t in session_types},
        },
    }


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

        # A dedicated subdirectory, not "memory/" directly — list_projects()
        # globs memory/*.json for project names, and research_feeds.json /
        # research_feeds_runs.json living there get misidentified as projects.
        _feed_manager = ResearchFeedManager(storage_path=str(BASE_DIR / "memory" / "feeds"))
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


def _save_deep_research_run(
    query: str, html: str, citations: list[dict], engine: str = "last30days"
) -> dict:
    """Persist a deep research run. Returns the run metadata.

    `engine` distinguishes which research mode produced the run
    (last30days, citation-grade, or hybrid) so the shared history list
    can show all three instead of only last30days runs.
    """
    import uuid
    run_id = uuid.uuid4().hex[:12]
    timestamp = datetime.now(timezone.utc).isoformat()

    # Save HTML output (also used for markdown-producing engines — the
    # field name predates citation-grade/hybrid support, but it's just a
    # text blob written back out verbatim by GET /last30days/runs/{id}).
    html_file = _DEEP_RESEARCH_DIR / f"{run_id}.html"
    html_file.write_text(html, encoding="utf-8")

    run = {
        "id": run_id,
        "timestamp": timestamp,
        "query": query,
        "citations_count": len(citations),
        "html_file": f"{run_id}.html",
        "engine": engine,
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
        "engine": run.get("engine", "last30days"),
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
    _emit_telemetry("RESEARCH", f"Feed '{feed.name}' ingested ({run.results_count} new)")
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

    uvicorn.run(app, host="127.0.0.1", port=8766, reload=False)
