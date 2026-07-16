"""Tests for core.tropebook.research_feeds and core.tropebook.scheduler"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from core.tropebook.research_feeds import (
    FeedInterval,
    FeedRun,
    FeedStatus,
    ResearchFeed,
    ResearchFeedManager,
    _validate_feed_id,
)
from core.tropebook.scheduler import FeedScheduler
from core.tropebook.research import BraveSearch, SearchResult


# ─── research_feeds.py ───────────────────────────────────────────────────────


class TestResearchFeedModel:
    def test_to_dict_roundtrip(self):
        feed = ResearchFeed(
            id="abc123",
            name="Test Feed",
            query="test query",
            description="desc",
            interval="weekly",
            sources=["web", "hn"],
            enabled=True,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            next_run="2026-01-08T00:00:00",
            last_run=None,
            citation_ids=[],
            tags=["test"],
            max_results_per_run=20,
            status="active",
            total_runs=0,
            total_citations=0,
            run_history=[],
        )
        d = feed.to_dict()
        restored = ResearchFeed.from_dict(d)
        assert restored.id == "abc123"
        assert restored.name == "Test Feed"
        assert restored.sources == ["web", "hn"]
        assert restored.interval == "weekly"

    def test_feed_run_roundtrip(self):
        run = FeedRun(
            id="run1",
            feed_id="feed1",
            timestamp="2026-07-16T12:00:00",
            query="test",
            results_count=5,
            citations_added=["c1", "c2"],
            status="success",
            error=None,
            duration_seconds=3.14,
            source_breakdown={"web": 3, "hn": 2},
        )
        d = run.to_dict()
        restored = FeedRun.from_dict(d)
        assert restored.id == "run1"
        assert restored.citations_added == ["c1", "c2"]
        assert restored.duration_seconds == 3.14


class TestResearchFeedManager:
    @pytest.fixture
    def fm(self, tmp_path):
        return ResearchFeedManager(storage_path=str(tmp_path / "feeds"))

    def test_create_feed(self, fm):
        feed = fm.create(name="AI News", query="AI safety OR alignment")
        assert feed.id is not None
        assert feed.name == "AI News"
        assert feed.enabled is True
        assert feed.total_runs == 0
        assert feed.next_run is not None

    def test_get_feed(self, fm):
        feed = fm.create(name="Test", query="test query")
        got = fm.get(feed.id)
        assert got is not None
        assert got.name == "Test"

    def test_get_nonexistent_returns_none(self, fm):
        assert fm.get("nonexistent") is None

    def test_list_feeds(self, fm):
        fm.create(name="A", query="a")
        fm.create(name="B", query="b")
        feeds = fm.list_feeds()
        assert len(feeds) == 2

    def test_list_feeds_enabled_only(self, fm):
        f1 = fm.create(name="A", query="a")
        f2 = fm.create(name="B", query="b")
        fm.update(f2.id, enabled=False)
        feeds = fm.list_feeds(enabled_only=True)
        assert len(feeds) == 1
        assert feeds[0].id == f1.id

    def test_list_feeds_by_tag(self, fm):
        fm.create(name="A", query="a", tags=["python"])
        fm.create(name="B", query="b", tags=["rust"])
        feeds = fm.list_feeds(tag="python")
        assert len(feeds) == 1
        assert feeds[0].name == "A"

    def test_update_feed(self, fm):
        feed = fm.create(name="Old", query="old query")
        updated = fm.update(feed.id, name="New", interval="daily")
        assert updated.name == "New"
        assert updated.interval == "daily"

    def test_update_nonexistent_returns_none(self, fm):
        assert fm.update("nope", name="X") is None

    def test_delete_feed(self, fm):
        feed = fm.create(name="Del", query="del")
        assert fm.delete(feed.id) is True
        assert fm.get(feed.id) is None

    def test_delete_nonexistent_returns_false(self, fm):
        assert fm.delete("nope") is False

    def test_record_run(self, fm):
        feed = fm.create(name="T", query="t")
        run = FeedRun(
            id="r1",
            feed_id=feed.id,
            timestamp="2026-07-16T00:00:00",
            query="t",
            results_count=3,
            citations_added=["c1", "c2", "c3"],
            status="success",
            error=None,
            duration_seconds=1.0,
        )
        fm.record_run(run)
        updated = fm.get(feed.id)
        assert updated.total_runs == 1
        assert updated.total_citations == 3
        assert updated.citation_ids == ["c1", "c2", "c3"]
        assert updated.last_run == "2026-07-16T00:00:00"

    def test_get_runs(self, fm):
        feed = fm.create(name="T", query="t")
        for i in range(3):
            run = FeedRun(
                id=f"r{i}",
                feed_id=feed.id,
                timestamp=f"2026-07-1{i}T00:00:00",
                query="t",
                results_count=1,
                citations_added=[],
                status="success",
                error=None,
                duration_seconds=0.5,
            )
            fm.record_run(run)
        runs = fm.get_runs(feed_id=feed.id)
        assert len(runs) == 3
        assert runs[0].id == "r2"

    def test_get_due_feeds(self, fm):
        feed = fm.create(name="Due", query="due")
        fm.update(
            feed.id,
            next_run=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        due = fm.get_due_feeds()
        assert len(due) == 1

    def test_get_due_feeds_skips_disabled(self, fm):
        feed = fm.create(name="Disabled", query="d")
        fm.update(feed.id, enabled=False)
        fm.update(
            feed.id,
            next_run=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        due = fm.get_due_feeds()
        assert len(due) == 0

    def test_get_due_feeds_skips_paused(self, fm):
        feed = fm.create(name="Paused", query="p")
        fm.update(feed.id, status=FeedStatus.PAUSED.value)
        fm.update(
            feed.id,
            next_run=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        due = fm.get_due_feeds()
        assert len(due) == 0

    def test_stats(self, fm):
        fm.create(name="A", query="a", interval="daily")
        fm.create(name="B", query="b", interval="weekly")
        stats = fm.stats()
        assert stats["total_feeds"] == 2
        assert stats["active_feeds"] == 2
        assert stats["by_interval"]["daily"] == 1
        assert stats["by_interval"]["weekly"] == 1

    def test_persistence(self, tmp_path):
        fm1 = ResearchFeedManager(storage_path=str(tmp_path / "feeds"))
        fm1.create(name="Persist", query="persist")
        fm2 = ResearchFeedManager(storage_path=str(tmp_path / "feeds"))
        feeds = fm2.list_feeds()
        assert len(feeds) == 1
        assert feeds[0].name == "Persist"

    def test_append_to_markdown(self, fm):
        feed = fm.create(name="MD Feed", query="test")
        run = FeedRun(
            id="r1",
            feed_id=feed.id,
            timestamp="2026-07-16T12:00:00",
            query="test",
            results_count=2,
            citations_added=["c1", "c2"],
            status="success",
            error=None,
            duration_seconds=1.0,
        )
        results = [
            {"title": "Result 1", "url": "https://a.com", "description": "Desc 1"},
            {"title": "Result 2", "url": "https://b.com", "description": "Desc 2"},
        ]
        md = fm.append_to_markdown(feed.id, run, results)
        assert "# MD Feed" in md
        assert "Result 1" in md
        assert "Result 2" in md
        assert "2026-07-16 Run" in md

    def test_append_error_to_markdown(self, fm):
        feed = fm.create(name="Err Feed", query="err")
        run = FeedRun(
            id="r1",
            feed_id=feed.id,
            timestamp="2026-07-16T12:00:00",
            query="err",
            results_count=0,
            citations_added=[],
            status="error",
            error="Search API down",
            duration_seconds=0.1,
        )
        md = fm.append_to_markdown(feed.id, run, [])
        assert "Error" in md
        assert "Search API down" in md

    def test_get_feed_markdown_empty(self, fm):
        assert fm.get_feed_markdown("nonexistent") == ""

    def test_run_history_capped(self, fm):
        feed = fm.create(name="Cap", query="cap")
        for i in range(60):
            run = FeedRun(
                id=f"r{i}",
                feed_id=feed.id,
                timestamp=f"2026-07-01T00:{i:02d}:00",
                query="cap",
                results_count=0,
                citations_added=[],
                status="success",
                error=None,
                duration_seconds=0.1,
            )
            fm.record_run(run)
        updated = fm.get(feed.id)
        assert len(updated.run_history) == 50


# ─── scheduler.py ────────────────────────────────────────────────────────────


class TestFeedScheduler:
    @pytest.fixture
    def fm(self, tmp_path):
        return ResearchFeedManager(storage_path=str(tmp_path / "feeds"))

    @pytest.fixture
    def scheduler(self, fm):
        return FeedScheduler(
            feed_manager=fm,
            brave_api_key=None,
            storage_path=str(fm.storage_path.parent / "tropebook"),
        )

    def test_split_query_single(self):
        assert FeedScheduler._split_query("AI safety") == ["AI safety"]

    def test_split_query_or(self):
        terms = FeedScheduler._split_query("AI safety OR alignment OR x-risk")
        assert terms == ["AI safety", "alignment", "x-risk"]

    def test_split_query_pipe(self):
        terms = FeedScheduler._split_query("AI safety | alignment | x-risk")
        assert terms == ["AI safety", "alignment", "x-risk"]

    def test_count_sources(self):
        results = [
            SearchResult("A", "https://a.com", source="web"),
            SearchResult("B", "https://b.com", source="hn"),
            SearchResult("C", "https://c.com", source="web"),
        ]
        counts = FeedScheduler._count_sources(results)
        assert counts == {"web": 2, "hn": 1}

    def test_count_sources_empty(self):
        assert FeedScheduler._count_sources([]) == {}

    @patch.object(BraveSearch, "search")
    def test_run_feed_success(self, mock_search, fm, scheduler):
        mock_search.return_value = [
            SearchResult("Title 1", "https://a.com", "Desc 1", "web"),
            SearchResult("Title 2", "https://b.com", "Desc 2", "web"),
        ]
        feed = fm.create(name="Test", query="test query")
        run = scheduler.run_feed(feed)
        assert run.status == "success"
        assert run.results_count == 2
        assert len(run.citations_added) == 2
        assert mock_search.called

    @patch.object(BraveSearch, "search")
    def test_run_feed_records_run(self, mock_search, fm, scheduler):
        mock_search.return_value = [
            SearchResult("R", "https://r.com", "D", "web"),
        ]
        feed = fm.create(name="T", query="q")
        scheduler.run_feed(feed)
        updated = fm.get(feed.id)
        assert updated.total_runs == 1
        assert updated.total_citations == 1
        assert updated.last_run is not None

    @patch.object(BraveSearch, "search")
    def test_run_feed_error(self, mock_search, fm, scheduler):
        mock_search.side_effect = RuntimeError("API down")
        feed = fm.create(name="Fail", query="fail")
        run = scheduler.run_feed(feed)
        assert run.status == "error"
        assert "API down" in run.error

    @patch.object(BraveSearch, "search")
    def test_tick_runs_due_feeds(self, mock_search, fm, scheduler):
        mock_search.return_value = [SearchResult("R", "https://r.com", "D", "web")]
        feed = fm.create(name="Due", query="due")
        fm.update(
            feed.id,
            next_run=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        )
        runs = scheduler.tick()
        assert len(runs) == 1
        assert runs[0].status == "success"

    @patch.object(BraveSearch, "search")
    def test_tick_skips_non_due(self, mock_search, fm, scheduler):
        fm.create(name="Future", query="future")
        runs = scheduler.tick()
        assert len(runs) == 0
        assert not mock_search.called

    @patch.object(BraveSearch, "search")
    def test_run_feed_multiterm(self, mock_search, fm, scheduler):
        call_count = [0]

        def side_effect(query, num_results=10):
            call_count[0] += 1
            return [SearchResult(f"R{call_count[0]}", f"https://{call_count[0]}.com", "D", "web")]

        mock_search.side_effect = side_effect
        feed = fm.create(name="Multi", query="term1 OR term2 OR term3")
        run = scheduler.run_feed(feed)
        assert run.status == "success"
        assert mock_search.call_count == 3

    @patch.object(BraveSearch, "search")
    def test_generate_markdown(self, mock_search, fm, scheduler):
        mock_search.return_value = [
            SearchResult("Article", "https://art.com", "About AI", "web"),
        ]
        feed = fm.create(name="MD", query="AI")
        run = scheduler.run_feed(feed)
        md = fm.get_feed_markdown(feed.id)
        assert "# MD" in md
        assert "Article" in md
        assert "2026-" in md


# ─── Security / invariants ──────────────────────────────────────────────────


class TestFeedIdValidation:
    def test_valid_ids(self):
        assert _validate_feed_id("abc123")
        assert _validate_feed_id("my-feed_name")
        assert _validate_feed_id("A" * 64)

    def test_rejects_path_traversal(self):
        assert not _validate_feed_id("../../etc/passwd")
        assert not _validate_feed_id("../secret")

    def test_rejects_special_chars(self):
        assert not _validate_feed_id("feed; rm -rf /")
        assert not _validate_feed_id("feed`whoami`")
        assert not _validate_feed_id("feed${HOME}")

    def test_rejects_too_short(self):
        assert not _validate_feed_id("abc")

    def test_rejects_too_long(self):
        assert not _validate_feed_id("a" * 65)


class TestUpdateWhitelist:
    @pytest.fixture
    def fm(self, tmp_path):
        return ResearchFeedManager(storage_path=str(tmp_path / "feeds"))

    def test_cannot_set_total_runs(self, fm):
        feed = fm.create(name="T", query="q")
        updated = fm.update(feed.id, total_runs=999)
        assert updated.total_runs == 0  # unchanged

    def test_cannot_set_citation_ids(self, fm):
        feed = fm.create(name="T", query="q")
        updated = fm.update(feed.id, citation_ids=["fake1", "fake2"])
        assert updated.citation_ids == []  # unchanged

    def test_cannot_set_id(self, fm):
        feed = fm.create(name="T", query="q")
        updated = fm.update(feed.id, id="hacked")
        assert updated.id == feed.id  # unchanged

    def test_can_set_allowed_fields(self, fm):
        feed = fm.create(name="T", query="q")
        updated = fm.update(feed.id, name="New", enabled=False, status="paused")
        assert updated.name == "New"
        assert updated.enabled is False
        assert updated.status == "paused"


class TestIntervalValidation:
    @pytest.fixture
    def fm(self, tmp_path):
        return ResearchFeedManager(storage_path=str(tmp_path / "feeds"))

    def test_create_rejects_invalid_interval(self, fm):
        with pytest.raises(ValueError, match="Invalid interval"):
            fm.create(name="Bad", query="q", interval="banana")

    def test_create_accepts_valid_intervals(self, fm):
        for interval in ["daily", "weekly", "monthly", "manual"]:
            feed = fm.create(name=f"Feed-{interval}", query="q", interval=interval)
            assert feed.interval == interval
