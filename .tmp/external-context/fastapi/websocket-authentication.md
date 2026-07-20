---
source: Context7 API + Official FastAPI Docs + JWT Tutorial
library: FastAPI
package: fastapi
topic: WebSocket authentication
fetched: 2026-07-16T00:00:00Z
official_docs: https://fastapi.tiangolo.com/advanced/websockets/
---

# WebSocket Authentication in FastAPI

## Overview

WebSockets cannot use standard HTTP `Authorization` headers in browsers.
Authentication must happen via:
1. **Query parameter** (token in URL)
2. **Cookie** (session cookie)
3. **First message** after connection
4. **Subprotocol header** (advanced)

## Method 1: Depends with Cookie/Query Token

Use FastAPI's dependency injection with `Cookie` and `Query`:

```python
from typing import Annotated
from fastapi import FastAPI, WebSocket, WebSocketException, status
from fastapi import Cookie, Query, Depends

app = FastAPI()

async def get_cookie_or_token(
    websocket: WebSocket,
    session: Annotated[str | None, Cookie(default=None)] = None,
    token: Annotated[str | None, Query(default=None)] = None,
):
    if session is None and token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return session or token

@app.websocket("/items/{item_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    item_id: str,
    cookie_or_token: Annotated[str, Depends(get_cookie_or_token)],
):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(
            f"Session cookie or query token value is: {cookie_or_token}"
        )
```

## Method 2: JWT Token Validation

```python
import jwt
from datetime import datetime, timedelta, timezone

SECRET_KEY = "your-secret-key-here"
ALGORITHM = "HS256"

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def validate_ws_token(
    websocket: WebSocket,
    token: Annotated[str | None, Query(default=None)] = None,
):
    """Dependency that validates JWT token from query parameter."""
    if token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
        return username
    except jwt.InvalidTokenError:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    username: Annotated[str, Depends(validate_ws_token)],
):
    await websocket.accept()
    await websocket.send_text(f"Authenticated as: {username}")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"{username}: {data}")
    except WebSocketDisconnect:
        pass
```

## Method 3: First-Message Authentication

Authenticate immediately after connecting, before entering the main loop:

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # First message must be a JSON auth payload
    auth_msg = await websocket.receive_json()

    token = auth_msg.get("token")
    if not token or not verify_token(token):
        await websocket.send_json({"error": "Unauthorized"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = decode_token(token)
    await websocket.send_json({"status": "authenticated", "user": user["sub"]})

    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        pass
```

## Method 4: Cookie-Based Session (FastAPI Depends)

```python
from fastapi import Cookie

async def get_session_from_cookie(
    websocket: WebSocket,
    session_id: Annotated[str | None, Cookie(default=None)] = None,
):
    if session_id is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    # Validate session against your database
    user = await db.get_user_by_session(session_id)
    if user is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    return user

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user: Annotated[User, Depends(get_session_from_cookie)],
):
    await websocket.accept()
    # user is now a validated User object
    while True:
        data = await websocket.receive_text()
        await websocket.broadcast(f"{user.username}: {data}")
```

## Starlette Subprotocol Authorization (Advanced)

Use the WebSocket subprotocol header for auth (browser clients can set this):

```python
async def is_authorized(websocket: WebSocket) -> bool:
    subprotocols = websocket.scope.get("subprotocols", [])
    if len(subprotocols) < 2:
        return False
    if subprotocols[0] != "Authorization":
        return False
    # Validate the token from subprotocols[1]
    try:
        payload = jwt.decode(subprotocols[1], SECRET_KEY, algorithms=[ALGORITHM])
        return True
    except jwt.InvalidTokenError:
        return False

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not await is_authorized(websocket):
        raise HTTPException(status_code=401, detail="Unauthorized")
    await websocket.accept("Authorization")
    # ... handle connection
```

## Client-Side Connection with Auth

### JavaScript (Browser)
```javascript
// Token in query parameter
const token = getJwtToken();
const ws = new WebSocket(`ws://localhost:8000/ws?token=${token}`);

// Token after connection (first-message auth)
const ws = new WebSocket("ws://localhost:8000/ws");
ws.onopen = function() {
    ws.send(JSON.stringify({ token: getJwtToken() }));
};
```

### Python Client
```python
import websockets
import jwt

token = create_access_token({"sub": "user123"})

async with websockets.connect(f"ws://localhost:8000/ws?token={token}") as ws:
    msg = await ws.recv()
    print(msg)
```

## Key Notes

- **Never use `HTTPException`** in WebSocket endpoints — use `WebSocketException` instead
- Use `status.WS_1008_POLICY_VIOLATION` (1008) for auth failures
- Query parameter tokens appear in server logs and browser history — use HTTPS in production
- Cookie-based auth is preferred for browser clients (HTTP-only, secure cookies)
- For production, combine JWT with short-lived tokens and refresh mechanisms
