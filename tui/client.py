"""Thin async client for Tropelex's REST API, shared by the TUI screens."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

TROPELEX_URL = os.environ.get("TROPELEX_URL", "http://localhost:8766").rstrip("/")


class TropelexError(RuntimeError):
    """Raised when the Tropelex server is unreachable or returns an error."""


async def request(method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{TROPELEX_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method, url, json=json, headers={"X-Tropelex-Client": "tui"}
            )
    except httpx.ConnectError as exc:
        raise TropelexError(
            f"Could not reach Tropelex at {TROPELEX_URL} — is the server running? ({exc})"
        )
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise TropelexError(f"{resp.status_code} on {path}: {detail}")
    return resp.json()


async def list_projects() -> list[dict[str, Any]]:
    data = await request("GET", "/api/memory")
    return data.get("projects", [])


async def get_project_memory(project: str) -> dict[str, Any]:
    return await request("GET", f"/api/memory/{quote(project, safe='')}")


async def add_decision(project: str, decision: str, context: str = "") -> dict[str, Any]:
    return await request(
        "POST", f"/api/memory/{quote(project, safe='')}/decisions",
        json={"decision": decision, "context": context},
    )


async def get_contradictions(project: str) -> dict[str, Any]:
    return await request("GET", f"/api/memory/{quote(project, safe='')}/contradictions")


async def get_health(project: str) -> dict[str, Any]:
    return await request("GET", f"/api/memory/{quote(project, safe='')}/health")
