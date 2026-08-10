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
        """Check for stale decisions and, when one is still referenced by
        other decisions, flag it for review (wishlist #58 -- closing the
        loop from "descriptive" decay to an actual signal).

        Deliberately stricter than get_stale_decisions' own default
        threshold (score<0.3 or age>180d, already shown in the dashboard's
        maintenance queue): only the worst tier ("stale", score<0.2) *and*
        reference_count > 0 (the only "still referenced" signal that
        exists in this codebase -- keyword-overlap against other
        decisions) creates a review entry, to keep this new actionable
        signal from being noisy. Idempotent: a decision already present in
        memory["decay_reviews"] is never re-flagged, so this can run every
        12h without piling up duplicates.
        """
        try:
            from core.memory.manager import MemoryManager
            from core.knowledge_decay import get_stale_decisions
            from core.audit import append_audit_event
            import uuid
            from datetime import datetime, timezone

            mm = MemoryManager(str(self.base_dir))
            for project in mm.list_projects():
                try:
                    memory = mm.get_project_memory(project)
                    decisions = memory.get("decisions", [])
                    if len(decisions) < 3:
                        continue
                    stale = get_stale_decisions(decisions)
                    if not stale:
                        continue
                    logger.info(
                        "Stale check %s: %d stale decision(s)",
                        project, len(stale),
                    )

                    existing = memory.get("decay_reviews", [])
                    if not isinstance(existing, list):
                        existing = []
                    already_flagged = {
                        r.get("decision_id") for r in existing if isinstance(r, dict)
                    }

                    newly_flagged = []
                    for d in stale:
                        if not isinstance(d, dict):
                            continue
                        conf = d.get("confidence", {})
                        if not isinstance(conf, dict):
                            continue
                        if conf.get("tier") != "stale":
                            continue
                        if conf.get("reference_count", 0) <= 0:
                            continue
                        if d.get("pinned"):
                            continue
                        did = d.get("id") or d.get("timestamp", "")
                        if not did or did in already_flagged:
                            continue
                        newly_flagged.append({
                            "id": uuid.uuid4().hex[:12],
                            "decision_id": did,
                            "decision": d.get("decision", "")[:200],
                            "tier": conf.get("tier"),
                            "score": conf.get("score"),
                            "reference_count": conf.get("reference_count", 0),
                            "flagged_at": datetime.now(timezone.utc).isoformat(),
                            "review_status": "pending",
                        })
                        already_flagged.add(did)

                    if newly_flagged:
                        memory["decay_reviews"] = existing + newly_flagged
                        try:
                            append_audit_event(
                                memory, "decay_review_flagged",
                                project=project, count=len(newly_flagged),
                            )
                        except Exception as exc:
                            logger.warning("decay_review_flagged audit event failed for %s: %s", project, exc)
                        mm.save_project_memory(project, memory)
                        logger.info(
                            "Decay review: %d decision(s) newly flagged in %s",
                            len(newly_flagged), project,
                        )
                except Exception as exc:
                    logger.warning("Stale check failed for %s: %s", project, exc)
        except Exception as exc:
            logger.error("Stale check failed: %s", exc, exc_info=True)
