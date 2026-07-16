"""Tests for core.collaboration.connection_manager.ConnectionManager"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from core.collaboration.connection_manager import ConnectionManager, ClientInfo


class MockWebSocket:
    """Mock WebSocket for testing."""
    
    def __init__(self):
        self.messages = []
        self.ping_called = False
        self.close_called = False
        self.send_should_fail = False
        self.ping_should_fail = False
    
    async def send_text(self, message: str) -> None:
        if self.send_should_fail:
            raise Exception("Send failed")
        self.messages.append(message)
    
    async def ping(self) -> None:
        if self.ping_should_fail:
            raise Exception("Ping failed")
        self.ping_called = True
    
    async def close(self) -> None:
        self.close_called = True


@pytest.fixture
def manager():
    """Create a ConnectionManager with fast heartbeat for testing."""
    return ConnectionManager(heartbeat_interval=0.1)


@pytest.mark.asyncio
class TestConnectionManager:
    async def test_connect_and_get_room_clients(self, manager):
        """Test connecting a client and retrieving room clients."""
        ws = MockWebSocket()
        await manager.connect("client1", "room1", ws)
        
        clients = manager.get_room_clients("room1")
        assert "client1" in clients
        assert len(clients) == 1
    
    async def test_multiple_clients_same_room(self, manager):
        """Test multiple clients connecting to the same room."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client2", "room1", ws2)
        
        clients = manager.get_room_clients("room1")
        assert len(clients) == 2
        assert "client1" in clients
        assert "client2" in clients
    
    async def test_disconnect_client(self, manager):
        """Test disconnecting a client."""
        ws = MockWebSocket()
        await manager.connect("client1", "room1", ws)
        await manager.disconnect("client1", "room1")
        
        clients = manager.get_room_clients("room1")
        assert len(clients) == 0
        assert ws.close_called
    
    async def test_disconnect_cleans_room_when_empty(self, manager):
        """Test that empty rooms are cleaned up after disconnect."""
        ws = MockWebSocket()
        await manager.connect("client1", "room1", ws)
        await manager.disconnect("client1", "room1")
        
        # Room should not exist
        assert manager.get_room_clients("room1") == set()
    
    async def test_broadcast_to_room(self, manager):
        """Test broadcasting a message to all clients in a room."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client2", "room1", ws2)
        
        await manager.broadcast("room1", "Hello everyone!")
        
        assert "Hello everyone!" in ws1.messages
        assert "Hello everyone!" in ws2.messages
    
    async def test_broadcast_does_not_affect_other_rooms(self, manager):
        """Test that broadcast only affects the target room."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client2", "room2", ws2)
        
        await manager.broadcast("room1", "Room1 message")
        
        assert "Room1 message" in ws1.messages
        assert len(ws2.messages) == 0
    
    async def test_broadcast_handles_failed_send(self, manager):
        """Test that broadcast handles send failures gracefully."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        ws2.send_should_fail = True
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client2", "room1", ws2)
        
        await manager.broadcast("room1", "Test message")
        
        # Good connection should still receive message
        assert "Test message" in ws1.messages
        # Failed connection should be disconnected
        assert manager.get_room_clients("room1") == {"client1"}
    
    async def test_reconnect_replaces_existing_connection(self, manager):
        """Test that reconnecting replaces the existing connection."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client1", "room1", ws2)  # Reconnect
        
        clients = manager.get_room_clients("room1")
        assert len(clients) == 1
        
        # Broadcast should go to new connection
        await manager.broadcast("room1", "Hello")
        assert "Hello" in ws2.messages
        assert len(ws1.messages) == 0
    
    async def test_heartbeat_detects_dead_connections(self, manager):
        """Test that heartbeat detects and removes dead connections."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        ws2.ping_should_fail = True  # Simulate dead connection
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client2", "room1", ws2)
        
        await manager.start()
        
        # Wait for heartbeat cycle
        await asyncio.sleep(0.2)
        
        # Dead connection should be removed (check BEFORE stop)
        clients = manager.get_room_clients("room1")
        assert "client1" in clients
        assert "client2" not in clients
        
        await manager.stop()
    
    async def test_start_and_stop_heartbeat(self, manager):
        """Test starting and stopping the heartbeat task."""
        await manager.start()
        assert manager._heartbeat_task is not None
        
        await manager.stop()
        assert manager._heartbeat_task is None
    
    async def test_stop_closes_all_connections(self, manager):
        """Test that stop closes all connections."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client2", "room2", ws2)
        
        await manager.stop()
        
        assert ws1.close_called
        assert ws2.close_called
        assert manager.get_room_clients("room1") == set()
        assert manager.get_room_clients("room2") == set()
    
    async def test_client_info_tracking(self, manager):
        """Test that client info is tracked correctly."""
        ws = MockWebSocket()
        await manager.connect("client1", "room1", ws)
        
        # Check client info exists
        assert "client1" in manager._clients
        client_info = manager._clients["client1"]
        assert client_info.client_id == "client1"
        assert client_info.room_id == "room1"
        assert client_info.is_alive
    
    async def test_multiple_rooms(self, manager):
        """Test clients in multiple rooms."""
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        ws3 = MockWebSocket()
        
        await manager.connect("client1", "room1", ws1)
        await manager.connect("client2", "room1", ws2)
        await manager.connect("client3", "room2", ws3)
        
        assert len(manager.get_room_clients("room1")) == 2
        assert len(manager.get_room_clients("room2")) == 1
        
        await manager.broadcast("room1", "Room1 only")
        assert "Room1 only" in ws1.messages
        assert "Room1 only" in ws2.messages
        assert len(ws3.messages) == 0


class TestClientInfo:
    def test_client_info_creation(self):
        """Test ClientInfo dataclass creation."""
        now = datetime.now(timezone.utc)
        info = ClientInfo(
            client_id="test",
            room_id="room",
            connected_at=now
        )
        
        assert info.client_id == "test"
        assert info.room_id == "room"
        assert info.connected_at == now
        assert info.is_alive
    
    def test_client_info_default_values(self):
        """Test ClientInfo default values."""
        info = ClientInfo(
            client_id="test",
            room_id="room",
            connected_at=datetime.now(timezone.utc)
        )
        
        assert info.is_alive
        assert isinstance(info.last_pong, datetime)