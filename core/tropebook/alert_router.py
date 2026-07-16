"""
Feed Alerts API — configure and test feed notifications.

Mount into the main app:
    from core.tropebook.alert_router import alert_router
    app.include_router(alert_router)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.tropebook.alert_service import (
    format_slack_message,
    get_alert_webhook,
    send_slack_alert,
)

logger = logging.getLogger("tropelex.alerts_router")

alert_router = APIRouter(prefix="/api/alerts", tags=["alerts"])

_CORE_DIR = Path(__file__).parent.parent.parent
BASE_DIR = _CORE_DIR.parent
ALERTS_CONFIG_PATH = BASE_DIR / "memory" / "alerts_config.json"


class AlertConfig(BaseModel):
    slack_webhook_url: str | None = Field(None, description="Slack webhook URL")
    quiet_hours_start: int | None = Field(None, ge=0, le=23, description="Quiet hours start (UTC)")
    quiet_hours_end: int | None = Field(None, ge=0, le=23, description="Quiet hours end (UTC)")
    default_events: list[str] = Field(
        default=["run_complete", "error"],
        description="Events to alert on by default",
    )


def _load_config() -> dict[str, Any]:
    if ALERTS_CONFIG_PATH.exists():
        return json.loads(ALERTS_CONFIG_PATH.read_text())
    return {}


def _save_config(config: dict[str, Any]) -> None:
    ALERTS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_CONFIG_PATH.write_text(json.dumps(config, indent=2))


@alert_router.get("/config")
async def get_alert_config() -> dict[str, Any]:
    """Return current alert configuration."""
    config = _load_config()
    # Don't expose full webhook URL
    webhook = config.get("slack_webhook_url", "")
    return {
        "slack_configured": bool(webhook),
        "slack_webhook_preview": f"{webhook[:30]}..." if len(webhook) > 30 else webhook,
        "quiet_hours_start": config.get("quiet_hours_start"),
        "quiet_hours_end": config.get("quiet_hours_end"),
        "default_events": config.get("default_events", ["run_complete", "error"]),
    }


@alert_router.post("/config")
async def update_alert_config(req: AlertConfig) -> dict[str, Any]:
    """Update alert configuration."""
    config = _load_config()
    if req.slack_webhook_url is not None:
        config["slack_webhook_url"] = req.slack_webhook_url
    if req.quiet_hours_start is not None:
        config["quiet_hours_start"] = req.quiet_hours_start
    if req.quiet_hours_end is not None:
        config["quiet_hours_end"] = req.quiet_hours_end
    if req.default_events:
        config["default_events"] = req.default_events
    _save_config(config)
    return {"status": "updated"}


@alert_router.post("/test")
async def test_alert() -> dict[str, Any]:
    """Send a test alert to verify webhook configuration."""
    config = _load_config()
    webhook = config.get("slack_webhook_url") or get_alert_webhook()
    if not webhook:
        raise HTTPException(
            status_code=400,
            detail="No Slack webhook configured. Set SLACK_WEBHOOK_URL or configure via /api/alerts/config",
        )

    payload = format_slack_message(
        "Test Feed",
        "run_complete",
        {"citations_count": 42, "status": "success"},
    )
    success = await send_slack_alert(webhook, payload)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to send test alert")
    return {"status": "sent", "message": "Test alert delivered to Slack"}
