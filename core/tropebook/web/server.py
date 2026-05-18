"""
Tropebook Web API - FastAPI server for Tropebook web interface
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
import uvicorn

from core.tropebook import Tropebook, create_researcher, create_importer, SourceType
from core.tropebook.tropebook import Citation

class CitationCreate(BaseModel):
    title: str
    url: str
    summary: str = ""
    source: str = ""
    tags: List[str] = []
    entities: List[str] = []

class CitationUpdate(BaseModel):
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    entities: Optional[List[str]] = None

class SearchRequest(BaseModel):
    query: str
    num_results: int = 10

class LinkRequest(BaseModel):
    source_url: str
    target_url: str
    relationship: str

class ImportRequest(BaseModel):
    data: Dict[str, Any]
    source_type: str = "deep_research"

app_state: Dict[str, Any] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state["tropebook"] = Tropebook()
    app_state["researcher"] = create_researcher()
    yield

app = FastAPI(title="Tropebook API", version="1.0.0", lifespan=lifespan)

templates = Jinja2Templates(directory="core/tropebook/web/templates")
app.mount("/static", StaticFiles(directory="core/tropebook/web/static"), name="static")

@app.get("/")
async def root():
    return FileResponse("core/tropebook/web/templates/index.html")

@app.get("/api/citations")
async def list_citations(tag: Optional[str] = None, source: Optional[str] = None):
    tb = app_state["tropebook"]
    if tag:
        citations = tb.find_by_tag(tag)
    elif source:
        source_type = SourceType(source) if source in [s.value for s in SourceType] else SourceType.MANUAL
        citations = tb.find_by_source(source_type)
    else:
        citations = list(tb.citations.values())
    return {"citations": [c.to_dict() for c in citations], "count": len(citations)}

@app.get("/api/citations/{cid}")
async def get_citation(cid: str):
    tb = app_state["tropebook"]
    citation = tb.get(cid)
    if not citation:
        raise HTTPException(status_code=404, detail="Citation not found")
    return citation.to_dict()

@app.post("/api/citations")
async def create_citation(citation: CitationCreate):
    tb = app_state["tropebook"]
    cid = tb.add(
        title=citation.title,
        url=citation.url,
        summary=citation.summary,
        source=citation.source,
        tags=citation.tags,
        entities=citation.entities
    )
    return {"id": cid, "citation": tb.get(cid).to_dict()}

@app.patch("/api/citations/{cid}")
async def update_citation(cid: str, update: CitationUpdate):
    tb = app_state["tropebook"]
    tb.update(cid, **update.model_dump(exclude_none=True))
    return {"updated": True}

@app.delete("/api/citations/{cid}")
async def delete_citation(cid: str):
    tb = app_state["tropebook"]
    if cid not in tb.citations:
        raise HTTPException(status_code=404, detail="Citation not found")
    del tb.citations[cid]
    tb._build_index()
    tb._save()
    return {"deleted": True}

@app.get("/api/search")
async def search_citations(q: str = Query(..., min_length=1), limit: int = 20):
    tb = app_state["tropebook"]
    results = tb.search(q, limit)
    return {"results": [r.to_dict() for r in results], "count": len(results)}

@app.post("/api/research")
async def research(query: str = Query(...), num_results: int = Query(10, le=20)):
    researcher = app_state["researcher"]
    results = researcher.research(query, num_results)
    return {
        "results": [
            {"title": r.title, "url": r.url, "description": r.description, "source": r.source}
            for r in results
        ],
        "count": len(results)
    }

@app.get("/api/related/{cid}")
async def get_related(cid: str, depth: int = Query(1, ge=1, le=3)):
    tb = app_state["tropebook"]
    related = tb.get_related(cid, depth)
    return {
        "related": {cid: c.to_dict() for cid, c in related.items()},
        "count": len(related)
    }

@app.post("/api/links")
async def create_link(link: LinkRequest):
    tb = app_state["tropebook"]
    tb.add_relationship(link.source_url, link.target_url, link.relationship)
    return {"created": True}

@app.get("/api/tags")
async def list_tags():
    tb = app_state["tropebook"]
    return {"tags": list(tb._index["by_tag"].keys())}

@app.get("/api/entities")
async def list_entities():
    tb = app_state["tropebook"]
    return {"entities": list(tb._index["by_entity"].keys())}

@app.get("/api/stats")
async def get_stats():
    tb = app_state["tropebook"]
    return tb.stats()

@app.post("/api/import")
async def import_sources(import_req: ImportRequest):
    tb = app_state["tropebook"]
    count = tb.import_from_deep_research(import_req.data)
    return {"imported": count}

@app.get("/api/export")
async def export_all():
    tb = app_state["tropebook"]
    return tb.export_json()

def run_server(host: str = "0.0.0.0", port: int = 8765):
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    run_server()