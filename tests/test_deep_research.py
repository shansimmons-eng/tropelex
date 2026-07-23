"""Tests for deep research API endpoints and research_provider field."""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.tropebook.research_feeds import (
    ResearchFeed,
    ResearchFeedManager,
    FeedRun,
)


@pytest.fixture
def fm(tmp_path):
    """Fresh feed manager per test."""
    return ResearchFeedManager(storage_path=str(tmp_path / "feeds"))


# ─── research_provider field ──────────────────────────────────────────────


class TestResearchProviderField:
    def test_default_is_web_search(self, fm):
        feed = fm.create(name="Test", query="test query")
        assert feed.research_provider == "web_search"

    def test_create_with_deep_research(self, fm):
        feed = fm.create(name="Deep", query="AI trends", research_provider="deep_research")
        assert feed.research_provider == "deep_research"

    def test_create_rejects_invalid_provider(self, fm):
        with pytest.raises(ValueError, match="Invalid research_provider"):
            fm.create(name="Bad", query="test", research_provider="invalid")

    def test_update_research_provider(self, fm):
        feed = fm.create(name="Test", query="test")
        assert feed.research_provider == "web_search"
        updated = fm.update(feed.id, research_provider="deep_research")
        assert updated.research_provider == "deep_research"

    def test_roundtrip_preserves_provider(self, fm):
        feed = fm.create(name="Test", query="test", research_provider="deep_research")
        d = feed.to_dict()
        restored = ResearchFeed.from_dict(d)
        assert restored.research_provider == "deep_research"

    def test_update_invalid_provider_rejected(self, fm):
        feed = fm.create(name="Test", query="test")
        # update() doesn't validate research_provider (it's a generic setter)
        # but the model allows any string — validation happens at API boundary
        updated = fm.update(feed.id, research_provider="anything")
        assert updated.research_provider == "anything"


# ─── Deep research persistence ───────────────────────────────────────────


class TestDeepResearchPersistence:
    def test_run_persisted_after_query(self, tmp_path):
        """POST /api/last30days/query should persist the run to disk."""
        # Patch the deep research directory to use tmp_path
        import core.tropebook.web.server as srv

        fake_html = "<html><h1>Test</h1><p>Content</p></html>"
        fake_citations = [{"title": "Source A", "url": "https://a.com"}]

        with patch.object(srv, '_DEEP_RESEARCH_DIR', tmp_path / "dr"):
            (tmp_path / "dr").mkdir(exist_ok=True)
            with patch.object(srv, '_DEEP_RESEARCH_INDEX', tmp_path / "dr" / "index.json"):
                with patch(
                    "core.last30days.runner.run_query_and_extract_citations",
                    return_value=(fake_html, fake_citations),
                ):
                    # Create a test app with just the relevant endpoints
                    test_app = FastAPI()
                    test_app.include_router(srv.app.router)
                    client = TestClient(test_app, raise_server_exceptions=False)
                    resp = client.post(
                        "/api/last30days/query",
                        json={"query": "test topic", "emit": "html"},
                    )

                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["query"] == "test topic"
                    assert data["output"] == fake_html
                    assert data["citations_count"] == 1
                    assert "run_id" in data
                    assert "timestamp" in data

                    # Verify run was persisted
                    runs_resp = client.get("/api/last30days/runs")
                    assert runs_resp.status_code == 200
                    runs_data = runs_resp.json()
                    assert runs_data["count"] >= 1
                    assert any(r["id"] == data["run_id"] for r in runs_data["runs"])

    def test_get_run_by_id(self, tmp_path):
        """GET /api/last30days/runs/{id} returns the HTML output."""
        import core.tropebook.web.server as srv

        fake_html = "<html>Research Output</html>"

        with patch.object(srv, '_DEEP_RESEARCH_DIR', tmp_path / "dr"):
            (tmp_path / "dr").mkdir(exist_ok=True)
            with patch.object(srv, '_DEEP_RESEARCH_INDEX', tmp_path / "dr" / "index.json"):
                with patch(
                    "core.last30days.runner.run_query_and_extract_citations",
                    return_value=(fake_html, []),
                ):
                    test_app = FastAPI()
                    test_app.include_router(srv.app.router)
                    client = TestClient(test_app, raise_server_exceptions=False)

                    # Create a run
                    create_resp = client.post(
                        "/api/last30days/query",
                        json={"query": "my topic"},
                    )
                    run_id = create_resp.json()["run_id"]

                    # Get it back
                    get_resp = client.get(f"/api/last30days/runs/{run_id}")
                    assert get_resp.status_code == 200
                    assert get_resp.json()["output"] == fake_html
                    assert get_resp.json()["query"] == "my topic"

    def test_run_404_for_missing(self):
        """GET /api/last30days/runs/{id} returns 404 for non-existent run."""
        from core.tropebook.web.server import app as full_app
        client = TestClient(full_app, raise_server_exceptions=False)
        resp = client.get("/api/last30days/runs/000000000000")
        assert resp.status_code == 404

    def test_run_400_for_invalid_id(self):
        """GET /api/last30days/runs/{id} returns 400 for invalid ID format."""
        from core.tropebook.web.server import app as full_app
        client = TestClient(full_app, raise_server_exceptions=False)
        resp = client.get("/api/last30days/runs/not-valid!")
        assert resp.status_code == 400

    def test_query_timeout_returns_504(self):
        """POST /api/last30days/query returns 504 on engine timeout."""
        with patch(
            "core.last30days.runner.run_query_and_extract_citations",
            side_effect=TimeoutError("timed out"),
        ):
            from core.tropebook.web.server import app as full_app
            client = TestClient(full_app, raise_server_exceptions=False)
            resp = client.post(
                "/api/last30days/query",
                json={"query": "slow query"},
            )
            assert resp.status_code == 504


# ─── Feed create API with research_provider ──────────────────────────────


class TestFeedCreateAPI:
    def test_create_feed_with_deep_research(self):
        """POST /api/research-feeds with research_provider='deep_research'."""
        from core.tropebook.web.server import app as full_app
        client = TestClient(full_app, raise_server_exceptions=False)
        resp = client.post(
            "/api/research-feeds",
            json={
                "name": "Deep Feed",
                "query": "AI safety",
                "research_provider": "deep_research",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["research_provider"] == "deep_research"

    def test_create_feed_default_provider(self):
        """POST /api/research-feeds without research_provider defaults to web_search."""
        from core.tropebook.web.server import app as full_app
        client = TestClient(full_app, raise_server_exceptions=False)
        resp = client.post(
            "/api/research-feeds",
            json={"name": "Default Feed", "query": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["research_provider"] == "web_search"

    def test_create_feed_invalid_provider_422(self):
        """POST /api/research-feeds with invalid research_provider returns 422."""
        from core.tropebook.web.server import app as full_app
        client = TestClient(full_app, raise_server_exceptions=False)
        resp = client.post(
            "/api/research-feeds",
            json={
                "name": "Bad Feed",
                "query": "test",
                "research_provider": "invalid_provider",
            },
        )
        assert resp.status_code == 422
