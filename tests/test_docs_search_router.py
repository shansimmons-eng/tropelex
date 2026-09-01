"""
Tests for GET /api/docs-search (core/docs_search_router.py) -- the HTTP
wrapper around core.docs_search, the "Documentation" category behind the
dashboard sidebar search widget.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


class TestDocsSearchEndpoint:
    def test_real_query_returns_ranked_results(self, client):
        resp = client.get("/api/docs-search", params={"q": "ghost decisions"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "ghost decisions"
        assert body["count"] == len(body["results"])
        assert body["results"]
        assert body["results"][0]["score"] >= body["results"][-1]["score"]

    def test_unrelated_query_returns_empty_results(self, client):
        resp = client.get("/api/docs-search", params={"q": "xyzzy plugh frotz"})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_limit_is_respected(self, client):
        resp = client.get("/api/docs-search", params={"q": "decision", "limit": 3})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 3

    def test_missing_query_is_422(self, client):
        resp = client.get("/api/docs-search")
        assert resp.status_code == 422

    def test_result_includes_a_faq_or_guide_source(self, client):
        resp = client.get("/api/docs-search", params={"q": "ghost decisions"})
        sources = {r["source"] for r in resp.json()["results"]}
        assert sources & {"Guide", "FAQ"}
