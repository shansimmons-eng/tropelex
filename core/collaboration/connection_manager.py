"""
WebSocket Connection Manager for Tropelex
Manages client connections per room with heartbeat and dead connection cleanup.
"""

import asyncio
from typing import Any, Dict, Set, Optional, Protocol
from dataclasses import dataclass, field
from datetime import datetime, timezone


class WebSocketLike(Protocol):
    """Protocol for objects that behave like websockets."""
    async def send_text(self, message: str) -> None: ...
    async def ping(self) -> None: ...
    async def close(self) -> None: ...


@dataclass
class ClientInfo:
    """Tracks metadata about a connected client."""
    client_id: str
    room_id: str
    connected_at: datetime
    last_pong: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_alive: bool = True


class ConnectionManager:
    """
    Manages WebSocket connections per room with heartbeat and cleanup.
    
    Thread-safe via asyncio.Lock. Tracks clients per room and
    periodically checks for dead connections.
    """
    
    def __init__(self, heartbeat_interval: float = 30.0):
        self._lock = asyncio.Lock()
        self._connections: Dict[str, Dict[str, WebSocketLike]] = {}  # room_id -> {client_id: ws}
        self._clients: Dict[str, ClientInfo] = {}  # client_id -> ClientInfo
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the heartbeat task."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
    
    async def stop(self) -> None:
        """Stop the heartbeat task and close all connections."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        
        async with self._lock:
            await self._close_all_connections()
    
    async def connect(self, client_id: str, room_id: str, websocket: WebSocketLike) -> None:
        """Add a client to a room."""
        async with self._lock:
            # If client already exists in this room, disconnect first
            if room_id in self._connections and client_id in self._connections[room_id]:
                await self._disconnect_client(client_id, room_id)
            
            # Create room if it doesn't exist (may have been deleted after disconnect)
            if room_id not in self._connections:
                self._connections[room_id] = {}
            
            self._connections[room_id][client_id] = websocket
            self._clients[client_id] = ClientInfo(
                client_id=client_id,
                room_id=room_id,
                connected_at=datetime.now(timezone.utc)
            )
    
    async def disconnect(self, client_id: str, room_id: str) -> None:
        """Remove a client from a room."""
        async with self._lock:
            await self._disconnect_client(client_id, room_id)
    
    async def broadcast(self, room_id: str, message: str) -> None:
        """Send a message to all clients in a room.
        
        Takes a snapshot of connections under the lock, then sends outside
        the lock to avoid deadlocks when clients are reading simultaneously.
        """
        async with self._lock:
            if room_id not in self._connections:
                return
            # Snapshot: copy (client_id, ws) pairs so we can release the lock
            # before performing potentially blocking sends.
            targets = list(self._connections[room_id].items())

        disconnected_clients = []
        for client_id, websocket in targets:
            try:
                await websocket.send_text(message)
            except Exception:
                disconnected_clients.append(client_id)

        # Clean up disconnected clients (re-acquire lock)
        if disconnected_clients:
            async with self._lock:
                if room_id in self._connections:
                    for cid in disconnected_clients:
                        if cid in self._connections[room_id]:
                            del self._connections[room_id][cid]
                            self._clients.pop(cid, None)
                    if not self._connections[room_id]:
                        del self._connections[room_id]
    
    def get_room_clients(self, room_id: str) -> Set[str]:
        """Get all client IDs in a room."""
        return set(self._connections.get(room_id, {}).keys())
    
    async def _heartbeat_loop(self) -> None:
        """Periodically check for dead connections."""
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            await self._check_dead_connections()
    
    async def _check_dead_connections(self) -> None:
        """Send pings and clean up unresponsive connections."""
        async with self._lock:
            for room_id in list(self._connections.keys()):
                disconnected_clients = []
                for client_id, websocket in self._connections[room_id].items():
                    try:
                        await websocket.ping()
                        # Update last pong time on successful ping
                        if client_id in self._clients:
                            self._clients[client_id].last_pong = datetime.now(timezone.utc)
                            self._clients[client_id].is_alive = True
                    except Exception:
                        disconnected_clients.append(client_id)
                
                # Clean up disconnected clients
                for client_id in disconnected_clients:
                    await self._disconnect_client(client_id, room_id)
    
    async def _disconnect_client(self, client_id: str, room_id: str) -> None:
        """Internal method to disconnect a client (must be called with lock held)."""
        if room_id in self._connections and client_id in self._connections[room_id]:
            websocket = self._connections[room_id][client_id]
            try:
                await websocket.close()
            except Exception:
                pass  # Already closed or error
            
            del self._connections[room_id][client_id]
            
            # Clean up room if empty
            if not self._connections[room_id]:
                del self._connections[room_id]
            
            # Remove client info
            if client_id in self._clients:
                del self._clients[client_id]
    
    async def _close_all_connections(self) -> None:
        """Close all connections (must be called with lock held)."""
        for room_id in list(self._connections.keys()):
            for client_id in list(self._connections[room_id].keys()):
                await self._disconnect_client(client_id, room_id)