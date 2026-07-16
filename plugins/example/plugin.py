"""
Example plugin: git-auto-sync.

Demonstrates how to write a Tropelex plugin by registering hooks
against the plugin hook registry. This plugin logs session activity
and decision events — a real plugin would trigger git sync, send
notifications, etc.
"""

import logging

logger = logging.getLogger(__name__)


def register(registry) -> None:  # pragma: no cover — example code
    """Called by the plugin loader to wire this plugin into the hook registry.

    Args:
        registry: A ``HookRegistry`` instance from ``core.plugins.hooks``.
    """

    def _on_session_start(context: dict) -> dict:
        project = context.get("project_name", "unknown")
        logger.info("[example-plugin] Session started for project: %s", project)
        return context

    def _on_decision_recorded(context: dict) -> dict:
        decision = context.get("decision", "")
        project = context.get("project_name", "unknown")
        logger.info(
            "[example-plugin] Decision recorded for %s: %s",
            project,
            decision[:80],
        )
        return context

    registry.register("post_save", "after", _on_session_start)
    registry.register("post_save", "after", _on_decision_recorded)
    logger.info("[example-plugin] Registered hooks: post_save (after)")
