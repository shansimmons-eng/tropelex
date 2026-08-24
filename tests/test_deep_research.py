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


# ─── #87: query-fingerprint caching + quick/thorough mode ────────────────


class TestQueryFingerprintCaching:
    @pytest.fixture
    def isolated(self, tmp_path):
        """Isolate the deep-research index/dir and mock the engine, tracking
        call count so cache-hit tests can assert the expensive subprocess
        was NOT invoked a second time. Yields (client, mock)."""
        import core.tropebook.web.server as srv

        dr_dir = tmp_path / "dr"
        dr_dir.mkdir(exist_ok=True)
        with patch.object(srv, "_DEEP_RESEARCH_DIR", dr_dir), \
             patch.object(srv, "_DEEP_RESEARCH_INDEX", dr_dir / "index.json"), \
             patch(
                 "core.last30days.runner.run_query_and_extract_citations",
                 return_value=("<html>result</html>", [{"title": "A", "url": "https://a.com"}]),
             ) as mock_run:
            test_app = FastAPI()
            test_app.include_router(srv.app.router)
            client = TestClient(test_app, raise_server_exceptions=False)
            yield client, mock_run

    def test_first_call_is_not_cached(self, isolated):
        client, mock_run = isolated
        resp = client.post("/api/last30days/query", json={"query": "cache test"})
        assert resp.json()["cached"] is False
        assert mock_run.call_count == 1

    def test_identical_repeat_query_hits_cache(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "cache test"})
        resp = client.post("/api/last30days/query", json={"query": "cache test"})
        body = resp.json()
        assert body["cached"] is True
        assert body["output"] == "<html>result</html>"
        assert mock_run.call_count == 1  # engine not called a second time

    def test_cache_hit_reports_citations_count_but_not_the_list(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "cache test"})
        resp = client.post("/api/last30days/query", json={"query": "cache test"})
        body = resp.json()
        assert body["citations"] is None
        assert body["citations_count"] == 1

    def test_case_and_whitespace_insensitive_fingerprint(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "  Cache   Test  "})
        resp = client.post("/api/last30days/query", json={"query": "cache test"})
        assert resp.json()["cached"] is True
        assert mock_run.call_count == 1

    def test_different_emit_mode_not_cached_together(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "cache test", "emit": "html"})
        resp = client.post("/api/last30days/query", json={"query": "cache test", "emit": "md"})
        assert resp.json()["cached"] is False
        assert mock_run.call_count == 2

    def test_different_query_not_cached_together(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "cache test"})
        resp = client.post("/api/last30days/query", json={"query": "a completely different query"})
        assert resp.json()["cached"] is False
        assert mock_run.call_count == 2

    def test_force_refresh_bypasses_cache(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "cache test"})
        resp = client.post("/api/last30days/query", json={"query": "cache test", "force_refresh": True})
        assert resp.json()["cached"] is False
        assert mock_run.call_count == 2

    def test_expired_cache_entry_not_reused(self, isolated, monkeypatch):
        import core.tropebook.web.server as srv

        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "cache test"})
        monkeypatch.setattr(srv, "_RESEARCH_CACHE_MAX_AGE_HOURS", -1.0)  # already "expired"
        resp = client.post("/api/last30days/query", json={"query": "cache test"})
        assert resp.json()["cached"] is False
        assert mock_run.call_count == 2


class TestModeBudgetPreset:
    @pytest.fixture
    def isolated(self, tmp_path):
        import core.tropebook.web.server as srv

        dr_dir = tmp_path / "dr"
        dr_dir.mkdir(exist_ok=True)
        with patch.object(srv, "_DEEP_RESEARCH_DIR", dr_dir), \
             patch.object(srv, "_DEEP_RESEARCH_INDEX", dr_dir / "index.json"), \
             patch(
                 "core.last30days.runner.run_query_and_extract_citations",
                 return_value=("<html></html>", []),
             ) as mock_run:
            test_app = FastAPI()
            test_app.include_router(srv.app.router)
            client = TestClient(test_app, raise_server_exceptions=False)
            yield client, mock_run

    def test_default_mode_is_quick_with_120s_timeout(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "mode test"})
        assert mock_run.call_args.kwargs["timeout"] == 120

    def test_thorough_mode_uses_400s_timeout(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "mode test", "mode": "thorough"})
        assert mock_run.call_args.kwargs["timeout"] == 400

    def test_explicit_timeout_wins_over_mode(self, isolated):
        client, mock_run = isolated
        client.post("/api/last30days/query", json={"query": "mode test", "mode": "thorough", "timeout": 60})
        assert mock_run.call_args.kwargs["timeout"] == 60

    def test_invalid_mode_rejected_with_422(self, isolated):
        client, mock_run = isolated
        resp = client.post("/api/last30days/query", json={"query": "mode test", "mode": "extreme"})
        assert resp.status_code == 422


# ─── Feed create API with research_provider ──────────────────────────────


class TestFeedCreateAPI:
    @pytest.fixture(autouse=True)
    def _isolated_feed_storage(self, tmp_path, monkeypatch):
        """Point the app's feed manager at an isolated temp directory.

        Without this, these tests hit the real app singleton
        (``_get_feed_manager`` caches a module-level ``ResearchFeedManager``
        pointed at ``BASE_DIR / "memory"``, the same storage the live
        dashboard reads) and permanently write "Deep Feed"/"Default Feed"
        entries into production feed storage on every test run.
        """
        from core.tropebook.web import server as server_module

        monkeypatch.setattr(
            server_module,
            "_feed_manager",
            ResearchFeedManager(storage_path=str(tmp_path / "feeds")),
        )

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
