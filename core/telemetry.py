"""
Live Telemetry — in-memory event log for the dashboard's terminal drawer.

Ephemeral, ring-buffered, no persistence. Any router or handler can import
_emit_telemetry() and push an event; the frontend polls GET /api/telemetry/recent
with a monotonic since_id cursor to fetch what's new since its last poll.
"""

from collections import deque
from datetime import datetime, timezone
from itertools import count
from typing import Any

from fastapi import APIRouter, Query

_telemetry_log: deque[dict[str, Any]] = deque(maxlen=200)
_telemetry_seq = count(1)


def _emit_telemetry(kind: str, message: str) -> dict[str, Any]:
    """Append an event to the ring buffer. kind is a short tag like OK/DECAY/RESEARCH/GHOST."""
    entry = {
        "id": next(_telemetry_seq),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "message": f"[{kind}] {message}",
    }
    _telemetry_log.append(entry)
    return entry


telemetry_router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@telemetry_router.get("/recent")
async def get_recent_telemetry(since_id: int = Query(0, ge=0)) -> dict[str, Any]:
    """Events with id > since_id, plus the latest id seen (poll cursor)."""
    events = [e for e in _telemetry_log if e["id"] > since_id]
    latest_id = _telemetry_log[-1]["id"] if _telemetry_log else since_id
    return {"events": events, "latest_id": latest_id}
