"""
Tests for Trending — storage, github_client (query building + search), and router.

Follows tests/test_reposeek.py's conventions: pytest, AAA pattern, all
external HTTP mocked, autouse fixture isolating storage to tmp_path so no
test writes into the real memory/trending/ directory.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.reposeek.models import RepoResult
from core.result import Err, Ok
from core.trending.github_client import build_query, search_trending, window_cutoff
from core.trending.router import router as trending_router
from core.trending.storage import TrendingStore, snapshot_key


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_result(
    title: str = "owner/repo",
    url: str = "https://github.com/owner/repo",
    description: str = "A test repo",
    language: str | None = "Python",
    stars: int = 100,
) -> RepoResult:
    return RepoResult(
        title=title, url=url, description=description,
        language=language, stars=stars, similarity_score=0.0, match_reasons=[],
    )


def _make_raw_item(
    full_name: str = "owner/repo",
    html_url: str = "https://github.com/owner/repo",
    description: str = "A test repo",
    language: str | None = "Python",
    stargazers_count: int = 100,
) -> dict:
    return {
        "full_name": full_name,
        "html_url": html_url,
        "description": description,
        "language": language,
        "stargazers_count": stargazers_count,
    }


def _mock_response(status_code: int = 200, json_data: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {"items": []}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


def _make_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(trending_router)
    return app


@pytest.fixture(autouse=True)
def _isolated_trending_store(tmp_path):
    """Every router endpoint persists via TrendingStore(). Scope it to
    tmp_path for every test in this file so nothing writes into the real
    repo's memory/trending/ directory (same rationale/pattern as
    tests/test_reposeek.py's _isolated_reposeek_store)."""
    with patch("core.trending.router.TrendingStore", return_value=TrendingStore(str(tmp_path))):
        yield


# ---------------------------------------------------------------------------
#  1. Storage
# ===========================================================================


