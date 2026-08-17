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
PERSONA_MARKET_ESCALATION_INTERVAL = 21600  # 6 hours
# P8: configurable per plan.md's design -- operators auditing a more
# sensitive harness surface may want this tighter than the 6h default.
AGENT_AUDIT_INTERVAL = int(os.environ.get("AGENT_AUDIT_INTERVAL", "21600"))


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
        persona_market_escalation = 0
        agent_audit = 0

        while self._running:
            try:
                await asyncio.sleep(60)  # tick every minute, check intervals

                feed_tick += 60
                ghost_scan += 60
                stale_check += 60
                persona_market_escalation += 60
                agent_audit += 60

                if feed_tick >= FEED_TICK_INTERVAL:
                    feed_tick = 0
                    await self._tick_feeds()

                if ghost_scan >= GHOST_SCAN_INTERVAL:
                    ghost_scan = 0
                    await self._scan_ghost_decisions()

                if stale_check >= STALE_CHECK_INTERVAL:
                    stale_check = 0
                    await self._check_stale_decisions()

                if persona_market_escalation >= PERSONA_MARKET_ESCALATION_INTERVAL:
                    persona_market_escalation = 0
                    await self._apply_persona_market_escalations()

                if agent_audit >= AGENT_AUDIT_INTERVAL:
                    agent_audit = 0
                    await self._scan_agent_surfaces()

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
        """Scan all projects for ghost decisions against real git diffs
        (P4). Advisory only -- this path never gates, only the preventive
        check does, so a false positive here costs nothing but a Needs
        Attention entry.

        Was previously calling detect_ghost_decisions(decisions, []) --
        passing the decisions *list* where the function expects the full
        memory *dict*, and treating a plain GhostReport dataclass as if it
        were a Result with a .value attribute. Both mean this has been
        silently no-op-ing (AttributeError caught by the try/except below,
        logged as a warning) since the day it was added; diff_data was
        also always [], which short-circuits detect_ghost_decisions to an
        empty report regardless.
        """
        try:
            from core.memory.manager import MemoryManager
            from core.ghost.detector import detect_ghost_decisions
            from core.ghost.diff_source import recent_diffs
            from core.audit import append_audit_event
            from datetime import datetime, timezone

            mm = MemoryManager(str(self.base_dir))
            for project in mm.list_projects():
                try:
                    memory = mm.get_project_memory(project)
                    decisions = memory.get("decisions", [])
                    if not decisions:
                        continue

                    ghost_scan = memory.get("ghost_scan", {})
                    last_scan_ts = ghost_scan.get("last_scan_ts") if isinstance(ghost_scan, dict) else None
                    diff_data = recent_diffs(memory, since_ts=last_scan_ts)
                    if not diff_data:
                        # No repo synced, not a git repo, or nothing new
                        # since the last scan -- nothing to check.
                        continue

                    report = detect_ghost_decisions(memory, diff_data)
                    now = datetime.now(timezone.utc).isoformat()
                    memory.setdefault("ghost_scan", {})
                    memory["ghost_scan"]["last_scan_ts"] = now
                    memory["ghost_scan"]["last_diff_count"] = len(diff_data)

                    if report.total_ghosts:
                        logger.info(
                            "Ghost scan %s: %d ghost(s) detected across %d diff(s)",
                            project, report.total_ghosts, len(diff_data),
                        )
                        try:
                            append_audit_event(
                                memory, "ghost_scan_detected",
                                count=report.total_ghosts,
                                severity_distribution=report.severity_distribution,
                                diffs_checked=len(diff_data),
                            )
                        except Exception as exc:
                            logger.warning("ghost_scan_detected audit event failed for %s: %s", project, exc)

                    mm.save_project_memory(project, memory)
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

    async def _apply_persona_market_escalations(self):
        """Run persona/market compounding-risk escalation for every project.

        Moves the mutation that used to run implicitly on every
        GET /reviews/pending onto this periodic task instead (gap D, P0).
        """
        try:
            from core.memory.manager import MemoryManager
            from core.tropebook.web.server import _apply_persona_market_escalation

            mm = MemoryManager(str(self.base_dir))
            for project in mm.list_projects():
                try:
                    memory = mm.get_project_memory(project)
                    escalated = _apply_persona_market_escalation(project, memory, mm)
                    if escalated:
                        logger.info(
                            "Persona/market escalation %s: %d decision(s) escalated",
                            project, escalated,
                        )
                except Exception as exc:
                    logger.warning("Persona/market escalation failed for %s: %s", project, exc)
        except Exception as exc:
            logger.error("Persona/market escalation failed: %s", exc, exc_info=True)

    async def _scan_agent_surfaces(self):
        """Scheduled Agent Surface Audit (P8, gap F): audit_agent_surface
        (core/agent_audit/scanner.py) exists and scans a repo's harness
        config for secrets/permissions/hooks/MCP/agent-config risk, but
        was only ever reachable via a manual POST /api/agent-audit/scan --
        config drift (a new secret committed, a new curl|sh hook) between
        manual runs went undetected.

        Scans each project's own connected repo (memory["repo_path"], the
        same field ghost detection's diff source uses) -- a project with
        no repo synced has nothing to scan and is skipped gracefully, same
        shape as every other per-project scheduled task.
        """
        try:
            from core.memory.manager import MemoryManager
            from core.agent_audit.scanner import audit_agent_surface
            from core.git_integration import get_project_repo_path
            from core.audit import append_audit_event
            from datetime import datetime, timezone

            mm = MemoryManager(str(self.base_dir))
            for project in mm.list_projects():
                try:
                    memory = mm.get_project_memory(project)
                    repo_path = get_project_repo_path(memory)
                    if not repo_path:
                        continue

                    report = audit_agent_surface(repo_path)
                    now = datetime.now(timezone.utc).isoformat()

                    # Point-in-time snapshot, not accumulated history --
                    # config drift is about *current* state, and re-scanning
                    # the same files every interval is the expected behavior
                    # here (unlike ghost detection's incremental diffs).
                    memory["agent_surface_audit"] = {
                        "last_scan_ts": now,
                        "grade": report.grade,
                        "files_scanned": report.files_scanned,
                        "severity_distribution": report.severity_distribution,
                        "findings": [
                            {
                                "id": f.id, "category": f.category, "severity": f.severity,
                                "file": f.file, "line": f.line,
                                "description": f.description, "recommendation": f.recommendation,
                            }
                            for f in report.findings
                        ],
                    }

                    if report.findings:
                        logger.info(
                            "Agent surface audit %s: %d finding(s), grade %s",
                            project, len(report.findings), report.grade,
                        )
                        try:
                            append_audit_event(
                                memory, "agent_surface_finding",
                                count=len(report.findings),
                                severity_distribution=report.severity_distribution,
                                grade=report.grade,
                            )
                        except Exception as exc:
                            logger.warning("agent_surface_finding audit event failed for %s: %s", project, exc)

                    mm.save_project_memory(project, memory)
                except Exception as exc:
                    logger.warning("Agent surface audit failed for %s: %s", project, exc)
        except Exception as exc:
            logger.error("Agent surface audit failed: %s", exc, exc_info=True)
