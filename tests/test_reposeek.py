"""
Tests for RepoSeek — models, github_client, scoring, and router.

Covers serialization roundtrips, API error handling, scoring logic,
and HTTP endpoint integration. All external dependencies are mocked
(no real GitHub API calls).

Uses pytest, AAA pattern, monkeypatch for all externals.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.github.search_client import (
    deduplicate_results as _deduplicate_results,
    get_token as _get_token,
    parse_item as _parse_item,
)
from core.reposeek.github_client import (
    _build_queries,
    search_github,
)
from core.reposeek.models import RepoResult, SeekQuery
from core.reposeek.router import router as reposeek_router
from core.reposeek.scoring import score_results
from core.reposeek.storage import RepoSeekStore
from core.result import Err, Ok


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _make_result(
    title: str = "owner/repo",
    url: str = "https://github.com/owner/repo",
    description: str = "A test repo",
    language: str | None = "Python",
    stars: int = 100,
    score: float = 0.0,
    reasons: list[str] | None = None,
) -> RepoResult:
    """Create a RepoResult with sensible defaults."""
    return RepoResult(
        title=title,
        url=url,
        description=description,
        language=language,
        stars=stars,
        similarity_score=score,
        match_reasons=reasons or [],
    )


def _make_raw_item(
    full_name: str = "owner/repo",
    html_url: str = "https://github.com/owner/repo",
    description: str = "A test repo",
    language: str | None = "Python",
    stargazers_count: int = 100,
) -> dict:
    """Create a raw GitHub API item dict."""
    return {
        "full_name": full_name,
        "html_url": html_url,
        "description": description,
        "language": language,
        "stargazers_count": stargazers_count,
    }


def _mock_response(status_code: int = 200, json_data: dict | None = None):
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {"items": []}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
#  1. Models
# ===========================================================================


class TestModels:
    def test_repo_result_to_dict(self):
        """RepoResult.to_dict serializes all fields including defaults."""
        # Arrange
        r = _make_result(reasons=["language:python", "stars:500"])

        # Act
        d = r.to_dict()

        # Assert
        assert d["title"] == "owner/repo"
        assert d["url"] == "https://github.com/owner/repo"
        assert d["description"] == "A test repo"
        assert d["language"] == "Python"
        assert d["stars"] == 100
        assert d["similarity_score"] == 0.0
        assert d["match_reasons"] == ["language:python", "stars:500"]

    def test_repo_result_from_dict_roundtrip(self):
        """to_dict → from_dict roundtrip preserves all data."""
        # Arrange
        original = _make_result(reasons=["language:python"])
        d = original.to_dict()

        # Act
        restored = RepoResult.from_dict(d)

        # Assert
        assert restored == original

    def test_repo_result_from_dict_ignores_unknown_keys(self):
        """from_dict silently ignores keys not in the dataclass."""
        # Arrange
        d = _make_result().to_dict()
        d["unknown_field"] = "surprise"
        d["extra_nested"] = {"a": 1}

        # Act
        restored = RepoResult.from_dict(d)

        # Assert
        assert restored.title == "owner/repo"
        # No unknown fields leaked into the dataclass
        assert not hasattr(restored, "unknown_field")

    def test_repo_result_from_dict_none_language(self):
        """from_dict handles language=None correctly."""
        # Arrange
        d = _make_result(language=None).to_dict()

        # Act
        restored = RepoResult.from_dict(d)

        # Assert
        assert restored.language is None

    def test_seek_query_to_dict(self):
        """SeekQuery.to_dict serializes with optional fields."""
        # Arrange
        q = SeekQuery(query="machine learning", language="Python", topics=["ml", "ai"])

        # Act
        d = q.to_dict()

        # Assert
        assert d["query"] == "machine learning"
        assert d["language"] == "Python"
        assert d["topics"] == ["ml", "ai"]

    def test_seek_query_defaults(self):
        """SeekQuery defaults: language=None, topics=[]."""
        # Arrange / Act
        q = SeekQuery(query="test")

        # Assert
        assert q.language is None
        assert q.topics == []
        assert q.to_dict()["language"] is None
        assert q.to_dict()["topics"] == []


# ---------------------------------------------------------------------------
#  2. GitHub Client
# ===========================================================================


class TestGitHubClient:
    def test_build_queries_basic(self):
        """Query-only SeekQuery produces a single search string."""
        # Arrange
        q = SeekQuery(query="web framework")

        # Act
        queries = _build_queries(q)

        # Assert
        assert queries == ["web framework"]

    def test_build_queries_with_language(self):
        """Language filter adds a language-qualified text query."""
        # Arrange
        q = SeekQuery(query="web framework", language="Python")

        # Act
        queries = _build_queries(q)

        # Assert
        assert len(queries) == 2
        assert "web framework language:Python" in queries

    def test_build_queries_with_topics(self):
        """Topics add a third query dimension."""
        # Arrange
        q = SeekQuery(query="web framework", language="Python", topics=["ml", "api"])

        # Act
        queries = _build_queries(q)

        # Assert
        assert len(queries) == 3
        assert "topic:ml topic:api" in queries

    def test_parse_item(self):
        """_parse_item converts raw GitHub API item to RepoResult."""
        # Arrange
        raw = _make_raw_item(stargazers_count=5000, description="Fast web framework")

        # Act
        result = _parse_item(raw)

        # Assert
        assert isinstance(result, RepoResult)
        assert result.title == "owner/repo"
        assert result.stars == 5000
        assert result.description == "Fast web framework"
        assert result.similarity_score == 0.0
        assert result.match_reasons == []

    def test_parse_item_missing_fields(self):
        """_parse_item handles missing fields gracefully."""
        # Arrange
        raw = {}

        # Act
        result = _parse_item(raw)

        # Assert
        assert result.title == ""
        assert result.url == ""
        assert result.description == ""
        assert result.language is None
        assert result.stars == 0

    def test_deduplicate_results(self):
        """_deduplicate_results keeps first occurrence of each URL."""
        # Arrange
        items = [
            _make_raw_item(html_url="https://github.com/a/repo"),
            _make_raw_item(html_url="https://github.com/b/repo"),
            _make_raw_item(html_url="https://github.com/a/repo"),  # duplicate
        ]

        # Act
        unique = _deduplicate_results(items)

        # Assert
        assert len(unique) == 2
        urls = [i["html_url"] for i in unique]
        assert "https://github.com/a/repo" in urls
        assert "https://github.com/b/repo" in urls

    def test_deduplicate_results_empty_url(self):
        """Items with empty html_url are skipped by dedup."""
        # Arrange
        items = [
            {"html_url": "https://github.com/a/repo", "full_name": "a/repo"},
            {"html_url": "", "full_name": "empty/url"},
        ]

        # Act
        unique = _deduplicate_results(items)

        # Assert
        assert len(unique) == 1
        assert unique[0]["html_url"] == "https://github.com/a/repo"

    def test_get_token_from_env(self, monkeypatch):
        """_get_token reads GITHUB_TOKEN from environment."""
        # Arrange
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")

        # Act
        token = _get_token()

        # Assert
        assert token == "ghp_test123"

    def test_get_token_gh_token_fallback(self, monkeypatch):
        """_get_token falls back to GH_TOKEN when GITHUB_TOKEN not set."""
        # Arrange
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "gh_fallback")

        # Act
        token = _get_token()

        # Assert
        assert token == "gh_fallback"

    def test_get_token_missing(self, monkeypatch):
        """_get_token returns None when neither token is set."""
        # Arrange
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        # Act
        token = _get_token()

        # Assert
        assert token is None

    @pytest.mark.asyncio
    async def test_search_github_success(self, monkeypatch):
        """search_github mocks 3 parallel API calls, verifies deduplication."""
        # Arrange
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        item1 = _make_raw_item(full_name="a/repo", html_url="https://github.com/a/repo")
        item2 = _make_raw_item(full_name="b/repo", html_url="https://github.com/b/repo")
        # item3 duplicates item1
        item3 = _make_raw_item(full_name="a/repo", html_url="https://github.com/a/repo")
        # item4 is unique
        item4 = _make_raw_item(full_name="c/repo", html_url="https://github.com/c/repo")

        call_count = 0

        async def mock_get(url, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_response(200, {"items": [item1, item2]})
            elif call_count == 2:
                return _mock_response(200, {"items": [item3]})
            else:
                return _mock_response(200, {"items": [item4]})

        with patch("core.reposeek.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            query = SeekQuery(query="web framework", language="Python", topics=["api"])
            result = await search_github(query)

        # Assert
        assert isinstance(result, Ok)
        titles = [r.title for r in result.value]
        assert "a/repo" in titles
        assert "b/repo" in titles
        assert "c/repo" in titles
        # Deduplication: only 3 unique, not 4
        assert len(result.value) == 3

    @pytest.mark.asyncio
    async def test_search_github_rate_limit(self, monkeypatch):
        """search_github returns Err with RATE_LIMITED when API returns 403."""
        # Arrange
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        async def mock_get(url, params=None):
            return _mock_response(403)

        with patch("core.reposeek.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            query = SeekQuery(query="test")
            result = await search_github(query)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_search_github_not_found(self, monkeypatch):
        """search_github returns Err with NOT_FOUND when API returns 404."""
        # Arrange
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        async def mock_get(url, params=None):
            return _mock_response(404)

        with patch("core.reposeek.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            query = SeekQuery(query="test")
            result = await search_github(query)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_search_github_network_error(self, monkeypatch):
        """search_github returns Err with NETWORK_ERROR on connection failure."""
        # Arrange
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        import httpx

        async def mock_get(url, params=None):
            raise httpx.ConnectError("Connection refused")

        with patch("core.reposeek.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            query = SeekQuery(query="test")
            result = await search_github(query)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "NETWORK_ERROR"

    @pytest.mark.asyncio
    async def test_search_github_no_token(self, monkeypatch):
        """search_github warns when GITHUB_TOKEN is not set."""
        # Arrange
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        async def mock_get(url, params=None):
            return _mock_response(200, {"items": []})

        with patch("core.reposeek.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            query = SeekQuery(query="test")

            with pytest.warns(UserWarning, match="No GITHUB_TOKEN"):
                result = await search_github(query)

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []

    @pytest.mark.asyncio
    async def test_search_github_deduplication(self, monkeypatch):
        """Same repo appearing in multiple queries is returned only once."""
        # Arrange
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        shared_item = _make_raw_item(
            full_name="shared/repo",
            html_url="https://github.com/shared/repo",
        )

        async def mock_get(url, params=None):
            return _mock_response(200, {"items": [shared_item]})

        with patch("core.reposeek.github_client.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            query = SeekQuery(query="shared repo", topics=["shared"])
            result = await search_github(query)

        # Assert — 2 queries both return same repo, dedup keeps 1
        assert isinstance(result, Ok)
        assert len(result.value) == 1
        assert result.value[0].title == "shared/repo"


# ---------------------------------------------------------------------------
#  3. Scoring
# ===========================================================================


class TestScoring:
    def test_score_results_language_match(self):
        """Python repo vs Python profile → high language score contribution."""
        # Arrange
        results = [_make_result(language="Python", stars=1000)]
        profile = {"tech_stack": ["Python"], "description": "", "patterns": []}

        # Act
        scored = score_results(results, profile)

        # Assert
        assert len(scored) == 1
        r = scored[0]
        assert r.similarity_score > 0
        assert "language:python" in r.match_reasons

    def test_score_results_no_match(self):
        """Different language → low score, no language reason."""
        # Arrange
        results = [_make_result(language="Ruby", stars=50)]
        profile = {"tech_stack": ["Python"], "description": "", "patterns": []}

        # Act
        scored = score_results(results, profile)

        # Assert
        assert len(scored) == 1
        assert scored[0].similarity_score < 0.3
        assert not any("language:" in r for r in scored[0].match_reasons)

    def test_score_results_sorted(self):
        """Results are sorted by similarity_score descending."""
        # Arrange
        results = [
            _make_result(title="low/star", language="Ruby", stars=10),
            _make_result(title="high/star", language="Python", stars=5000),
            _make_result(title="mid/star", language="Python", stars=100),
        ]
        profile = {"tech_stack": ["Python"], "description": "", "patterns": []}

        # Act
        scored = score_results(results, profile)

        # Assert
        scores = [r.similarity_score for r in scored]
        assert scores == sorted(scores, reverse=True)

    def test_score_results_match_reasons_language(self):
        """Language match produces a 'language:<tech>' reason."""
        # Arrange
        results = [_make_result(language="Go", stars=0)]
        profile = {"tech_stack": ["Go"], "description": "", "patterns": []}

        # Act
        scored = score_results(results, profile)

        # Assert
        assert "language:go" in scored[0].match_reasons

    def test_score_results_match_reasons_stars(self):
        """High-star repo produces a 'stars:<n>' reason."""
        # Arrange
        results = [_make_result(language=None, stars=5000)]
        profile = {"tech_stack": [], "description": "", "patterns": []}

        # Act
        scored = score_results(results, profile)

        # Assert
        assert "stars:5000" in scored[0].match_reasons

    def test_score_results_match_reasons_description(self):
        """Overlapping description words produce a 'description_match' reason."""
        # Arrange
        results = [_make_result(description="fast web framework", language=None, stars=0)]
        profile = {"tech_stack": [], "description": "a fast web framework for APIs", "patterns": []}

        # Act
        scored = score_results(results, profile)

        # Assert
        assert "description_match" in scored[0].match_reasons

    def test_score_results_empty(self):
        """Empty results returns empty list."""
        # Arrange / Act
        scored = score_results([], {"tech_stack": [], "description": "", "patterns": []})

        # Assert
        assert scored == []

    def test_score_results_stars(self):
        """High-star repo scores higher than low-star repo (same language)."""
        # Arrange
        high_star = _make_result(title="popular/repo", language="Python", stars=10000)
        low_star = _make_result(title="niche/repo", language="Python", stars=5)
        profile = {"tech_stack": ["Python"], "description": "", "patterns": []}

        # Act
        scored = score_results([low_star, high_star], profile)

        # Assert
        # Both have same language match, but high_star has better star score
        high_scored = next(r for r in scored if r.title == "popular/repo")
        low_scored = next(r for r in scored if r.title == "niche/repo")
        assert high_scored.similarity_score > low_scored.similarity_score

    def test_score_results_none_language(self):
        """Repo with None language gets zero language score."""
        # Arrange
        results = [_make_result(language=None, stars=100)]
        profile = {"tech_stack": ["Python"], "description": "", "patterns": []}

        # Act
        scored = score_results(results, profile)

        # Assert
        assert scored[0].similarity_score >= 0
        assert not any("language:" in r for r in scored[0].match_reasons)


# ---------------------------------------------------------------------------
#  4. Router Integration
# ===========================================================================


def _make_test_app() -> FastAPI:
    """Create a test FastAPI app with the reposeek router."""
    app = FastAPI()
    app.include_router(reposeek_router)
    return app


@pytest.fixture(autouse=True)
def _isolated_reposeek_store(tmp_path):
    """Every router endpoint now persists via RepoSeekStore(). Without this,
    every test in this module would write real batch files into the actual
    repo's memory/reposeek/ directory (confirmed live: a bare test run
    left memory/reposeek/my-project.json sitting in the working tree).
    Scope storage to tmp_path for every test in this file instead."""
    with patch("core.reposeek.router.RepoSeekStore", return_value=RepoSeekStore(str(tmp_path))):
        yield


class TestRouter:
    def test_scan_success(self):
        """GET /api/reposeek/scan with valid project → 200 + correct shape."""
        # Arrange
        profile = {"tech_stack": ["Python"], "description": "A Python project", "patterns": []}
        search_results = [
            _make_result(title="a/repo", language="Python", stars=500),
            _make_result(title="b/repo", language="Python", stars=200),
        ]

        with (
            patch(
                "core.reposeek.router._load_profile_from_memory",
                return_value=profile,
            ),
            patch(
                "core.reposeek.router.search_github",
                new_callable=AsyncMock,
                return_value=Ok(value=search_results),
            ),
            patch(
                "core.reposeek.router.score_results",
                return_value=search_results,
            ),
        ):
            client = TestClient(_make_test_app())
            response = client.get("/api/reposeek/scan", params={"project": "my-project"})

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "repos" in data
        assert len(data["repos"]) == 2
        assert data["repos"][0]["title"] == "a/repo"
        assert data["repos"][0]["language"] == "Python"

    def test_scan_project_not_found(self):
        """Project not in memory and README fetch fails → 404."""
        # Arrange
        with (
            patch(
                "core.reposeek.router._load_profile_from_memory",
                return_value=None,
            ),
            patch(
                "core.reposeek.router._fetch_readme_as_profile",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            client = TestClient(_make_test_app())
            response = client.get(
                "/api/reposeek/scan", params={"project": "nonexistent"}
            )

        # Assert
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_scan_empty_name(self):
        """Empty project name → 422."""
        # Arrange
        client = TestClient(_make_test_app())

        # Act — send empty project name
        response = client.get("/api/reposeek/scan", params={"project": "  "})

        # Assert
        assert response.status_code == 422
        assert "empty" in response.json()["detail"].lower()

    def test_scan_rate_limit(self):
        """search_github returns RATE_LIMITED → 503 + Retry-After header."""
        # Arrange
        profile = {"tech_stack": ["Python"], "description": "test", "patterns": []}

        with (
            patch(
                "core.reposeek.router._load_profile_from_memory",
                return_value=profile,
            ),
            patch(
                "core.reposeek.router.search_github",
                new_callable=AsyncMock,
                return_value=Err(error="rate limited", code="RATE_LIMITED"),
            ),
        ):
            client = TestClient(_make_test_app())
            response = client.get(
                "/api/reposeek/scan", params={"project": "my-project"}
            )

        # Assert
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "60"

    def test_scan_general_error(self):
        """search_github returns generic Err → 500."""
        # Arrange
        profile = {"tech_stack": [], "description": "test", "patterns": []}

        with (
            patch(
                "core.reposeek.router._load_profile_from_memory",
                return_value=profile,
            ),
            patch(
                "core.reposeek.router.search_github",
                new_callable=AsyncMock,
                return_value=Err(error="internal failure", code="UNKNOWN"),
            ),
        ):
            client = TestClient(_make_test_app())
            response = client.get(
                "/api/reposeek/scan", params={"project": "my-project"}
            )

        # Assert
        assert response.status_code == 500

    def test_scan_persists_a_depth_0_batch(self):
        """A successful scan is now persisted, not just returned."""
        profile = {"tech_stack": ["Python"], "description": "A Python project", "patterns": []}
        results = [_make_result(title="a/repo"), _make_result(title="b/repo", url="https://github.com/b/repo")]

        with (
            patch("core.reposeek.router._load_profile_from_memory", return_value=profile),
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=results)),
            patch("core.reposeek.router.score_results", return_value=results),
        ):
            client = TestClient(_make_test_app())
            response = client.get("/api/reposeek/scan", params={"project": "my-project"})

        data = response.json()
        assert "batch_id" in data
        assert data["depth"] == 0

        batches_resp = client.get("/api/reposeek/my-project/batches")
        assert batches_resp.json()["count"] == 1
        assert batches_resp.json()["batches"][0]["id"] == data["batch_id"]

    def test_scan_caps_results_at_20(self):
        profile = {"tech_stack": ["Python"], "description": "test", "patterns": []}
        results = [_make_result(title=f"owner/repo{i}", url=f"https://github.com/owner/repo{i}") for i in range(30)]

        with (
            patch("core.reposeek.router._load_profile_from_memory", return_value=profile),
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=results)),
            patch("core.reposeek.router.score_results", return_value=results),
        ):
            client = TestClient(_make_test_app())
            response = client.get("/api/reposeek/scan", params={"project": "my-project"})

        assert len(response.json()["repos"]) == 20

    def test_scan_filters_excluded_repos(self):
        profile = {"tech_stack": ["Python"], "description": "test", "patterns": []}
        results = [
            _make_result(title="a/repo", url="https://github.com/a/repo"),
            _make_result(title="b/repo", url="https://github.com/b/repo"),
        ]

        with (
            patch("core.reposeek.router._load_profile_from_memory", return_value=profile),
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=results)),
            patch("core.reposeek.router.score_results", return_value=results),
        ):
            client = TestClient(_make_test_app())
            client.post("/api/reposeek/my-project/exclude", json={"url": "https://github.com/a/repo", "title": "a/repo"})
            response = client.get("/api/reposeek/scan", params={"project": "my-project"})

        titles = [r["title"] for r in response.json()["repos"]]
        assert "a/repo" not in titles
        assert "b/repo" in titles


class TestExcludeEndpoints:
    def test_add_list_remove_roundtrip(self):
        client = TestClient(_make_test_app())

        add = client.post("/api/reposeek/my-project/exclude", json={"url": "https://github.com/a/repo", "title": "a/repo"})
        assert add.status_code == 200
        assert add.json()["excluded_count"] == 1

        listed = client.get("/api/reposeek/my-project/exclude")
        assert listed.json()["count"] == 1
        assert listed.json()["excluded"][0]["url"] == "https://github.com/a/repo"

        removed = client.delete("/api/reposeek/my-project/exclude", params={"url": "https://github.com/a/repo"})
        assert removed.status_code == 200
        assert removed.json()["excluded_count"] == 0

    def test_remove_nonexistent_is_404(self):
        client = TestClient(_make_test_app())
        response = client.delete("/api/reposeek/my-project/exclude", params={"url": "https://github.com/nope/repo"})
        assert response.status_code == 404

    def test_add_same_url_twice_does_not_duplicate(self):
        client = TestClient(_make_test_app())
        client.post("/api/reposeek/my-project/exclude", json={"url": "https://github.com/a/repo", "title": "a/repo"})
        second = client.post("/api/reposeek/my-project/exclude", json={"url": "https://github.com/a/repo", "title": "a/repo"})
        assert second.json()["excluded_count"] == 1


class TestItemScanEndpoint:
    """POST /{project}/batches/{batch_id}/items/scan -- the "Scan Item"
    action. Profiles a single result as its own project and searches from
    that, bounded by depth (2 rounds) and width (3 per batch)."""

    def _seed_batch(self, client, project="my-project", depth=0, item_scans_used=0, results=None):
        """Create a batch directly via the initial scan endpoint (depth 0),
        or synthesize a deeper one by calling the storage layer the same
        way the router does, to set up depth/width-cap test scenarios
        without needing 1-2 real item-scan round trips first."""
        results = results if results is not None else [_make_result(title="target/repo", url="https://github.com/target/repo")]
        with (
            patch("core.reposeek.router._load_profile_from_memory", return_value={"tech_stack": [], "description": "x", "patterns": []}),
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=results)),
            patch("core.reposeek.router.score_results", return_value=results),
        ):
            resp = client.get("/api/reposeek/scan", params={"project": project})
        batch_id = resp.json()["batch_id"]

        if depth > 0 or item_scans_used > 0:
            # Reach into the same isolated store the router is using
            # (patched to tmp_path by the module's autouse fixture) to set
            # up depth/width states that would otherwise take several real
            # round trips to construct.
            from core.reposeek.router import RepoSeekStore as PatchedStore
            store = PatchedStore()
            data = store._load(project)
            for b in data["batches"]:
                if b["id"] == batch_id:
                    b["depth"] = depth
                    b["item_scans_used"] = item_scans_used
            store._save(project, data)

        return batch_id

    def test_successful_item_scan_creates_child_batch(self):
        client = TestClient(_make_test_app())
        batch_id = self._seed_batch(client)

        child_results = [_make_result(title="child/repo", url="https://github.com/child/repo")]
        with (
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=child_results)),
            patch("core.reposeek.router.score_results", return_value=child_results),
        ):
            response = client.post(
                f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
                json={"item_url": "https://github.com/target/repo"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["depth"] == 1
        assert data["parent_batch_id"] == batch_id
        assert data["source_item"]["title"] == "target/repo"
        assert [r["title"] for r in data["repos"]] == ["child/repo"]

    def test_item_scan_increments_parent_item_scans_used(self):
        client = TestClient(_make_test_app())
        batch_id = self._seed_batch(client)

        with (
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=[])),
            patch("core.reposeek.router.score_results", return_value=[]),
        ):
            client.post(f"/api/reposeek/my-project/batches/{batch_id}/items/scan", json={"item_url": "https://github.com/target/repo"})

        batches = client.get("/api/reposeek/my-project/batches").json()["batches"]
        parent = next(b for b in batches if b["id"] == batch_id)
        assert parent["item_scans_used"] == 1

    def test_depth_cap_blocks_a_third_round(self):
        """depth=2 is the terminal round -- no further item scans allowed."""
        client = TestClient(_make_test_app())
        batch_id = self._seed_batch(client, depth=2)

        response = client.post(
            f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
            json={"item_url": "https://github.com/target/repo"},
        )
        assert response.status_code == 409
        assert "depth" in response.json()["detail"].lower()

    def test_width_cap_blocks_a_fourth_item_scan(self):
        client = TestClient(_make_test_app())
        batch_id = self._seed_batch(client, item_scans_used=3)

        response = client.post(
            f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
            json={"item_url": "https://github.com/target/repo"},
        )
        assert response.status_code == 409
        assert "item scans" in response.json()["detail"].lower()

    def test_unknown_batch_is_404(self):
        client = TestClient(_make_test_app())
        response = client.post(
            "/api/reposeek/my-project/batches/doesnotexist/items/scan",
            json={"item_url": "https://github.com/target/repo"},
        )
        assert response.status_code == 404

    def test_unknown_item_url_is_404(self):
        client = TestClient(_make_test_app())
        batch_id = self._seed_batch(client)
        response = client.post(
            f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
            json={"item_url": "https://github.com/not-in-this-batch/repo"},
        )
        assert response.status_code == 404

    def test_dedup_against_exclude_list(self):
        client = TestClient(_make_test_app())
        batch_id = self._seed_batch(client)
        client.post("/api/reposeek/my-project/exclude", json={"url": "https://github.com/excluded/repo", "title": "excluded/repo"})

        child_results = [
            _make_result(title="excluded/repo", url="https://github.com/excluded/repo"),
            _make_result(title="ok/repo", url="https://github.com/ok/repo"),
        ]
        with (
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=child_results)),
            patch("core.reposeek.router.score_results", return_value=child_results),
        ):
            response = client.post(
                f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
                json={"item_url": "https://github.com/target/repo"},
            )

        titles = [r["title"] for r in response.json()["repos"]]
        assert "excluded/repo" not in titles
        assert "ok/repo" in titles

    def test_dedup_against_parent_batch(self):
        """A result that's already in the parent batch must not reappear
        in the child batch derived from it -- checked against the batch
        immediately before, not just the global exclude list."""
        client = TestClient(_make_test_app())
        parent_results = [
            _make_result(title="target/repo", url="https://github.com/target/repo"),
            _make_result(title="sibling/repo", url="https://github.com/sibling/repo"),
        ]
        batch_id = self._seed_batch(client, results=parent_results)

        # search returns the sibling (already in parent) plus something new
        child_results = [
            _make_result(title="sibling/repo", url="https://github.com/sibling/repo"),
            _make_result(title="new/repo", url="https://github.com/new/repo"),
        ]
        with (
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=child_results)),
            patch("core.reposeek.router.score_results", return_value=child_results),
        ):
            response = client.post(
                f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
                json={"item_url": "https://github.com/target/repo"},
            )

        titles = [r["title"] for r in response.json()["repos"]]
        assert "sibling/repo" not in titles
        assert "new/repo" in titles

    def test_empty_results_after_filtering_is_a_valid_terminal_batch_not_an_error(self):
        """If everything found is already excluded or in the parent batch,
        that's a normal stopping point -- the batch is still created, just
        empty, and the endpoint returns 200."""
        client = TestClient(_make_test_app())
        parent_results = [_make_result(title="target/repo", url="https://github.com/target/repo")]
        batch_id = self._seed_batch(client, results=parent_results)

        # Everything the search turns up is already in the parent batch.
        with (
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=parent_results)),
            patch("core.reposeek.router.score_results", return_value=parent_results),
        ):
            response = client.post(
                f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
                json={"item_url": "https://github.com/target/repo"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["repos"] == []
        # Still a real, persisted batch -- lineage stays visible.
        batches = client.get("/api/reposeek/my-project/batches").json()["batches"]
        assert any(b["id"] == data["batch_id"] for b in batches)

    def test_rate_limit_does_not_burn_an_item_scan_slot(self):
        """A transient API failure shouldn't count against the 3-per-batch
        cap -- only a completed search (even an empty one) should."""
        client = TestClient(_make_test_app())
        batch_id = self._seed_batch(client)

        with patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Err(error="rate limited", code="RATE_LIMITED")):
            response = client.post(
                f"/api/reposeek/my-project/batches/{batch_id}/items/scan",
                json={"item_url": "https://github.com/target/repo"},
            )
        assert response.status_code == 503

        batches = client.get("/api/reposeek/my-project/batches").json()["batches"]
        parent = next(b for b in batches if b["id"] == batch_id)
        assert parent["item_scans_used"] == 0


class TestBatchesAndExportEndpoints:
    def test_get_batch_detail(self):
        client = TestClient(_make_test_app())
        with (
            patch("core.reposeek.router._load_profile_from_memory", return_value={"tech_stack": [], "description": "x", "patterns": []}),
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=[_make_result()])),
            patch("core.reposeek.router.score_results", return_value=[_make_result()]),
        ):
            scan_resp = client.get("/api/reposeek/scan", params={"project": "my-project"})
        batch_id = scan_resp.json()["batch_id"]

        detail = client.get(f"/api/reposeek/my-project/batches/{batch_id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == batch_id
        assert len(detail.json()["results"]) == 1

    def test_get_batch_detail_unknown_is_404(self):
        client = TestClient(_make_test_app())
        response = client.get("/api/reposeek/my-project/batches/doesnotexist")
        assert response.status_code == 404

    def test_export_json_default(self):
        client = TestClient(_make_test_app())
        with (
            patch("core.reposeek.router._load_profile_from_memory", return_value={"tech_stack": [], "description": "x", "patterns": []}),
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=[_make_result()])),
            patch("core.reposeek.router.score_results", return_value=[_make_result()]),
        ):
            client.get("/api/reposeek/scan", params={"project": "my-project"})

        response = client.get("/api/reposeek/my-project/export")
        assert response.status_code == 200
        data = response.json()
        assert data["project"] == "my-project"
        assert len(data["batches"]) == 1

    def test_export_markdown(self):
        client = TestClient(_make_test_app())
        with (
            patch("core.reposeek.router._load_profile_from_memory", return_value={"tech_stack": [], "description": "x", "patterns": []}),
            patch("core.reposeek.router.search_github", new_callable=AsyncMock, return_value=Ok(value=[_make_result(title="a/repo")])),
            patch("core.reposeek.router.score_results", return_value=[_make_result(title="a/repo")]),
        ):
            client.get("/api/reposeek/scan", params={"project": "my-project"})

        response = client.get("/api/reposeek/my-project/export", params={"format": "markdown"})
        assert response.status_code == 200
        assert "a/repo" in response.text
        assert "Initial scan" in response.text

    def test_export_empty_project_returns_empty_batches(self):
        client = TestClient(_make_test_app())
        response = client.get("/api/reposeek/never-scanned/export")
        assert response.status_code == 200
        assert response.json()["batches"] == []