class TestStorage:
    def test_snapshot_key_normalizes_case_and_sorts_topics(self):
        """Key building lowercases language/topics and sorts topics so
        filter order doesn't fragment history under different keys."""
        k1 = snapshot_key("Python", ["AI", "cli"], "week")
        k2 = snapshot_key("python", ["cli", "ai"], "week")
        assert k1 == k2

    def test_snapshot_key_handles_none_language_and_empty_topics(self):
        key = snapshot_key(None, [], "month")
        assert key == "::::month"

    def test_add_and_last_snapshot_roundtrip(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        key = snapshot_key("python", [], "week")

        assert store.last_snapshot(key) is None

        snap = {"id": "abc123", "created_at": "2026-08-19T00:00:00+00:00", "repos": []}
        store.add_snapshot(key, snap)

        assert store.last_snapshot(key) == snap

    def test_last_snapshot_returns_most_recent(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        key = snapshot_key(None, [], "week")

        store.add_snapshot(key, {"id": "1", "created_at": "t1", "repos": []})
        store.add_snapshot(key, {"id": "2", "created_at": "t2", "repos": []})

        assert store.last_snapshot(key)["id"] == "2"

    def test_snapshot_history_capped_and_trims_oldest(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        key = snapshot_key(None, [], "week")

        for i in range(35):
            store.add_snapshot(key, {"id": str(i), "created_at": f"t{i}", "repos": []})

        history = store.list_snapshots(key)
        assert len(history) == 30
        # Oldest (0-4) trimmed, most recent (5-34) kept, order preserved
        assert history[0]["id"] == "5"
        assert history[-1]["id"] == "34"

    def test_snapshot_keys_are_independent(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        key_a = snapshot_key("python", [], "week")
        key_b = snapshot_key("rust", [], "week")

        store.add_snapshot(key_a, {"id": "a", "created_at": "t", "repos": []})

        assert store.last_snapshot(key_a) is not None
        assert store.last_snapshot(key_b) is None

    def test_exclude_add_dedupes_by_url(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        store.exclude_add("https://github.com/x/y", "x/y")
        store.exclude_add("https://github.com/x/y", "x/y")

        assert len(store.exclude_list()) == 1

    def test_exclude_remove_returns_false_when_not_present(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        assert store.exclude_remove("https://github.com/nope/nope") is False

    def test_excluded_urls_returns_url_set(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        store.exclude_add("https://github.com/a/b", "a/b")
        store.exclude_add("https://github.com/c/d", "c/d")

        assert store.excluded_urls() == {
            "https://github.com/a/b",
            "https://github.com/c/d",
        }

    def test_missing_file_returns_graceful_defaults(self, tmp_path):
        store = TrendingStore(str(tmp_path))
        assert store.exclude_list() == []
        assert store.list_snapshots(snapshot_key(None, [], "week")) == []


# ---------------------------------------------------------------------------
#  2. GitHub client — query building + search
# ===========================================================================


class TestQueryBuilding:
    def test_window_cutoff_today_is_one_day_back(self):
        from datetime import datetime, timedelta, timezone

        cutoff = window_cutoff("today")
        expected = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        assert cutoff == expected

    def test_window_cutoff_unknown_falls_back_to_week(self):
        assert window_cutoff("bogus") == window_cutoff("week")

    def test_build_query_includes_pushed_qualifier(self):
        q = build_query(None, [], "week")
        assert q.startswith("pushed:>")

    def test_build_query_includes_language(self):
        q = build_query("Python", [], "week")
        assert "language:Python" in q

    def test_build_query_includes_topics_capped_at_four(self):
        q = build_query(None, ["a", "b", "c", "d", "e"], "week")
        assert "topic:a" in q
        assert "topic:d" in q
        assert "topic:e" not in q

    def test_build_query_omits_language_when_none(self):
        q = build_query(None, [], "week")
        assert "language:" not in q


class TestSearchTrending:
    @pytest.mark.asyncio
    async def test_search_trending_success(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        item = _make_raw_item(full_name="a/repo", stargazers_count=500)

        async def mock_get(url, params=None):
            assert params.get("sort") == "stars"
            assert params.get("order") == "desc"
            return _mock_response(200, {"items": [item]})

        with patch("core.trending.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await search_trending(None, [], "week")

        assert isinstance(result, Ok)
        assert result.value[0].title == "a/repo"

    @pytest.mark.asyncio
    async def test_search_trending_rate_limit(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        async def mock_get(url, params=None):
            return _mock_response(403)

        with patch("core.trending.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await search_trending(None, [], "week")

        assert isinstance(result, Err)
        assert result.code == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_search_trending_respects_limit(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        items = [
            _make_raw_item(full_name=f"o/{i}", html_url=f"https://github.com/o/{i}")
            for i in range(5)
        ]

        async def mock_get(url, params=None):
            return _mock_response(200, {"items": items})

        with patch("core.trending.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await search_trending(None, [], "week", limit=3)

        assert isinstance(result, Ok)
        assert len(result.value) == 3


# ---------------------------------------------------------------------------
#  3. Router
# ===========================================================================


class TestScanEndpoint:
    def test_first_scan_has_no_delta_or_previous_snapshot(self):
        results = [_make_result(title="a/repo", stars=500)]

        with patch(
            "core.trending.router.search_trending",
            new_callable=AsyncMock,
            return_value=Ok(value=results),
        ):
            client = TestClient(_make_test_app())
            response = client.get("/api/trending/scan", params={"window": "week"})

        assert response.status_code == 200
        data = response.json()
        assert data["previous_snapshot_at"] is None
        assert data["repos"][0]["delta_stars"] is None
        assert data["repos"][0]["first_seen"] is None

    def test_repeat_scan_computes_delta_for_existing_repo(self):
        first = [_make_result(title="a/repo", url="https://github.com/a/repo", stars=500)]
        second = [_make_result(title="a/repo", url="https://github.com/a/repo", stars=650)]

        with patch(
            "core.trending.router.search_trending",
            new_callable=AsyncMock,
            side_effect=[Ok(value=first), Ok(value=second)],
        ):
            client = TestClient(_make_test_app())
            client.get("/api/trending/scan", params={"window": "week", "language": "Python"})
            response = client.get(
                "/api/trending/scan", params={"window": "week", "language": "Python"}
            )

        data = response.json()
        assert data["previous_snapshot_at"] is not None
        repo = data["repos"][0]
        assert repo["first_seen"] is False
        assert repo["delta_stars"] == 150

    def test_repeat_scan_flags_new_entrant(self):
        first = [_make_result(title="a/repo", url="https://github.com/a/repo", stars=500)]
        second = [
            _make_result(title="a/repo", url="https://github.com/a/repo", stars=500),
            _make_result(title="b/repo", url="https://github.com/b/repo", stars=50),
        ]

        with patch(
            "core.trending.router.search_trending",
            new_callable=AsyncMock,
            side_effect=[Ok(value=first), Ok(value=second)],
        ):
            client = TestClient(_make_test_app())
            client.get("/api/trending/scan", params={"window": "week"})
            response = client.get("/api/trending/scan", params={"window": "week"})

        repos_by_url = {r["url"]: r for r in response.json()["repos"]}
        assert repos_by_url["https://github.com/b/repo"]["first_seen"] is True
        assert repos_by_url["https://github.com/b/repo"]["delta_stars"] is None
        assert repos_by_url["https://github.com/a/repo"]["first_seen"] is False
        assert repos_by_url["https://github.com/a/repo"]["delta_stars"] == 0

    def test_scan_filters_excluded_repos(self):
        results = [
            _make_result(title="a/repo", url="https://github.com/a/repo"),
            _make_result(title="b/repo", url="https://github.com/b/repo"),
        ]

        with (
            patch(
                "core.trending.router.search_trending",
                new_callable=AsyncMock,
                return_value=Ok(value=results),
            ),
            patch("core.trending.router.TrendingStore") as MockStore,
        ):
            instance = MockStore.return_value
            instance.excluded_urls.return_value = {"https://github.com/a/repo"}
            instance.last_snapshot.return_value = None
            instance.new_snapshot_id.return_value = "snap1"

            client = TestClient(_make_test_app())
            response = client.get("/api/trending/scan", params={"window": "week"})

        titles = [r["title"] for r in response.json()["repos"]]
        assert "a/repo" not in titles
        assert "b/repo" in titles

    def test_scan_rate_limit_returns_503(self):
        with patch(
            "core.trending.router.search_trending",
            new_callable=AsyncMock,
            return_value=Err(error="rate limited", code="RATE_LIMITED"),
        ):
            client = TestClient(_make_test_app())
            response = client.get("/api/trending/scan", params={"window": "week"})

        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "60"

    def test_scan_invalid_window_returns_422(self):
        client = TestClient(_make_test_app())
        response = client.get("/api/trending/scan", params={"window": "yesterday"})
        assert response.status_code == 422


class TestRelatedEndpoint:
    def test_related_returns_scored_results(self):
        results = [_make_result(title="c/repo", url="https://github.com/c/repo")]

        with (
            patch(
                "core.trending.router.search_github",
                new_callable=AsyncMock,
                return_value=Ok(value=results),
            ),
            patch("core.trending.router.score_results", return_value=results),
        ):
            client = TestClient(_make_test_app())
            response = client.post(
                "/api/trending/related",
                json={
                    "title": "a/repo",
                    "url": "https://github.com/a/repo",
                    "description": "a test repo",
                    "language": "Python",
                },
            )

        assert response.status_code == 200
        assert response.json()["repos"][0]["title"] == "c/repo"

    def test_related_excludes_the_source_repo_itself(self):
        source = _make_result(title="a/repo", url="https://github.com/a/repo")
        other = _make_result(title="c/repo", url="https://github.com/c/repo")

        with (
            patch(
                "core.trending.router.search_github",
                new_callable=AsyncMock,
                return_value=Ok(value=[source, other]),
            ),
            patch("core.trending.router.score_results", return_value=[source, other]),
        ):
            client = TestClient(_make_test_app())
            response = client.post(
                "/api/trending/related",
                json={"title": "a/repo", "url": "https://github.com/a/repo"},
            )

        titles = [r["title"] for r in response.json()["repos"]]
        assert "a/repo" not in titles
        assert "c/repo" in titles

    def test_related_nothing_persisted(self, tmp_path):
        """POST /related must not create a snapshot -- it's a one-shot
        lookup, not a batch."""
        results = [_make_result(title="c/repo")]

        with (
            patch(
                "core.trending.router.search_github",
                new_callable=AsyncMock,
                return_value=Ok(value=results),
            ),
            patch("core.trending.router.score_results", return_value=results),
        ):
            client = TestClient(_make_test_app())
            client.post("/api/trending/related", json={"title": "a/repo"})

        store = TrendingStore(str(tmp_path))
        assert store.list_snapshots(snapshot_key(None, [], "week")) == []


class TestExcludeEndpoints:
    def test_add_then_list_exclude(self):
        client = TestClient(_make_test_app())
        client.post(
            "/api/trending/exclude",
            json={"url": "https://github.com/x/y", "title": "x/y"},
        )
        response = client.get("/api/trending/exclude")

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_remove_missing_exclude_returns_404(self):
        client = TestClient(_make_test_app())
        response = client.delete(
            "/api/trending/exclude", params={"url": "https://github.com/nope/nope"}
        )
        assert response.status_code == 404

    def test_add_then_remove_exclude(self):
        client = TestClient(_make_test_app())
        client.post(
            "/api/trending/exclude",
            json={"url": "https://github.com/x/y", "title": "x/y"},
        )
        response = client.delete(
            "/api/trending/exclude", params={"url": "https://github.com/x/y"}
        )
        assert response.status_code == 200
        assert response.json()["excluded_count"] == 0


class TestHistoryEndpoint:
    def test_history_returns_dates_and_counts_only(self):
        results = [_make_result(title="a/repo")]

        with patch(
            "core.trending.router.search_trending",
            new_callable=AsyncMock,
            return_value=Ok(value=results),
        ):
            client = TestClient(_make_test_app())
            client.get("/api/trending/scan", params={"window": "week"})
            response = client.get("/api/trending/history", params={"window": "week"})

        data = response.json()
        assert data["count"] == 1
        entry = data["history"][0]
        assert set(entry.keys()) == {"id", "created_at", "result_count"}
        assert entry["result_count"] == 1

    def test_history_empty_when_never_scanned(self):
        client = TestClient(_make_test_app())
        response = client.get("/api/trending/history", params={"window": "month"})
        assert response.json() == {
            "window": "month", "language": None, "topics": [], "history": [], "count": 0,
        }
