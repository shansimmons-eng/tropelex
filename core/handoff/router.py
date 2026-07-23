"""
Agent Handoff Packets — FastAPI router.

Mount into the main app:
    from core.handoff.router import handoff_router
    app.include_router(handoff_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.handoff.packet_builder import (
    HandoffPacket,
    ContextSlice,
    build_handoff_packet,
    ROLE_PROFILES,
)
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.handoff")

handoff_router = APIRouter(prefix="/api/memory", tags=["handoff"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


class HandoffRequest(BaseModel):
    role: str
    token_budget: int = 4000


@handoff_router.post("/{project}/handoff")
async def generate_handoff(project: str, req: HandoffRequest) -> dict[str, Any]:
    """Generate a role-aware context packet for agent handoff."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("handoff load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    packet: HandoffPacket = build_handoff_packet(
        project=project,
        role=req.role,
        memory=memory,
        token_budget=req.token_budget,
    )

    # Convert dataclasses to dicts for JSON serialization
    return {
        "role": packet.role,
        "project": packet.project,
        "context_slices": [
            {
                "category": s.category,
                "content": s.content,
                "priority": s.priority,
                "token_estimate": s.token_estimate,
            }
            for s in packet.context_slices
        ],
        "active_decisions": packet.active_decisions,
        "recent_sessions": packet.recent_sessions,
        "token_count": packet.token_count,
        "token_budget": packet.token_budget,
        "skills_summary": packet.skills_summary,
        "generated_at": packet.generated_at,
    }


@handoff_router.get("/{project}/handoff/roles")
async def list_roles(project: str) -> dict[str, Any]:
    """List available handoff roles and their descriptions."""
    return {
        "roles": {
            name: profile["description"]
            for name, profile in ROLE_PROFILES.items()
        }
    }
