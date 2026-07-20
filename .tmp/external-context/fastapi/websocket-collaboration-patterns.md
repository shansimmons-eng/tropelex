---
source: Synthesized from Context7 API + Official FastAPI Docs + Broadcaster + Best Practices
library: FastAPI
package: fastapi
topic: real-time collaboration patterns
fetched: 2026-07-16T00:00:00Z
official_docs: https://fastapi.tiangolo.com/advanced/websockets/
---

# Real-Time Collaboration — Complete Implementation

## Full Application Structure

```
project/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + lifespan
│   ├── auth.py              # JWT auth dependencies
│   ├── websocket/
│   │   ├── __init__.py
│   │   ├── manager.py       # ConnectionManager
│   │   ├── router.py        # WebSocket routes
│   │   └── models.py        # WS message schemas
│   └── models.py            # DB models
├── requirements.txt
└── .env
```

## 1. Connection Manager (Production-Grade)

```python
# app/websocket/manager.py
import asyncio
import json
import time
from dataclasses import dataclass, field
from fastapi import WebSocket, WebSocketDisconnect
import logging

logger = logging.getLogger(__name__)

@dataclass
class ClientConnection:
    websocket: WebSocket
    client_id: str
    user_id: str
    room_id: str
    connected_at: float = field(default_factory=time.time)
    last_pong: float = field(default_factory=time.time)

class ConnectionManager:
    """Thread-safe, production-ready WebSocket connection manager."""

    def __init__(self):
        # room_id -> {client_id -> ClientConnection}
        self.rooms: dict[str, dict[str, ClientConnection]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, client_id: str, user_id: str, room_id: str):
        async with self._lock:
            await websocket.accept()

            # Disconnect existing connection for same user in same room
            if room_id in self.rooms and client_id in self.rooms[room_id]:
                existing = self.rooms[room_id][client_id]
                try:
                    await existing.websocket.close(code=1000, reason="Reconnected")
                except Exception:
                    pass

            connection = ClientConnection(
                websocket=websocket,
                client_id=client_id,
                user_id=user_id,
                room_id=room_id,
            )

            if room_id not in self.rooms:
                self.rooms[room_id] = {}
            self.rooms[room_id][client_id] = connection

        logger.info(f"Client {client_id} (user={user_id}) connected to room {room_id}")

    async def disconnect(self, client_id: str, room_id: str):
        async with self._lock:
            if room_id in self.rooms:
                self.rooms[room_id].pop(client_id, None)
                if not self.rooms[room_id]:
                    del self.rooms[room_id]

        logger.info(f"Client {client_id} disconnected from room {room_id}")

    async def broadcast_to_room(self, room_id: str, message: dict, exclude_client: str | None = None):
        """Broadcast JSON message to all clients in a room."""
        if room_id not in self.rooms:
            return

        payload = json.dumps(message)
        disconnected = []

        for client_id, conn in self.rooms[room_id].items():
            if client_id == exclude_client:
                continue
            try:
                await conn.websocket.send_text(payload)
            except Exception:
                disconnected.append(client_id)

        for client_id in disconnected:
            await self.disconnect(client_id, room_id)

    async def send_to_user(self, user_id: str, message: dict):
        """Send message to all connections of a specific user across rooms."""
        payload = json.dumps(message)
        for room_id in list(self.rooms.keys()):
            for client_id, conn in list(self.rooms[room_id].items()):
                if conn.user_id == user_id:
                    try:
                        await conn.websocket.send_text(payload)
                    except Exception:
                        await self.disconnect(client_id, room_id)

    def get_room_users(self, room_id: str) -> list[str]:
        if room_id in self.rooms:
            return [conn.user_id for conn in self.rooms[room_id].values()]
        return []

    def get_user_rooms(self, user_id: str) -> list[str]:
        return [
            room_id for room_id, clients in self.rooms.items()
            if any(c.user_id == user_id for c in clients.values())
        ]

manager = ConnectionManager()
```

## 2. WebSocket Router with Auth

