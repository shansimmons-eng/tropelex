"""
Research Feeds - Persistent, scheduled research queries that auto-refresh
and accumulate citations over time with markdown export.

Data model:
    ResearchFeed: A named, scheduled query with interval, sources, and tags.
    FeedRun:      A single execution record for a feed.
    ResearchFeedManager: CRUD + persistence + markdown generation.
"""

import json
import logging
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

logger = logging.getLogger("tropelex.feeds")

# Fields allowed to be mutated via update()
_UPDATABLE_FIELDS = frozenset({
    "name", "query", "description", "interval", "sources",
    "tags", "max_results_per_run", "enabled", "status", "next_run",
    "research_provider",
})

# feed_id must be safe for use in file paths
_FEED_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{4,64}$")


class FeedInterval(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MANUAL = "manual"


class FeedStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class FeedRun:
    """Record of a single feed execution."""
    id: str
    feed_id: str
    timestamp: str
    query: str
    results_count: int
    citations_added: list[str]
    status: str
    error: str | None
    duration_seconds: float
    source_breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FeedRun":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ResearchFeed:
    """A named, scheduled research query that accumulates citations."""
    id: str
    name: str
    query: str
    description: str
    interval: str
    sources: list[str]
    enabled: bool
    created_at: str
    updated_at: str
    next_run: str
    last_run: str | None
    citation_ids: list[str]
    tags: list[str]
    max_results_per_run: int
    status: str
    total_runs: int
    total_citations: int
    run_history: list[dict]
    research_provider: str = "web_search"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchFeed":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _validate_feed_id(feed_id: str) -> bool:
    """Return True if feed_id is safe for file-path use."""
    return bool(_FEED_ID_RE.match(feed_id))


def _atomic_write(path: Path, data: str) -> None:
    """Write data to path atomically via temp file + replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class ResearchFeedManager:
    """CRUD + persistence + markdown generation for research feeds."""

    def __init__(self, storage_path: str = "memory/"):
        self.storage_path = Path(storage_path)
        if not self.storage_path.is_absolute():
            self.storage_path = Path(__file__).parent.parent.parent / self.storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.feeds_file = self.storage_path / "research_feeds.json"
        self.runs_file = self.storage_path / "research_feeds_runs.json"
        self.feeds_dir = self.storage_path / "research_feeds"
        self.feeds_dir.mkdir(parents=True, exist_ok=True)
        self.feeds: dict[str, ResearchFeed] = {}
        self.runs: dict[str, FeedRun] = {}
        self._dirty_feeds = False
        self._dirty_runs = False
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self):
        """Load feeds and runs from disk with error handling."""
        try:
            if self.feeds_file.exists():
                with open(self.feeds_file) as f:
                    data = json.load(f)
                    self.feeds = {k: ResearchFeed.from_dict(v) for k, v in data.items()}
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Failed to load feeds file: %s", e)
            self.feeds = {}
        except Exception as e:
            logger.error("Unexpected error loading feeds: %s", e)
            self.feeds = {}
        
        try:
            if self.runs_file.exists():
                with open(self.runs_file) as f:
                    data = json.load(f)
                    self.runs = {k: FeedRun.from_dict(v) for k, v in data.items()}
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Failed to load runs file: %s", e)
            self.runs = {}
        except Exception as e:
            logger.error("Unexpected error loading runs: %s", e)
            self.runs = {}

    def _save(self):
        """Atomically write only the files that changed."""
        if self._dirty_feeds:
            try:
                _atomic_write(self.feeds_file, json.dumps(
                    {k: v.to_dict() for k, v in self.feeds.items()}, indent=2
                ))
                self._dirty_feeds = False
            except Exception as e:
                logger.error("Failed to save feeds: %s", e)
                raise
        if self._dirty_runs:
            try:
                _atomic_write(self.runs_file, json.dumps(
                    {k: v.to_dict() for k, v in self.runs.items()}, indent=2
                ))
                self._dirty_runs = False
            except Exception as e:
                logger.error("Failed to save runs: %s", e)
                raise

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        query: str,
        description: str = "",
        interval: str = "weekly",
        sources: list[str] | None = None,
        tags: list[str] | None = None,
        max_results_per_run: int = 20,
        research_provider: str = "web_search",
    ) -> ResearchFeed:
        """Create a new feed. Raises ValueError on invalid interval."""
        if interval not in {e.value for e in FeedInterval}:
            raise ValueError(f"Invalid interval: {interval!r}")
        if research_provider not in ("web_search", "deep_research"):
            raise ValueError(f"Invalid research_provider: {research_provider!r}")
        now = datetime.now(timezone.utc).isoformat()
        feed_id = uuid.uuid4().hex[:12]
        feed = ResearchFeed(
            id=feed_id, name=name, query=query, description=description,
            interval=interval, sources=sources or ["web"], enabled=True,
            created_at=now, updated_at=now,
            next_run=self._compute_next_run(interval, datetime.now(timezone.utc)),
            last_run=None, citation_ids=[], tags=tags or [],
            max_results_per_run=max_results_per_run,
            status=FeedStatus.ACTIVE.value, total_runs=0,
            total_citations=0, run_history=[],
            research_provider=research_provider,
        )
        self.feeds[feed_id] = feed
        self._dirty_feeds = True
        self._save()
        return feed

    def get(self, feed_id: str) -> ResearchFeed | None:
        """Return a feed by ID, or None."""
        return self.feeds.get(feed_id)

    def list_feeds(self, enabled_only: bool = False, tag: str | None = None) -> list[ResearchFeed]:
        """Return feeds, optionally filtered by enabled state or tag."""
        feeds = list(self.feeds.values())
        if enabled_only:
            feeds = [f for f in feeds if f.enabled]
        if tag:
            feeds = [f for f in feeds if tag in f.tags]
        feeds.sort(key=lambda f: f.created_at, reverse=True)
        return feeds

    def update(self, feed_id: str, **kwargs) -> ResearchFeed | None:
        """Update whitelisted fields on a feed. Returns None if not found."""
        feed = self.feeds.get(feed_id)
        if not feed:
            return None
        for key, value in kwargs.items():
            if key in _UPDATABLE_FIELDS and hasattr(feed, key):
                setattr(feed, key, value)
        feed.updated_at = datetime.now(timezone.utc).isoformat()
        self._dirty_feeds = True
        self._save()
        return feed

    def delete(self, feed_id: str) -> bool:
        """Delete a feed, its runs, and its markdown file. Returns False if not found."""
        if feed_id not in self.feeds:
            return False
        del self.feeds[feed_id]
        self.runs = {k: v for k, v in self.runs.items() if v.feed_id != feed_id}
        md_file = self.feeds_dir / f"{feed_id}.md"
        try:
            if md_file.exists():
                md_file.unlink()
        except Exception as e:
            logger.warning("Failed to delete markdown file for feed %s: %s", feed_id, e)
        self._dirty_feeds = True
        self._dirty_runs = True
        self._save()
        return True

    # ── Scheduling ───────────────────────────────────────────────────────

    def get_due_feeds(self) -> list[ResearchFeed]:
        """Return enabled, non-paused feeds whose next_run is in the past."""
        now = datetime.now(timezone.utc)
        return [
            f for f in self.feeds.values()
            if f.enabled and f.status != FeedStatus.PAUSED.value and self._is_due(f, now)
        ]

    # ── Runs ─────────────────────────────────────────────────────────────

    def record_run(self, run: FeedRun) -> None:
        """Record a run and update feed counters."""
        self.runs[run.id] = run
        feed = self.feeds.get(run.feed_id)
        if feed:
            feed.total_runs += 1
            feed.total_citations += len(run.citations_added)
            feed.citation_ids.extend(run.citations_added)
            feed.last_run = run.timestamp
            feed.updated_at = run.timestamp
            feed.run_history.append({
                "run_id": run.id, "timestamp": run.timestamp,
                "results_count": run.results_count, "status": run.status,
            })
            if len(feed.run_history) > 50:
                feed.run_history = feed.run_history[-50:]
        self._dirty_feeds = True
        self._dirty_runs = True
        self._save()

    def get_runs(self, feed_id: str | None = None, limit: int = 20) -> list[FeedRun]:
        """Return the most recent runs, optionally filtered by feed."""
        runs = list(self.runs.values())
        if feed_id:
            runs = [r for r in runs if r.feed_id == feed_id]
        runs.sort(key=lambda r: r.timestamp, reverse=True)
        return runs[:limit]

    # ── Markdown ─────────────────────────────────────────────────────────

    def get_feed_markdown(self, feed_id: str) -> str:
        """Return the persistent markdown content for a feed, or empty string."""
        md_file = self.feeds_dir / f"{feed_id}.md"
        try:
            return md_file.read_text() if md_file.exists() else ""
        except Exception as e:
            logger.error("Failed to read markdown for feed %s: %s", feed_id, e)
            return ""

    def set_feed_markdown(self, feed_id: str, content: str) -> bool:
        """Overwrite a feed's markdown file wholesale -- used by bulk
        import (#91) to restore markdown history from an export bundle.
        Unlike append_to_markdown, this replaces rather than adds a
        section, since a freshly-created feed has no prior run to append
        after. Returns False if the feed doesn't exist."""
        if feed_id not in self.feeds:
            return False
        md_file = self.feeds_dir / f"{feed_id}.md"
        try:
            md_file.write_text(content)
            return True
        except Exception as e:
            logger.error("Failed to set markdown for feed %s: %s", feed_id, e)
            return False

    def append_to_markdown(self, feed_id: str, run: FeedRun, results: list[dict]) -> str:
        """Append a run's results to the feed's markdown file. Returns updated content."""
        feed = self.feeds.get(feed_id)
        if not feed:
            return ""
        md_file = self.feeds_dir / f"{feed_id}.md"
        try:
            if not md_file.exists():
                md_file.write_text(self._generate_feed_header(feed))

            section = self._render_run_section(run, results)
            with open(md_file, "a") as f:
                f.write(section)
            return md_file.read_text()
        except Exception as e:
            logger.error("Failed to append to markdown for feed %s: %s", feed_id, e)
            return ""

    # ── Stats ────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Aggregate stats across all feeds (single pass)."""
        by_interval = {i.value: 0 for i in FeedInterval}
        active = total_runs = total_citations = 0
        for f in self.feeds.values():
            if f.enabled:
                active += 1
            total_runs += f.total_runs
            total_citations += f.total_citations
            if f.interval in by_interval:
                by_interval[f.interval] += 1
        return {
            "total_feeds": len(self.feeds),
            "active_feeds": active,
            "total_runs": total_runs,
            "total_citations": total_citations,
            "by_interval": by_interval,
        }

    # ── Private helpers ──────────────────────────────────────────────────

    def _generate_feed_header(self, feed: ResearchFeed) -> str:
        return (
            f"# {feed.name}\n\n"
            f"**Feed:** {feed.id} | **Query:** {feed.query} | **Interval:** {feed.interval}\n"
            f"**Sources:** {', '.join(feed.sources)}\n\n"
            f"---"
        )

    def _render_run_section(self, run: FeedRun, results: list[dict]) -> str:
        """Render a single run as a markdown section.

        `results` is the full raw result set for this run, not deduplicated
        against prior runs -- a source reappearing across runs is itself
        informative (multiple runs agreeing on it), not noise to hide.
        `run.results_count` stays the *new*-citations-ingested count (a
        distinct, still-useful number), so the header shows both.
        """
        run_date = datetime.fromisoformat(run.timestamp).strftime("%Y-%m-%d")
        lines = [f"\n\n## {run_date} Run ({len(results)} found, {run.results_count} new)\n\n"]

        if run.status == "success" and results:
            lines.append("### Key Findings\n\n")
            for i, r in enumerate(results, 1):
                title, url = r.get("title", "Untitled"), r.get("url", "")
                snippet = r.get("description", r.get("snippet", ""))
                lines.append(f"{i}. **{title}**")
                if url:
                    lines.append(f" - [Source]({url})")
                lines.append("\n")
                if snippet:
                    lines.append(f"   > {snippet[:200]}...\n")
                lines.append("\n")
            lines.append("### All Citations\n\n")
            for i, cid in enumerate(run.citations_added, 1):
                lines.append(f"[^{i}]: Citation {cid}\n")
        elif run.status == "error":
            lines.append(f"**Error:** {run.error}\n")
        else:
            lines.append("No results found.\n")

        lines.append("\n---\n")
        return "".join(lines)

    @staticmethod
    def _is_due(feed: ResearchFeed, now: datetime) -> bool:
        if not feed.next_run:
            return True
        try:
            next_run = datetime.fromisoformat(feed.next_run)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            return now >= next_run
        except (ValueError, TypeError):
            return True

    @staticmethod
    def _compute_next_run(interval: str, from_time: datetime) -> str:
        deltas = {
            "daily": timedelta(days=1),
            "weekly": timedelta(days=7),
            "monthly": timedelta(days=30),
        }
        delta = deltas.get(interval)
        if delta is None:
            # manual or unknown: schedule far future (manually triggered only)
            return (from_time + timedelta(days=365 * 10)).isoformat()
        return (from_time + delta).isoformat()
