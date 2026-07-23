"""Tests for the _load_memory fix across all routers.

Verifies that project-scoped endpoints return data for existing projects
and 404 for missing ones, using MemoryManager instead of broken BASE_DIR paths.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from core.memory.manager import MemoryManager


@pytest.fixture
def project_memory(tmp_path):
    """Create a test project with some data."""
    mm = MemoryManager(str(tmp_path))
    mm.add_decision("test-proj", "Use FastAPI", "Async support needed")
    mm.add_decision("test-proj", "Use Postgres", "JSON support")
    return mm


def _make_client(router):
    """Create a TestClient with just the given router."""
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app, raise_server_exceptions=False)


class TestGraphRouter:
    def test_returns_nodes_for_existing_project(self, project_memory):
        """GET /{project}/graph returns nodes and edges."""
        with patch("core.graph_router._mm", project_memory):
            from core.graph_router import graph_router
            client = _make_client(graph_router)
            resp = client.get("/api/memory/test-proj/graph")
            assert resp.status_code == 200
            data = resp.json()
            assert "nodes" in data
            assert "edges" in data
            assert len(data["nodes"]) == 2  # 2 decisions

    def test_404_for_missing_project(self, project_memory):
        """GET /{project}/graph returns 404 for non-existent project."""
        with patch("core.graph_router._mm", project_memory):
            from core.graph_router import graph_router
            client = _make_client(graph_router)
            resp = client.get("/api/memory/nonexistent/graph")
            assert resp.status_code == 404


class TestHealthRouter:
    def test_returns_health_for_existing_project(self, project_memory):
        """GET /{project}/health returns health metrics."""
        with patch("core.health.router._mm", project_memory):
            from core.health.router import health_router
            client = _make_client(health_router)
            resp = client.get("/api/memory/test-proj/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "quality_score" in data or "confidence_summary" in data

    def test_404_for_missing_project(self, project_memory):
        with patch("core.health.router._mm", project_memory):
            from core.health.router import health_router
            client = _make_client(health_router)
            resp = client.get("/api/memory/nonexistent/health")
            assert resp.status_code == 404


class TestGhostRouter:
    def test_returns_ghost_decisions(self, project_memory):
        """GET /{project}/ghost-decisions returns results."""
        with patch("core.ghost.router._mm", project_memory):
            from core.ghost.router import ghost_router
            client = _make_client(ghost_router)
            resp = client.get("/api/memory/test-proj/ghost-decisions")
            assert resp.status_code == 200

    def test_404_for_missing_project(self, project_memory):
        with patch("core.ghost.router._mm", project_memory):
            from core.ghost.router import ghost_router
            client = _make_client(ghost_router)
            resp = client.get("/api/memory/nonexistent/ghost-decisions")
            assert resp.status_code == 404


class TestContradictionsRouter:
    def test_returns_contradictions(self, project_memory):
        """GET /{project}/contradictions returns results."""
        with patch("core.contradictions.router._mm", project_memory):
            from core.contradictions.router import contradiction_router
            client = _make_client(contradiction_router)
            resp = client.get("/api/memory/test-proj/contradictions")
            assert resp.status_code == 200

    def test_404_for_missing_project(self, project_memory):
        with patch("core.contradictions.router._mm", project_memory):
            from core.contradictions.router import contradiction_router
            client = _make_client(contradiction_router)
            resp = client.get("/api/memory/nonexistent/contradictions")
            assert resp.status_code == 404


class TestExplainRouter:
    def test_404_for_missing_project(self, project_memory):
        with patch("core.explain.router._mm", project_memory):
            from core.explain.router import explain_router
            client = _make_client(explain_router)
            resp = client.post(
                "/api/memory/nonexistent/explain",
                json={"question": "why?"},
            )
            assert resp.status_code == 404


class TestImpactRouter:
    def test_returns_impact(self, project_memory):
        """GET /{project}/impact returns impact analysis."""
        with patch("core.impact.router._mm", project_memory):
            from core.impact.router import impact_router
            client = _make_client(impact_router)
            resp = client.get("/api/memory/test-proj/impact")
            assert resp.status_code == 200

    def test_404_for_missing_project(self, project_memory):
        with patch("core.impact.router._mm", project_memory):
            from core.impact.router import impact_router
            client = _make_client(impact_router)
            resp = client.get("/api/memory/nonexistent/impact")
            assert resp.status_code == 404


class TestAnalyticsRouter:
    def test_returns_analytics(self, project_memory):
        """GET /{project}/analytics returns analytics."""
        with patch("core.analytics_router._mm", project_memory):
            from core.analytics_router import analytics_router
            client = _make_client(analytics_router)
            resp = client.get("/api/memory/test-proj/analytics")
            assert resp.status_code == 200

    def test_404_for_missing_project(self, project_memory):
        with patch("core.analytics_router._mm", project_memory):
            from core.analytics_router import analytics_router
            client = _make_client(analytics_router)
            resp = client.get("/api/memory/nonexistent/analytics")
            assert resp.status_code == 404


class TestSearchRouter:
    def test_search_returns_results(self, project_memory):
        """GET /{project}/search returns results."""
        with patch("core.search_router._mm", project_memory):
            from core.search_router import search_router
            client = _make_client(search_router)
            resp = client.get("/api/memory/test-proj/search?q=FastAPI")
            assert resp.status_code == 200

    def test_404_for_missing_project(self, project_memory):
        with patch("core.search_router._mm", project_memory):
            from core.search_router import search_router
            client = _make_client(search_router)
            resp = client.get("/api/memory/nonexistent/search?q=test")
            assert resp.status_code == 404


class TestHandoffRouter:
    def test_404_for_missing_project(self, project_memory):
        with patch("core.handoff.router._mm", project_memory):
            from core.handoff.router import handoff_router
            client = _make_client(handoff_router)
            resp = client.post(
                "/api/memory/nonexistent/handoff",
                json={"role": "TestEngineer", "token_budget": 4000},
            )
            assert resp.status_code == 404


class TestSlackRouter:
    def test_capture_works_for_existing_project(self, project_memory):
        """POST /{project}/slack/capture works for existing project."""
        with patch("core.slack.router._mm", project_memory):
            from core.slack.router import slack_router
            client = _make_client(slack_router)
            resp = client.post(
                "/api/memory/test-proj/slack/capture",
                json={
                    "decision_text": "Use Redis for caching",
                    "context": "From slack discussion",
                    "channel": "#backend",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["decision_text"] == "Use Redis for caching"

    def test_capture_404_for_missing_project(self, project_memory):
        """POST /{project}/slack/capture returns 404 for missing project."""
        with patch("core.slack.router._mm", project_memory):
            from core.slack.router import slack_router
            client = _make_client(slack_router)
            resp = client.post(
                "/api/memory/nonexistent/slack/capture",
                json={"decision_text": "test"},
            )
            assert resp.status_code == 404

    def test_extract_404_for_missing_project(self, project_memory):
        """POST /{project}/slack/extract returns 404 for missing project."""
        with patch("core.slack.router._mm", project_memory):
            from core.slack.router import slack_router
            client = _make_client(slack_router)
            resp = client.post(
                "/api/memory/nonexistent/slack/extract",
                json={"messages": ["we decided x"]},
            )
            assert resp.status_code == 404


class TestMarketRouter:
    def test_leaderboard_returns_data(self, project_memory):
        """GET /{project}/market/leaderboard returns data."""
        with patch("core.market.router._mm", project_memory):
            from core.market.router import market_router
            client = _make_client(market_router)
            resp = client.get("/api/memory/test-proj/market/leaderboard")
            assert resp.status_code == 200

    def test_404_for_missing_project(self, project_memory):
        with patch("core.market.router._mm", project_memory):
            from core.market.router import market_router
            client = _make_client(market_router)
            resp = client.get("/api/memory/nonexistent/market/leaderboard")
            assert resp.status_code == 404


class TestFrictionRouter:
    def test_scan_works_for_existing_project(self, project_memory):
        """POST /{project}/friction/scan works for existing project."""
        with patch("core.friction.router._mm", project_memory):
            from core.friction.router import friction_router
            client = _make_client(friction_router)
            resp = client.post(
                "/api/memory/test-proj/friction/scan",
                json={"transcript": "user: try again\nassistant: ok\nuser: no that's wrong"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "friction_score" in data
            assert "signals" in data

    def test_scan_404_for_missing_project(self, project_memory):
        with patch("core.friction.router._mm", project_memory):
            from core.friction.router import friction_router
            client = _make_client(friction_router)
            resp = client.post(
                "/api/memory/nonexistent/friction/scan",
                json={"transcript": "test"},
            )
            assert resp.status_code == 404


class TestCostRouter:
    def test_404_for_missing_project(self, project_memory):
        with patch("core.cost.router._mm", project_memory):
            from core.cost.router import cost_router
            client = _make_client(cost_router)
            resp = client.get("/api/memory/nonexistent/cost/summary")
            assert resp.status_code == 404
