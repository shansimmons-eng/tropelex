---
source: Context7 API + Official FastAPI Docs
library: FastAPI
package: fastapi
topic: WebSocket connection management and broadcasting
fetched: 2026-07-16T00:00:00Z
official_docs: https://fastapi.tiangolo.com/advanced/websockets/
---

# WebSocket Connection Management & Broadcasting

## ConnectionManager Pattern (Official FastAPI Pattern)

The canonical way to manage multiple WebSocket clients in FastAPI:

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()
```

## Chat Room with Broadcasting

```python
html = """<!DOCTYPE html>
<html>
<head><title>Chat</title></head>
<body>
    <h1>WebSocket Chat</h1>
    <h2>Your ID: <span id="ws-id"></span></h2>
    <form onsubmit="sendMessage(event)">
        <input type="text" id="messageText" autocomplete="off"/>
        <button>Send</button>
    </form>
    <ul id='messages'></ul>
    <script>
        var client_id = Math.random().toString(36).substr(2, 9);
        document.getElementById("ws-id").textContent = client_id;
        var ws = new WebSocket(`ws://localhost:8000/ws/${client_id}`);
        ws.onmessage = function(event) {
            var messages = document.getElementById('messages');
            var message = document.createElement('li');
            var content = document.createTextNode(event.data);
            message.appendChild(content);
            messages.appendChild(message);
        };
        function sendMessage(event) {
            var input = document.getElementById("messageText");
            ws.send(input.value);
            input.value = '';
            event.preventDefault();
        }
    </script>
</body>
</html>"""

@app.get("/")
async def get():
    return HTMLResponse(html)

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal_message(f"You wrote: {data}", websocket)
            await manager.broadcast(f"Client #{client_id} says: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"Client #{client_id} left the chat")
```

## Enhanced ConnectionManager with Client IDs

```python
class ConnectionManager:
    def __init__(self):
        # Map client_id -> WebSocket for targeted messaging
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            try:
                await connection.send_text(message)
            except Exception:
                # Connection may be dead; clean up
                pass

    def get_connected_clients(self) -> list[str]:
        return list(self.active_connections.keys())
```

## Production: Scaling with Broadcaster (Redis/Kafka/Postgres)

**⚠️ Important**: The in-memory `ConnectionManager` only works with a single process.
For multi-worker or multi-server deployments, use [encode/broadcaster](https://github.com/encode/broadcaster).

### Installation

```bash
pip install broadcaster
pip install broadcaster[redis]    # Redis PUB/SUB backend
pip install broadcaster[postgres] # Postgres LISTEN/NOTIFY backend
pip install broadcaster[kafka]    # Apache Kafka backend
```

### Available Backends

```python
Broadcast('memory://')                        # In-memory (single process)
Broadcast("redis://localhost:6379")           # Redis PUB/SUB
Broadcast("redis-stream://localhost:6379")    # Redis Streams
Broadcast("postgres://localhost:5432/db")     # Postgres LISTEN/NOTIFY
Broadcast("kafka://localhost:9092")           # Apache Kafka
```

### Broadcaster Pattern with FastAPI

```python
from contextlib import asynccontextmanager
from broadcaster import Broadcast
from fastapi import FastAPI, WebSocket

broadcast = Broadcast("redis://localhost:6379")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await broadcast.connect()
    yield
    await broadcast.disconnect()

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws/{room_id}")
async def websocket_room(websocket: WebSocket, room_id: str):
    await websocket.accept()

    async with broadcast.subscribe(channel=room_id) as subscriber:
        async def receiver():
            async for message in websocket.iter_text():
                await broadcast.publish(channel=room_id, message=message)

        async def sender():
            async for event in subscriber:
                await websocket.send_text(event.message)

        # Run both concurrently; cancel on disconnect
        import anyio
        async with anyio.create_task_group() as tg:
            tg.start_soon(receiver)
            tg.start_soon(sender)
```

## Handling WebSocketDisconnect Exception

When a WebSocket connection is closed, `await websocket.receive_text()` raises
`WebSocketDisconnect`. Always wrap the receive loop in a try/except:

```python
from fastapi import WebSocketDisconnect

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        # Client disconnected gracefully
        print("Client disconnected")
    except Exception as e:
        # Unexpected error
        print(f"WebSocket error: {e}")
    finally:
        # Clean up resources
        pass
```
