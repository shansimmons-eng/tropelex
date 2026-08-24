"""Router-level test for GET /api/research-feeds/{feed_id}/citation-health
(#80) -- the pure scoring logic is covered by
tests/test_feed_intelligence.py::TestScoreFeedCitationHealth; this proves
the endpoint actually wires a feed's citation_ids to the real global
Tropebook store correctly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def isolated_stores(tmp_path):
    """Swap both the global Tropebook and the feed_intelligence_router's
    ResearchFeedManager for tmp_path-scoped instances, matching
    tests/test_injection_sentinel_router.py's isolated_tropebook fixture.
    """
    from core.tropebook.research_feeds import ResearchFeedManager
    from core.tropebook.tropebook import Tropebook
    from core.tropebook.web import server as server_module
    from core.tropebook import feed_intelligence_router as fi_router_module

    original_tropebook = server_module._state["tropebook"]
    server_module._state["tropebook"] = Tropebook(storage_path=str(tmp_path / "tropebook"))

    fm = ResearchFeedManager(storage_path=str(tmp_path / "feeds"))
    original_get_fm = fi_router_module._get_fm
    fi_router_module._get_fm = lambda: fm

    try:
        yield fm
    finally:
        server_module._state["tropebook"] = original_tropebook
        fi_router_module._get_fm = original_get_fm


class TestFeedIntelligenceEndpoint:
    """Regression coverage for a real bug found while building #85: FeedRun.
    to_dict() has no 'citations' key (the real field is citations_added),
    so compute_feed_intelligence's count-based signals (spike/drop/stale)
    silently no-op against every real run until the router started passing
    citations_added through as 'citations'."""

    def test_404_for_unknown_feed(self, client, isolated_stores):
        res = client.get("/api/research-feeds/nope/intelligence")
        assert res.status_code == 404

    def test_stale_run_detected_from_real_run_shape(self, client, isolated_stores):
        from core.tropebook.research_feeds import FeedRun

        fm = isolated_stores
        feed = fm.create(name="Stale Feed", query="test query")
        now = datetime.now(timezone.utc)
        fm.record_run(FeedRun(
            id="r1", feed_id=feed.id, timestamp=now.isoformat(),
            query="test query", results_count=3, citations_added=["c1", "c2", "c3"],
            status="success", error=None, duration_seconds=1.0,
        ))
        fm.record_run(FeedRun(
            id="r2", feed_id=feed.id, timestamp=(now + timedelta(hours=1)).isoformat(),
            query="test query", results_count=0, citations_added=[],
            status="success", error=None, duration_seconds=1.0,
        ))

        res = client.get(f"/api/research-feeds/{feed.id}/intelligence")

        assert res.status_code == 200
        anomalies = res.json()["anomalies"]
        assert any(a["anomaly_type"] == "stale" for a in anomalies)

    def test_spike_detected_from_real_run_shape(self, client, isolated_stores):
        from core.tropebook.research_feeds import FeedRun

        fm = isolated_stores
        feed = fm.create(name="Spike Feed", query="test query")
        now = datetime.now(timezone.utc)
        for i, count in enumerate([2, 2, 2, 20]):
            fm.record_run(FeedRun(
                id=f"r{i}", feed_id=feed.id, timestamp=(now + timedelta(hours=i)).isoformat(),
                query="test query", results_count=count,
                citations_added=[f"c{i}_{j}" for j in range(count)],
                status="success", error=None, duration_seconds=1.0,
            ))

        res = client.get(f"/api/research-feeds/{feed.id}/intelligence")

        anomalies = res.json()["anomalies"]
        assert any(a["anomaly_type"] == "spike" for a in anomalies)


class TestFeedCitationHealthEndpoint:
    def test_404_for_unknown_feed(self, client, isolated_stores):
        res = client.get("/api/research-feeds/nope/citation-health")
        assert res.status_code == 404

    def test_feed_with_no_citations(self, client, isolated_stores):
        fm = isolated_stores
        feed = fm.create(name="Empty Feed", query="test query")

        res = client.get(f"/api/research-feeds/{feed.id}/citation-health")

        assert res.status_code == 200
        assert res.json() == {"count": 0, "average_score": None, "aging_count": 0, "citations": []}

    def test_feed_citations_are_scored(self, client, isolated_stores):
        fm = isolated_stores
        feed = fm.create(name="Real Feed", query="test query")

        from core.tropebook.web.server import get_tropebook

        tropebook = get_tropebook()
        fresh_id = tropebook.add(title="Fresh", url="https://example.com/fresh", summary="")
        old_ts = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        old_id = tropebook.add(title="Old", url="https://example.com/old", summary="")
        tropebook.citations[old_id].created_at = old_ts

        feed.citation_ids = [fresh_id, old_id]
        fm.feeds[feed.id] = feed
        fm._save()

        res = client.get(f"/api/research-feeds/{feed.id}/citation-health")

        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 2
        assert body["aging_count"] == 1
