"""Router tests for GET/PUT .../research/source-coverage and
.../research/disabled-sources (wishlist #88). Isolates both the global
Tropebook and the feed manager, matching test_web_researcher_router.py's
isolated_tropebook and test_deep_research.py's feed-storage fixtures --
without both, this would write real citations/feeds into the live repo's
production stores.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from core.tropebook.research_feeds import ResearchFeedManager
from core.tropebook.tropebook import Tropebook
from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_srccov_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def isolated_stores(tmp_path):
    from core.tropebook.web import server as server_module

    original_tb = server_module._state["tropebook"]
    server_module._state["tropebook"] = Tropebook(storage_path=str(tmp_path / "tropebook"))

    original_fm = server_module._feed_manager
    server_module._feed_manager = ResearchFeedManager(storage_path=str(tmp_path / "feeds"))

    try:
        yield server_module._state["tropebook"], server_module._feed_manager
    finally:
        server_module._state["tropebook"] = original_tb
        server_module._feed_manager = original_fm


def _create_decision(client, project, citation_ids=None):
    client.post("/api/memory", json={"project_name": project})
    body = {
        "decision": "Use React", "context": "", "safety_metadata": {"safety_category": "general"},
    }
    if citation_ids:
        body["citation_ids"] = citation_ids
    resp = client.post(f"/api/memory/{project}/decisions", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["decision"]


class TestSourceCoverageEndpoint:
    def test_empty_project_returns_empty_report(self, client, project, isolated_stores):
        client.post("/api/memory", json={"project_name": project})
        resp = client.get(f"/api/memory/{project}/research/source-coverage")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sources"] == []
        assert body["total_citations"] == 0

    def test_citation_referenced_by_a_decision_counts_as_useful(self, client, project, isolated_stores):
        tb, fm = isolated_stores
        cid = tb.add(title="A", url="https://github.com/a/b", summary="")

        _create_decision(client, project, citation_ids=[cid])

        resp = client.get(f"/api/memory/{project}/research/source-coverage")
        body = resp.json()
        github = next(s for s in body["sources"] if s["source"] == "github")
        assert github["count"] == 1
        assert github["useful_count"] == 1
        assert github["value_rate"] == 1.0

    def test_citation_from_a_visible_feed_counted_even_if_not_cited_by_a_decision(
        self, client, project, isolated_stores,
    ):
        tb, fm = isolated_stores
        cid = tb.add(title="A", url="https://reddit.com/r/x", summary="")
        feed = fm.create(name="Feed", query="q", project=project)
        feed.citation_ids = [cid]
        fm.feeds[feed.id] = feed
        fm._save()

        client.post("/api/memory", json={"project_name": project})
        resp = client.get(f"/api/memory/{project}/research/source-coverage")
        body = resp.json()
        reddit = next(s for s in body["sources"] if s["source"] == "reddit")
        assert reddit["count"] == 1
        assert reddit["useful_count"] == 0  # never referenced by a decision

    def test_citation_from_a_feed_scoped_to_another_project_is_excluded(
        self, client, project, isolated_stores,
    ):
        tb, fm = isolated_stores
        cid = tb.add(title="A", url="https://reddit.com/r/x", summary="")
        feed = fm.create(name="Feed", query="q", project="some-other-project")
        feed.citation_ids = [cid]
        fm.feeds[feed.id] = feed
        fm._save()

        client.post("/api/memory", json={"project_name": project})
        resp = client.get(f"/api/memory/{project}/research/source-coverage")
        assert resp.json()["sources"] == []

    def test_disabled_source_reflected_in_the_report(self, client, project, isolated_stores):
        tb, fm = isolated_stores
        cid = tb.add(title="A", url="https://github.com/a/b", summary="")
        _create_decision(client, project, citation_ids=[cid])

        client.put(f"/api/memory/{project}/research/disabled-sources", json={"sources": ["github"]})

        resp = client.get(f"/api/memory/{project}/research/source-coverage")
        github = next(s for s in resp.json()["sources"] if s["source"] == "github")
        assert github["disabled"] is True


class TestDisabledSourcesEndpoint:
    def test_empty_by_default(self, client, project):
        client.post("/api/memory", json={"project_name": project})
        resp = client.get(f"/api/memory/{project}/research/disabled-sources")
        assert resp.json()["disabled_sources"] == []

    def test_set_and_read_back(self, client, project):
        client.post("/api/memory", json={"project_name": project})
        client.put(f"/api/memory/{project}/research/disabled-sources", json={"sources": ["reddit", "x"]})
        resp = client.get(f"/api/memory/{project}/research/disabled-sources")
        assert resp.json()["disabled_sources"] == ["reddit", "x"]

    def test_dedupes(self, client, project):
        client.post("/api/memory", json={"project_name": project})
        resp = client.put(
            f"/api/memory/{project}/research/disabled-sources", json={"sources": ["reddit", "reddit"]},
        )
        assert resp.json()["disabled_sources"] == ["reddit"]
