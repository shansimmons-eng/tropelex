"""Tests for core.research_pipeline.auto_research's provider waterfall.

auto_research previously only tried Brave then fell straight to DuckDuckGo
(free, hard rate limits) — Exa and Serper keys were accepted everywhere else
in the app (Settings, last30days) but never consulted here. These tests
pin down the new Brave -> Exa -> Serper -> DuckDuckGo order and that each
tier is skipped when unconfigured or empty, not just when missing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.research_pipeline import auto_research


class _FakeTropebook:
    def __init__(self):
        self.added = []

    def add(self, **kwargs):
        self.added.append(kwargs)


def _fake_response(status_code: int, json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _fake_async_client(get_response=None, post_response=None) -> MagicMock:
    """Build a mock that behaves like `async with httpx.AsyncClient() as client`."""
    client = MagicMock()
    if get_response is not None:
        client.get = AsyncMock(return_value=get_response)
    if post_response is not None:
        client.post = AsyncMock(return_value=post_response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory


@pytest.fixture(autouse=True)
def _clear_search_env(monkeypatch):
    for key in ("BRAVE_SEARCH_API_KEY", "EXA_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(key, raising=False)


class TestProviderWaterfall:
    @pytest.mark.asyncio
    async def test_uses_brave_when_configured(self, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
        resp = _fake_response(200, {"web": {"results": [
            {"title": "A", "url": "https://a.com", "description": "desc"},
        ]}})
        with patch("httpx.AsyncClient", _fake_async_client(get_response=resp)):
            result = await auto_research("query", _FakeTropebook(), max_results=5)
        assert result["provider"] == "brave"
        assert result["added"] == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_exa_when_no_brave_key(self, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "exa-key")
        resp = _fake_response(200, {"results": [
            {"title": "A", "url": "https://a.com", "text": "content"},
        ]})
        with patch("httpx.AsyncClient", _fake_async_client(post_response=resp)):
            result = await auto_research("query", _FakeTropebook(), max_results=5)
        assert result["provider"] == "exa"
        assert result["added"] == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_exa_when_brave_returns_zero_results(self, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
        monkeypatch.setenv("EXA_API_KEY", "exa-key")

        brave_client = MagicMock()
        brave_client.get = AsyncMock(return_value=_fake_response(200, {"web": {"results": []}}))
        exa_client = MagicMock()
        exa_client.post = AsyncMock(return_value=_fake_response(200, {"results": [
            {"title": "A", "url": "https://a.com", "text": "content"},
        ]}))

        # First AsyncClient() call is Brave's (uses .get), second is Exa's (uses .post).
        clients = [brave_client, exa_client]

        def _next_ctx(*a, **k):
            client = clients.pop(0)
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=client)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("httpx.AsyncClient", side_effect=_next_ctx):
            result = await auto_research("query", _FakeTropebook(), max_results=5)
        assert result["provider"] == "exa"

    @pytest.mark.asyncio
    async def test_falls_back_to_serper_when_no_brave_or_exa_key(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "serper-key")
        resp = _fake_response(200, {"organic": [
            {"title": "A", "link": "https://a.com", "snippet": "desc"},
        ]})
        with patch("httpx.AsyncClient", _fake_async_client(post_response=resp)):
            result = await auto_research("query", _FakeTropebook(), max_results=5)
        assert result["provider"] == "serper"
        assert result["added"] == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_duckduckgo_when_no_keys_configured(self):
        fake_ddgs = MagicMock()
        fake_ddgs.__enter__ = MagicMock(return_value=fake_ddgs)
        fake_ddgs.__exit__ = MagicMock(return_value=False)
        fake_ddgs.text.return_value = [
            {"title": "A", "href": "https://a.com", "body": "desc"},
        ]
        with patch("ddgs.DDGS", return_value=fake_ddgs, create=True):
            result = await auto_research("query", _FakeTropebook(), max_results=5)
        assert result["provider"] == "duckduckgo"
        assert result["added"] == 1

    @pytest.mark.asyncio
    async def test_all_providers_failing_returns_error_not_crash(self, monkeypatch):
        with patch("ddgs.DDGS", side_effect=ImportError, create=True), \
             patch("duckduckgo_search.DDGS", side_effect=RuntimeError("boom"), create=True):
            result = await auto_research("query", _FakeTropebook(), max_results=5)
        assert result["added"] == 0
        assert result["provider"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_added_citations_carry_correct_source_type(self, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
        resp = _fake_response(200, {"web": {"results": [
            {"title": "A", "url": "https://a.com", "description": "desc"},
        ]}})
        tb = _FakeTropebook()
        with patch("httpx.AsyncClient", _fake_async_client(get_response=resp)):
            await auto_research("query", tb, max_results=5)
        assert len(tb.added) == 1
        assert tb.added[0]["url"] == "https://a.com"
