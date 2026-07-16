"""
Feed Alert Service — deliver notifications for research feed events.

Supports Slack webhooks and configurable alert rules.
Pure functions for formatting; async delivery via httpx.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("tropelex.alerts")


def format_slack_message(feed_name: str, event: str, details: dict[str, Any]) -> dict:
    """Format a Slack webhook payload for a feed event.

    Args:
        feed_name: Display name of the feed.
        event: Event type — "run_complete", "new_citations", "error", "trend_alert".
        details: Event-specific payload.

    Returns:
        Slack webhook payload dict.
    """
    color_map = {
        "run_complete": "#98fa80",
        "new_citations": "#80d5fa",
        "error": "#ff6b6b",
        "trend_alert": "#a580fa",
    }
    color = color_map.get(event, "#8098fa")

    fields = []
    if "citations_count" in details:
        fields.append({"title": "Citations", "value": str(details["citations_count"]), "short": True})
    if "status" in details:
        fields.append({"title": "Status", "value": details["status"], "short": True})
    if "error" in details:
        fields.append({"title": "Error", "value": details["error"][:200], "short": False})
    if "trend" in details:
        fields.append({"title": "Trend", "value": details["trend"], "short": True})

    return {
        "attachments": [{
            "color": color,
            "title": f"Feed Alert: {feed_name}",
            "text": _event_text(event, feed_name, details),
            "fields": fields,
            "footer": "Tropelex Feed Alerts",
            "ts": int(datetime.now(timezone.utc).timestamp()),
        }],
    }


def _event_text(event: str, feed_name: str, details: dict) -> str:
    """Human-readable event description."""
    if event == "run_complete":
        count = details.get("citations_count", 0)
        return f"Feed '{feed_name}' completed with {count} citation(s)."
    if event == "new_citations":
        count = details.get("citations_count", 0)
        return f"Feed '{feed_name}' found {count} new citation(s)."
    if event == "error":
        return f"Feed '{feed_name}' encountered an error: {details.get('error', 'unknown')}"
    if event == "trend_alert":
        return f"Feed '{feed_name}' trend alert: {details.get('trend', 'unusual activity')}"
    return f"Feed '{feed_name}' event: {event}"


def should_alert(
    event: str,
    feed_config: dict[str, Any],
    quiet_hours: tuple[int, int] | None = None,
) -> bool:
    """Check if an alert should fire based on feed config and quiet hours.

    Args:
        event: Event type string.
        feed_config: Per-feed alert settings.
        quiet_hours: (start_hour, end_hour) in UTC — no alerts during this window.

    Returns:
        True if the alert should be delivered.
    """
    # Check if alerts are enabled for this feed
    if not feed_config.get("alerts_enabled", True):
        return False

    # Check event filter
    allowed_events = feed_config.get("alert_events", ["run_complete", "error"])
    if event not in allowed_events:
        return False

    # Check quiet hours
    if quiet_hours:
        now = datetime.now(timezone.utc).hour
        start, end = quiet_hours
        if start <= end:
            if start <= now < end:
                return False
        else:  # Wraps midnight
            if now >= start or now < end:
                return False

    return True


async def send_slack_alert(webhook_url: str, payload: dict) -> bool:
    """Send a Slack webhook notification.

    Returns True on success, False on failure.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200:
                logger.info("Slack alert sent successfully")
                return True
            logger.warning("Slack alert failed: %s %s", resp.status_code, resp.text[:100])
            return False
    except Exception as exc:
        logger.error("Slack alert error: %s", exc)
        return False


def get_alert_webhook() -> str | None:
    """Read Slack webhook URL from environment."""
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    return url if url else None
