"""
Tropelex Background Scheduler

Runs periodic tasks via asyncio — research feeds, ghost scans,
stale-decision checks, and slack alerts.  Started by the FastAPI
lifespan handler; stops cleanly on shutdown.

All tasks are self-contained and log errors without crashing the loop.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("tropelex.scheduler")

# Intervals in seconds
FEED_TICK_INTERVAL = 3600        # 1 hour
GHOST_SCAN_INTERVAL = 21600      # 6 hours
STALE_CHECK_INTERVAL = 43200     # 12 hours


class BackgroundScheduler:
    """Manages periodic background tasks for Tropelex."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """Start the background loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Background scheduler started")

    async def stop(self):
        """Stop the background loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Background scheduler stopped")

    async def _loop(self):
        """Main loop — runs tasks at their respective intervals."""
        feed_tick = 0
        ghost_scan = 0
        stale_check = 0

        while self._running:
            try:
                await asyncio.sleep(60)  # tick every minute, check intervals

                feed_tick += 60
                ghost_scan += 60
                stale_check += 60

                if feed_tick >= FEED_TICK_INTERVAL:
                    feed_tick = 0
                    await self._tick_feeds()

                if ghost_scan >= GHOST_SCAN_INTERVAL:
                    ghost_scan = 0
                    await self._scan_ghost_decisions()

                if stale_check >= STALE_CHECK_INTERVAL:
                    stale_check = 0
                    await self._check_stale_decisions()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Scheduler loop error: %s", exc, exc_info=True)
                await asyncio.sleep(60)

    async def _tick_feeds(self):
        """Run all due research feeds."""
        try:
            from core.tropebook.research_feeds import ResearchFeedManager
            from core.tropebook.scheduler import FeedScheduler

            fm = ResearchFeedManager(storage_path=str(self.base_dir / "memory" / "feeds"))
            scheduler = FeedScheduler(
                feed_manager=fm,
                brave_api_key=os.environ.get("BRAVE_API_KEY"),
                storage_path=str(self.base_dir / "memory" / "tropebook"),
            )
            runs = scheduler.tick()
            if runs:
                logger.info("Feed tick: %d feeds executed", len(runs))
                # Wire slack alerts on errors
                await self._alert_on_feed_errors(runs)
        except Exception as exc:
            logger.error("Feed tick failed: %s", exc, exc_info=True)

    async def _alert_on_feed_errors(self, runs):
        """Send slack alerts for failed feed runs."""
        errors = [r for r in runs if r.status == "error"]
        if not errors:
            return
        try:
            from core.tropebook.alert_service import (
                format_slack_message,
                get_alert_webhook,
                send_slack_alert,
            )
            webhook = get_alert_webhook()
            if not webhook:
                return
            for run in errors:
                payload = format_slack_message(
                    run.query, "error",
                    {"error": run.error, "feed_id": run.feed_id},
                )
                await send_slack_alert(webhook, payload)
        except Exception as exc:
            logger.warning("Failed to send feed error alerts: %s", exc)

    async def _scan_ghost_decisions(self):
        """Scan all projects for ghost decisions."""
        try:
            from core.memory.manager import MemoryManager
            from core.ghost.detector import detect_ghost_decisions

            mm = MemoryManager(str(self.base_dir))
            for project in mm.list_projects():
                try:
                    memory = mm.get_project_memory(project)
                    decisions = memory.get("decisions", [])
                    if not decisions:
                        continue
                    # Ghost detection needs code context — skip if no tech_stack
                    # (indicates no codebase mapped yet)
                    if not memory.get("tech_stack"):
                        continue
                    result = detect_ghost_decisions(decisions, [])
                    if hasattr(result, "value") and result.value:
                        ghosts = result.value
                        if ghosts:
                            logger.info(
                                "Ghost scan %s: %d ghost(s) detected",
                                project, len(ghosts),
                            )
                except Exception as exc:
                    logger.warning("Ghost scan failed for %s: %s", project, exc)
        except Exception as exc:
            logger.error("Ghost scan failed: %s", exc, exc_info=True)

    async def _check_stale_decisions(self):
        """Check for stale decisions and log warnings."""
        try:
            from core.memory.manager import MemoryManager
            from core.knowledge_decay import get_stale_decisions

            mm = MemoryManager(str(self.base_dir))
            for project in mm.list_projects():
                try:
                    memory = mm.get_project_memory(project)
                    decisions = memory.get("decisions", [])
                    if len(decisions) < 3:
                        continue
                    stale = get_stale_decisions(decisions)
                    if stale:
                        logger.info(
                            "Stale check %s: %d stale decision(s)",
                            project, len(stale),
                        )
                except Exception as exc:
                    logger.warning("Stale check failed for %s: %s", project, exc)
        except Exception as exc:
            logger.error("Stale check failed: %s", exc, exc_info=True)
