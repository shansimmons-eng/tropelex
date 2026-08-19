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

from core.reposeek.github_client import (
    _build_queries,
    _deduplicate_results,
    _get_token,
    _parse_item,
    search_github,
)
from core.reposeek.models import RepoResult, SeekQuery
from core.reposeek.router import router as reposeek_router
from core.reposeek.scoring import score_results
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
