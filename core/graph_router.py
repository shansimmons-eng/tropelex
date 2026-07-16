"""
Knowledge Graph API — serves decision graph data for D3 visualization.

Provides nodes (decisions) and edges (relationships) from the DecisionTree.
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from core.decision_tree import DecisionTree
from core.knowledge_decay import score_decisions

logger = logging.getLogger("tropelex.graph")

graph_router = APIRouter(prefix="/api/memory", tags=["graph"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


def _load_memory(project: str) -> dict[str, Any]:
    path = BASE_DIR / "memory" / f"{project}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return json.loads(path.read_text())


@graph_router.get("/{project}/graph")
async def decision_graph(
    project: str,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
) -> dict[str, Any]:
    """Return decision graph nodes and edges for D3 visualization.

    Nodes carry: id, label, confidence, tier, timestamp, source, categories.
    Edges carry: source, target, relationship.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("graph load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    decisions = memory.get("decisions", [])
    if not decisions:
        return {"nodes": [], "edges": [], "stats": {"total": 0}}

    tree = DecisionTree.from_decisions(decisions)
    scored = score_decisions(decisions)
    score_map = {s.get("decision", ""): s for s in scored}

    nodes = []
    for did, node in tree.nodes.items():
        conf = score_map.get(node.get("decision", ""), {})
        score = conf.get("score", 0.5)
        if score < min_confidence:
            continue
        nodes.append({
            "id": did,
            "label": (node.get("decision", "") or did)[:60],
            "full_text": node.get("decision", ""),
            "context": node.get("context", ""),
            "confidence": round(score, 3),
            "tier": conf.get("tier", "medium"),
            "timestamp": node.get("timestamp", ""),
            "source": node.get("source", "manual"),
            "categories": node.get("categories", []),
        })

    # Only include edges where both nodes passed the filter
    node_ids = {n["id"] for n in nodes}
    edges = []
    for edge in tree.edges:
        if edge["source"] in node_ids and edge["target"] in node_ids:
            edges.append({
                "source": edge["source"],
                "target": edge["target"],
                "relationship": edge["relationship"],
            })

    stats = tree.stats()
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_decisions": stats["total_decisions"],
            "total_edges": stats["total_edges"],
            "relationship_counts": stats["relationship_counts"],
            "filtered_nodes": len(nodes),
        },
    }
