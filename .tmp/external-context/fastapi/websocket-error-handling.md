---
source: Context7 API + Official FastAPI Docs
library: FastAPI
package: fastapi
topic: WebSocket error handling and reconnection patterns
fetched: 2026-07-16T00:00:00Z
official_docs: https://fastapi.tiangolo.com/advanced/websockets/
---

# WebSocket Error Handling & Reconnection Patterns

## Server-Side Error Handling

### Complete Error Handling Pattern

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
import logging

logger = logging.getLogger(__name__)
app = FastAPI()

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    try:
        await websocket.accept()
    except Exception as e:
        logger.error(f"Failed to accept WebSocket for {client_id}: {e}")
        return

    try:
        while True:
            try:
                data = await websocket.receive_text()
                # Process message...
                await websocket.send_text(f"Processed: {data}")
            except Exception as e:
                logger.error(f"Error processing message from {client_id}: {e}")
                # Continue listening — don't close on single message errors
                await websocket.send_text(f"Error processing your message: {str(e)}")

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected normally")
        manager.disconnect(client_id)
        await manager.broadcast(f"Client {client_id} left")

    except Exception as e:
        logger.error(f"Unexpected error for {client_id}: {e}")
        manager.disconnect(client_id)

    finally:
        # Always clean up
        try:
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
        except Exception:
            pass  # Already closed
```

### Sending Error Responses to Clients

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()

            # Validate message structure
            if "type" not in data:
                await websocket.send_json({
                    "error": "Missing 'type' field",
                    "code": "INVALID_MESSAGE"
                })
                continue

            # Process based on type
            result = await process_message(data)
            if result.error:
                await websocket.send_json({
                    "error": result.error,
                    "code": result.error_code
                })
            else:
                await websocket.send_json({"data": result.data})

    except WebSocketDisconnect:
        pass
```

## Client-Side Reconnection Patterns

### Exponential Backoff Reconnection (JavaScript)

```javascript
class ReconnectingWebSocket {
    constructor(url, maxRetries = 10) {
        this.url = url;
        this.maxRetries = maxRetries;
        this.retryCount = 0;
        this.baseDelay = 1000; // 1 second
        this.maxDelay = 30000; // 30 seconds
        this.connect();
    }

    connect() {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            console.log("WebSocket connected");
            this.retryCount = 0; // Reset on successful connection
        };

        this.ws.onclose = (event) => {
            if (event.code === 1000) {
                console.log("WebSocket closed normally");
                return; // Don't reconnect on normal close
            }
            this.reconnect();
        };

        this.ws.onerror = (error) => {
            console.error("WebSocket error:", error);
        };
    }

    reconnect() {
        if (this.retryCount >= this.maxRetries) {
            console.error("Max reconnection attempts reached");
            return;
        }

        // Exponential backoff with jitter
        const delay = Math.min(
            this.baseDelay * Math.pow(2, this.retryCount) + Math.random() * 1000,
            this.maxDelay
        );

        console.log(`Reconnecting in ${delay}ms (attempt ${this.retryCount + 1})`);

        setTimeout(() => {
            this.retryCount++;
            this.connect();
        }, delay);
    }

    send(data) {
        if (this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(data);
        } else {
            console.warn("WebSocket not open, queuing message");
            // Could implement a message queue here
        }
    }
}

// Usage
const ws = new ReconnectingWebSocket("ws://localhost:8000/ws");
ws.ws.onmessage = (event) => {
    console.log("Received:", event.data);
};
```

### Python Client with Reconnection

```python
import asyncio
import websockets
import logging

logger = logging.getLogger(__name__)

async def connect_with_reconnect(url, max_retries=10):
    retry_count = 0
    base_delay = 1.0
    max_delay = 30.0

    while retry_count < max_retries:
        try:
            async with websockets.connect(url) as ws:
                logger.info("Connected to WebSocket")
                retry_count = 0  # Reset on success

                async for message in ws:
                    logger.info(f"Received: {message}")

        except websockets.ConnectionClosed as e:
            logger.warning(f"Connection closed: {e}")
        except ConnectionRefusedError:
            logger.warning("Connection refused")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

        # Exponential backoff
        delay = min(base_delay * (2 ** retry_count), max_delay)
        logger.info(f"Reconnecting in {delay}s (attempt {retry_count + 1})")
        await asyncio.sleep(delay)
        retry_count += 1

    logger.error("Max reconnection attempts reached")
```

## WebSocket Close Codes Reference

| Code | Name | When to Use |
|------|------|-------------|
| 1000 | Normal Closure | Intentional close |
| 1001 | Going Away | Client navigating away |
| 1002 | Protocol Error | Protocol violation |
| 1003 | Unsupported Data | Received unsupported data type |
| 1006 | Abnormal Closure | Connection lost without close frame |
| 1008 | Policy Violation | Auth failure, rule violation |
| 1009 | Message Too Big | Message exceeds size limit |
| 1011 | Internal Error | Server-side unexpected error |
| 1012 | Service Restart | Server is restarting |
| 1013 | Try Again Later | Server overloaded |

## Heartbeat/Ping Pattern

Keep connections alive and detect dead clients:

```python
import asyncio
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()
HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 10   # seconds

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    last_pong = time.time()
    alive = True

    async def heartbeat():
        nonlocal alive, last_pong
        while alive:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await websocket.send_json({"type": "ping"})
                # If no pong received within timeout, mark as dead
                if time.time() - last_pong > HEARTBEAT_INTERVAL + HEARTBEAT_TIMEOUT:
                    alive = False
            except Exception:
                alive = False

    async def receive_loop():
        nonlocal last_pong, alive
        try:
            while alive:
                data = await websocket.receive_json()
                if data.get("type") == "pong":
                    last_pong = time.time()
                else:
                    await process_message(data)
        except WebSocketDisconnect:
            alive = False
        except Exception:
            alive = False

    # Run both concurrently
    try:
        await asyncio.gather(heartbeat(), receive_loop())
    finally:
        await websocket.close()
```

## Connection Cleanup Best Practices

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.connection_metadata: dict[str, dict] = {}

    async def connect(self, client_id: str, websocket: WebSocket, metadata: dict = None):
        # Close existing connection if client reconnects
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].close(code=1000)
            except Exception:
                pass

        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.connection_metadata[client_id] = metadata or {}

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        self.connection_metadata.pop(client_id, None)

    async def safe_send(self, client_id: str, data: str) -> bool:
        """Send message with automatic cleanup on failure."""
        ws = self.active_connections.get(client_id)
        if ws is None:
            return False
        try:
            await ws.send_text(data)
            return True
        except Exception:
            self.disconnect(client_id)
            return False

    async def broadcast(self, message: str):
        """Send to all clients, cleaning up dead connections."""
        disconnected = []
        for client_id, ws in self.active_connections.items():
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect(client_id)
```
