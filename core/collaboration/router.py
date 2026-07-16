"""
WebSocket collaboration router for Tropelex.
Provides a /ws/{room_id} endpoint backed by ConnectionManager.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.collaboration.connection_manager import ConnectionManager

logger = logging.getLogger("tropelex.collaboration")

router = APIRouter()

# Shared ConnectionManager — call manager.start() / manager.stop() at app lifecycle
manager = ConnectionManager(heartbeat_interval=30.0)


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    client_id: str = Query(..., min_length=1, max_length=128),
) -> None:
    """
    Real-time collaboration WebSocket.

    Query params:
        client_id — unique identifier for this client session.

    Accepted message JSON:
        {"type": "message", "content": "..."}  — broadcast to room
    """

    # --- handshake ---
    await websocket.accept()
    await manager.connect(client_id, room_id, websocket)

    # Broadcast a join notification so other clients know
    join_payload = json.dumps({
        "type": "system",
        "content": f"{client_id} joined",
    })
    await manager.broadcast(room_id, join_payload)

    logger.info("Client %s connected to room %s", client_id, room_id)

    # --- main receive loop ---
    try:
        while True:
            raw = await _receive_text_safe(websocket)

            try:
                data: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": "Invalid JSON",
                }))
                continue

            msg_type = data.get("type", "")

            if msg_type == "message":
                content = data.get("content", "")
                if not content:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": "Message content must not be empty",
                    }))
                    continue

                broadcast_payload = json.dumps({
                    "type": "message",
                    "client_id": client_id,
                    "content": content,
                })
                await manager.broadcast(room_id, broadcast_payload)

            elif msg_type == "ping":
                # Application-level heartbeat acknowledgement
                await websocket.send_text(json.dumps({"type": "pong"}))

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Unknown message type: {msg_type}",
                }))

    except WebSocketDisconnect:
        logger.info("Client %s disconnected from room %s", client_id, room_id)
    except Exception:
        logger.exception("Unexpected error for client %s in room %s", client_id, room_id)
    finally:
        # Notify room and clean up
        leave_payload = json.dumps({
            "type": "system",
            "content": f"{client_id} left",
        })
        await manager.disconnect(client_id, room_id)
        await manager.broadcast(room_id, leave_payload)


async def _receive_text_safe(websocket: WebSocket) -> str:
    """Receive a text frame, raising WebSocketDisconnect on disconnect/non-text frames.

    Starlette's WebSocket.receive() already validates the ASGI message shape
    (raising RuntimeError for malformed events), so this only needs to
    translate "websocket.disconnect" into WebSocketDisconnect and extract
    the "text" payload from "websocket.receive" events.
    """
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(code=message.get("code", 1000))
    text = message.get("text")
    if text is None:
        # Binary frame with no "text" key — treat as a disconnect-worthy error.
        raise WebSocketDisconnect(code=1003)  # unsupported data
    return text
