"""Integration tests for core.market.router — specifically the clear-data
endpoint (DELETE /{project}/market/clear), which had no test coverage since
it didn't exist until now (Decision Market previously had no way to wipe
accumulated bet data short of hand-editing the project's memory JSON)."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.market.router as router_mod
from core.market.router import market_router
from core.memory.manager import MemoryManager


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """router_mod._mm is a shared module-level singleton — core.tropebook.web
    .server mounts the same market_router instance, so leaving it pointed at
    a tmp dir after this fixture tears down would silently break any test
    that hits the real app's market endpoints afterward. Always restore it.
    """
    app = FastAPI()
    app.include_router(market_router)

    original_mm = router_mod._mm
    router_mod._mm = MemoryManager(base_path=str(tmp_path))
    mem = router_mod._mm.get_project_memory("demo")
    router_mod._mm.save_project_memory("demo", mem)

    yield TestClient(app, raise_server_exceptions=False)

    router_mod._mm = original_mm


class TestClearMarket:
    def test_clear_empty_market_is_a_no_op(self, client: TestClient) -> None:
        resp = client.delete("/api/memory/demo/market/clear")
        assert resp.status_code == 200
        assert resp.json() == {"cleared": True, "bets_removed": 0}

    def test_clear_removes_all_bets(self, client: TestClient) -> None:
        for i in range(3):
            r = client.post("/api/memory/demo/market/bet", json={
                "decision_id": f"d{i}", "agent_name": "claude", "confidence": 0.7, "category": "test",
            })
            assert r.status_code == 200

        resp = client.delete("/api/memory/demo/market/clear")
        assert resp.status_code == 200
        assert resp.json() == {"cleared": True, "bets_removed": 3}

        leaderboard = client.get("/api/memory/demo/market/leaderboard").json()
        assert leaderboard["count"] == 0

    def test_clear_unknown_project_404s(self, client: TestClient) -> None:
        resp = client.delete("/api/memory/nonexistent/market/clear")
        assert resp.status_code == 404

    def test_clear_is_idempotent(self, client: TestClient) -> None:
        client.post("/api/memory/demo/market/bet", json={
            "decision_id": "d1", "agent_name": "claude", "confidence": 0.5, "category": "test",
        })
        first = client.delete("/api/memory/demo/market/clear").json()
        second = client.delete("/api/memory/demo/market/clear").json()
        assert first == {"cleared": True, "bets_removed": 1}
        assert second == {"cleared": True, "bets_removed": 0}
