"""
Research Feed Scheduler - Runs due feeds, ingests citations, generates markdown.

Handles: search → deduplicate → ingest → markdown append per feed execution.
"""

import logging
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from core.tropebook.research import BraveSearch, SearchResult
from core.tropebook.research_feeds import FeedRun, ResearchFeed, ResearchFeedManager

logger = logging.getLogger("tropelex.scheduler")


class FeedScheduler:
    """Executes feeds: search, dedup, ingest citations, append markdown."""

    def __init__(
        self,
        feed_manager: ResearchFeedManager,
        brave_api_key: str | None = None,
        storage_path: str = "memory/tropebook/",
    ):
        self.feeds = feed_manager
        self.search = BraveSearch(api_key=brave_api_key)
        self.storage_path = Path(storage_path)
        if not self.storage_path.is_absolute():
            self.storage_path = Path(__file__).parent.parent.parent / self.storage_path
        self._tb = None  # Lazy-loaded shared Tropebook instance

    @property
    def _tropebook(self):
        """Shared Tropebook instance (loaded once, reused across calls)."""
        if self._tb is None:
            from core.tropebook.tropebook import Tropebook
            self._tb = Tropebook(storage_path=str(self.storage_path))
        return self._tb

    def tick(self) -> list[FeedRun]:
        """Find all due feeds, run them, update next_run. Returns completed runs."""
        try:
            due = self.feeds.get_due_feeds()
            logger.info("Tick: %d feeds due", len(due))
            runs = []
            for feed in due:
                try:
                    run = self.run_feed(feed)
                    runs.append(run)
                    feed.next_run = self.feeds._compute_next_run(
                        feed.interval, datetime.now(timezone.utc)
                    )
                    self.feeds.feeds[feed.id] = feed
                except Exception as e:
                    logger.error("Failed to run feed %s: %s", feed.name, e)
            self.feeds._dirty_feeds = True
            self.feeds._save()
            return runs
        except Exception as e:
            logger.error("Tick failed: %s", e)
            return []

    def run_feed(self, feed: ResearchFeed) -> FeedRun:
        """Execute a single feed: search, deduplicate, ingest, render markdown.

        For deep_research feeds, the run stores rich HTML output in the
        feed's markdown file alongside ingested citations.
        """
        start = time.time()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        logger.info("Running feed %s: %s", feed.name, feed.query)

        try:
            search_results = self._search_feed(feed)
            deduped = self._deduplicate(search_results, feed)
            citations_added = self._ingest_citations(deduped, feed, run_id, now)
            duration = round(time.time() - start, 2)

            is_deep = feed.research_provider == "deep_research"

            # Extract the rich HTML result (if any) before building results_dicts
            deep_html = ""
            filtered: list[SearchResult] = []
            for r in deduped:
                if r.source == "deep_research_html":
                    deep_html = r.description  # Stored HTML preview
                else:
                    filtered.append(r)

            run = FeedRun(
                id=run_id, feed_id=feed.id, timestamp=now, query=feed.query,
                results_count=len(citations_added), citations_added=citations_added,
                status="success", error=None, duration_seconds=duration,
                source_breakdown=self._count_sources(filtered),
            )

            if is_deep and deep_html:
                self._append_deep_research_markdown(feed.id, run, deep_html)
            else:
                results_dicts = [
                    {"title": r.title, "url": r.url, "description": r.description,
                     "source": r.source}
                    for r in filtered
                ]
                self.feeds.append_to_markdown(feed.id, run, results_dicts)

            self.feeds.record_run(run)
            logger.info("Feed %s completed: %d new citations", feed.name, len(citations_added))
            return run

        except Exception as e:
            logger.error("Feed %s failed: %s", feed.name, e, exc_info=True)
            run = FeedRun(
                id=run_id, feed_id=feed.id, timestamp=now, query=feed.query,
                results_count=0, citations_added=[], status="error",
                error=str(e), duration_seconds=round(time.time() - start, 2),
            )
            self.feeds.record_run(run)
            return run

    def _append_deep_research_markdown(
        self, feed_id: str, run: FeedRun, html: str,
    ) -> None:
        """Append deep research HTML output directly to the feed's markdown."""
        from pathlib import Path
        fm = self.feeds
        feed = fm.feeds.get(feed_id)
        if not feed:
            return
        md_file = fm.feeds_dir / f"{feed_id}.md"
        try:
            if not md_file.exists():
                md_file.write_text(fm._generate_feed_header(feed))

            run_date = datetime.fromisoformat(run.timestamp).strftime("%Y-%m-%d")
            section = (
                f"\n\n## {run_date} — Deep Research\n\n"
                f"**Citations collected:** {run.results_count}\n\n"
                f"{html}\n\n---\n"
            )
            with open(md_file, "a") as f:
                f.write(section)
        except Exception as e:
            logger.error("Failed to append deep research markdown for feed %s: %s",
                         feed_id, e)

    def _search_feed(self, feed: ResearchFeed) -> list[SearchResult]:
        """Run search with multi-term support (OR/| splitting).

        When feed.research_provider == 'deep_research', delegates to the
        last30days engine which produces rich multi-source HTML output.
        Otherwise uses BraveSearch (default).
        """
        if feed.research_provider == "deep_research":
            return self._deep_research_feed(feed)

        try:
            terms = self._split_query(feed.query)
            per_term = max(feed.max_results_per_run // max(len(terms), 1), 5)
            all_results: list[SearchResult] = []
            errors: list[str] = []
            for term in terms:
                try:
                    all_results.extend(self.search.search(term.strip(), num_results=per_term))
                except Exception as e:
                    logger.warning("Search failed for term '%s': %s", term, e)
                    errors.append(str(e))
            # If all searches failed, raise the last error
            if not all_results and errors:
                raise RuntimeError(f"All searches failed: {'; '.join(errors)}")
            # Deduplicate by URL
            seen: set[str] = set()
            unique: list[SearchResult] = []
            for r in sorted(all_results, key=lambda r: r.url):
                if r.url not in seen:
                    seen.add(r.url)
                    unique.append(r)
            return unique[:feed.max_results_per_run]
        except RuntimeError:
            raise  # Re-raise to be caught by run_feed
        except Exception as e:
            logger.error("Search feed failed: %s", e)
            return []

    def _deep_research_feed(self, feed: ResearchFeed) -> list[SearchResult]:
        """Run a feed using the last30days deep research engine.

        Returns SearchResult items so the rest of the pipeline (dedup,
        ingest, markdown) works the same way.
        """
        try:
            from core.last30days.runner import run_query_and_extract_citations

            logger.info("Deep researching: %s", feed.query)
            html_output, citations = run_query_and_extract_citations(
                feed.query, timeout=180,  # 3 minutes default for deep research
            )

            results: list[SearchResult] = []
            for c in citations:
                results.append(SearchResult(
                    title=c.get("title", "Untitled"),
                    url=c.get("url", ""),
                    description="",
                    source="deep_research",
                ))

            # Store the rich HTML as a synthetic result for markdown rendering
            if html_output:
                results.append(SearchResult(
                    title=f"📊 Deep Research: {feed.name}",
                    url="",
                    description=html_output[:2000],
                    source="deep_research_html",
                ))

            logger.info("Deep research found %d citations for '%s'", len(results), feed.query)
            return results[:feed.max_results_per_run]

        except ImportError as e:
            logger.error("last30days runner not available: %s", e)
            return []
        except TimeoutError as e:
            logger.error("Deep research timed out: %s", e)
            return []
        except Exception as e:
            logger.error("Deep research failed: %s", e, exc_info=True)
            return []

    def _deduplicate(self, results: list[SearchResult], feed: ResearchFeed) -> list[SearchResult]:
        """Remove results whose URL already exists in the feed's citation set."""
        try:
            existing_urls: set[str] = set()
            for cid in feed.citation_ids:
                c = self._tropebook.get(cid)
                if c:
                    existing_urls.add(c.url)
            return [r for r in results if r.url not in existing_urls]
        except Exception as e:
            logger.warning("Deduplication failed: %s", e)
            return results  # Return original results if dedup fails

    def _ingest_citations(
        self, results: list[SearchResult], feed: ResearchFeed, run_id: str, timestamp: str,
    ) -> list[str]:
        """Add results as citations to Tropebook. Returns new citation IDs."""
        try:
            from core.tropebook.tropebook import SourceType
            added: list[str] = []
            for r in results:
                try:
                    cid = self._tropebook.add(
                        title=r.title, url=r.url, summary=r.description, source=r.source,
                        tags=feed.tags + [feed.name], source_type=SourceType.SCRAPED,
                        metadata={"feed_id": feed.id, "run_id": run_id, "timestamp": timestamp},
                    )
                    added.append(cid)
                except Exception as e:
                    logger.warning("Failed to ingest citation '%s': %s", r.title, e)
            return added
        except Exception as e:
            logger.error("Citation ingestion failed: %s", e)
            return []

    @staticmethod
    def _split_query(query: str) -> list[str]:
        """Split a query by OR or | into individual terms."""
        return [t.strip() for t in re.split(r"\s+OR\s+|\s*\|\s*", query) if t.strip()]

    @staticmethod
    def _count_sources(results: list[SearchResult]) -> dict[str, int]:
        """Count results per source type."""
        return dict(Counter(r.source for r in results))
