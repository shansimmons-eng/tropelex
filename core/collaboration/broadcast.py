"""
Memory change broadcast — notifies WebSocket collaboration rooms
when memory data is modified.

Intended to be called from server endpoints after a successful
save/update/delete operation, so connected clients see live updates.
"""

import json
import logging
from typing import Any

from core.collaboration.connection_manager import ConnectionManager

logger = logging.getLogger("tropelex.broadcast")


async def broadcast_memory_change(
    manager: ConnectionManager,
    room_id: str,
    event: str,
    project_name: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Send a memory-change notification to all clients in a room.

    Args:
        manager: The active ConnectionManager instance.
        room_id: Room to broadcast to (e.g. "memory" or a project name).
        event: Event kind — "decision_added", "session_saved", "project_updated", etc.
        project_name: The affected project.
        details: Optional extra payload fields.
    """
    payload: dict[str, Any] = {
        "type": "memory_change",
        "event": event,
        "project": project_name,
    }
    if details:
        payload.update(details)

    message = json.dumps(payload)
    await manager.broadcast(room_id, message)
    logger.debug(
        "Broadcast %s for %s to room %s", event, project_name, room_id
    )
