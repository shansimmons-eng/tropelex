---
source: Context7 API + Official FastAPI Docs + Starlette Docs
library: FastAPI
package: fastapi
topic: WebSocket endpoint setup
fetched: 2026-07-16T00:00:00Z
official_docs: https://fastapi.tiangolo.com/advanced/websockets/
---

# FastAPI WebSocket Endpoint Setup

## Installation

```bash
pip install fastapi websockets uvicorn
```

## Basic WebSocket Endpoint

```python
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message text was: {data}")
```

## WebSocket with Path and Query Parameters

```python
@app.websocket("/items/{item_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    item_id: str,
    q: int | None = None,
):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message text was: {data}, for item ID: {item_id}")
        if q is not None:
            await websocket.send_text(f"Query parameter q is: {q}")
```

## Key WebSocket Methods (Starlette internals)

FastAPI's `WebSocket` class comes directly from Starlette:

- `await websocket.accept(subprotocol=None, headers=None)` — Accept the connection
- `await websocket.send_text(data)` — Send text data
- `await websocket.send_bytes(data)` — Send binary data
- `await websocket.send_json(data)` — Send JSON data
- `await websocket.receive_text()` — Receive text data
- `await websocket.receive_bytes()` — Receive binary data
- `await websocket.receive_json()` — Receive JSON data
- `await websocket.iter_text()` — Iterate over incoming text messages
- `await websocket.iter_bytes()` — Iterate over incoming binary messages
- `await websocket.close(code=1000, reason=None)` — Close the connection

## Accessing WebSocket Metadata

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # URL components
    websocket.url          # Full URL
    websocket.headers      # Request headers
    websocket.query_params # Query parameters dict
    websocket.path_params  # Path parameters dict

    await websocket.accept()
```

## Denying a WebSocket Connection (Starlette)

You can reject a connection before accepting it using `HTTPException`:

```python
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.exceptions import HTTPException

async def websocket_endpoint(websocket: WebSocket):
    # Inspect subprotocols or headers before accepting
    if not is_authorized(websocket):
        raise HTTPException(status_code=401, detail="Unauthorized")
    await websocket.accept()
    # ... handle connection

app = Starlette(routes=[WebSocketRoute("/ws", websocket_endpoint)])
```

## Complete HTML + WebSocket Client Example

```python
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

app = FastAPI()

html = """<!DOCTYPE html>
<html>
<head><title>Chat</title></head>
<body>
    <h1>WebSocket Chat</h1>
    <form onsubmit="sendMessage(event)">
        <input type="text" id="messageText" autocomplete="off"/>
        <button>Send</button>
    </form>
    <ul id='messages'></ul>
    <script>
        var ws = new WebSocket("ws://localhost:8000/ws");
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message text was: {data}")
```