```python
# app/websocket/router.py
import json
import uuid
from datetime import datetime
from typing import Annotated
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from app.auth import validate_ws_token
from app.websocket.manager import manager

router = APIRouter()

@router.websocket("/ws/{room_id}")
async def collaboration_ws(
    websocket: WebSocket,
    room_id: str,
    token: Annotated[str, Query(default=None)],
):
    # Authenticate before accepting
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return

    try:
        user_id = await validate_ws_token(token)
    except Exception:
        await websocket.close(code=1008, reason="Invalid token")
        return

    client_id = str(uuid.uuid4())[:8]
    await manager.connect(websocket, client_id, user_id, room_id)

    # Notify room about new user
    await manager.broadcast_to_room(room_id, {
        "type": "user_joined",
        "user_id": user_id,
        "client_id": client_id,
        "timestamp": datetime.utcnow().isoformat(),
        "users": manager.get_room_users(room_id),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            msg_type = message.get("type")

            if msg_type == "content_update":
                # Broadcast cursor/edits to all other clients
                await manager.broadcast_to_room(room_id, {
                    "type": "content_update",
                    "user_id": user_id,
                    "data": message.get("data"),
                    "timestamp": datetime.utcnow().isoformat(),
                }, exclude_client=client_id)

            elif msg_type == "cursor_move":
                await manager.broadcast_to_room(room_id, {
                    "type": "cursor_move",
                    "user_id": user_id,
                    "position": message.get("position"),
                    "timestamp": datetime.utcnow().isoformat(),
                }, exclude_client=client_id)

            elif msg_type == "ping":
                # Update last_pong timestamp
                if room_id in manager.rooms and client_id in manager.rooms[room_id]:
                    import time
                    manager.rooms[room_id][client_id].last_pong = time.time()
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({
                    "error": f"Unknown message type: {msg_type}"
                })

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(client_id, room_id)
        await manager.broadcast_to_room(room_id, {
            "type": "user_left",
            "user_id": user_id,
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "users": manager.get_room_users(room_id),
        })
```

## 3. Auth Module

```python
# app/auth.py
import jwt
from fastapi import Query, WebSocketException, status

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"

async def validate_ws_token(token: str) -> str:
    """Validate JWT token, return user_id."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError("No subject in token")
        return user_id
    except jwt.ExpiredSignatureError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    except jwt.InvalidTokenError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
```

## 4. Main App with Lifespan

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.websocket.router import router as ws_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize broadcaster if using Redis
    # await broadcast.connect()
    yield
    # Shutdown: cleanup
    # await broadcast.disconnect()

app = FastAPI(lifespan=lifespan)
app.include_router(ws_router)
```

## 5. Client-Side (JavaScript) Collaboration Client

```javascript
class CollaborationClient {
    constructor(roomId, token) {
        this.roomId = roomId;
        this.token = token;
        this.handlers = new Map();
        this.reconnectAttempts = 0;
        this.maxReconnects = 10;
        this.connect();
    }

    connect() {
        const ws = new WebSocket(
            `ws://localhost:8000/ws/${this.roomId}?token=${this.token}`
        );

        ws.onopen = () => {
            this.reconnectAttempts = 0;
            this.emit("connected");
            // Start heartbeat
            this.heartbeatInterval = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: "ping" }));
                }
            }, 30000);
        };

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            this.emit(msg.type, msg);
        };

        ws.onclose = (event) => {
            clearInterval(this.heartbeatInterval);
            if (event.code !== 1000) {
                this.reconnect();
            }
        };

        ws.onerror = () => {
            clearInterval(this.heartbeatInterval);
        };

        this.ws = ws;
    }

    reconnect() {
        if (this.reconnectAttempts >= this.maxReconnects) {
            this.emit("max_retries_reached");
            return;
        }
        const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30000);
        setTimeout(() => {
            this.reconnectAttempts++;
            this.connect();
        }, delay + Math.random() * 1000);
    }

    send(type, data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, ...data }));
        }
    }

    on(event, handler) {
        if (!this.handlers.has(event)) this.handlers.set(event, []);
        this.handlers.get(event).push(handler);
    }

    emit(event, data) {
        (this.handlers.get(event) || []).forEach(h => h(data));
    }

    disconnect() {
        clearInterval(this.heartbeatInterval);
        if (this.ws) this.ws.close(1000, "Client disconnect");
    }
}

// Usage
const client = new CollaborationClient("room-123", jwtToken);
client.on("content_update", (msg) => updateEditor(msg.data));
client.on("cursor_move", (msg) => updateCursor(msg.user_id, msg.position));
client.on("user_joined", (msg) => showNotification(`${msg.user_id} joined`));
client.on("user_left", (msg) => showNotification(`${msg.user_id} left`));
```

## Key Takeaways

1. **Never trust client state** — always validate auth on every WS connection
2. **Use `exclude_client`** — don't echo messages back to the sender
3. **Clean up on disconnect** — always use try/finally with WebSocketDisconnect
4. **Broadcast with dead-connection cleanup** — remove clients that fail to send
5. **Scale with Broadcaster** — in-memory only works for single process
6. **Heartbeat** — detect stale connections every 30s
7. **Reconnection with backoff** — exponential backoff + jitter, cap at 30s
8. **JSON message protocol** — always use `type` field for message routing
