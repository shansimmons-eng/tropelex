"""
Trending persistence — a single global JSON file at
memory/trending/snapshots.json (not one-per-project like RepoSeek: trending
isn't about any one Tropelex project).

Snapshots are keyed by f"{language or ''}::{sorted topics}::{window}" so
repeat scans under the same filter combination can be diffed against their
own history. Mirrors core/reposeek/storage.py's graceful-missing-file /
auto-mkdir pattern.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("trending.storage")

_MAX_SNAPSHOTS_PER_KEY = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_key(language: str | None, topics: list[str], window: str) -> str:
    """Build the storage key a given (language, topics, window) filter maps to."""
    topics_part = ",".join(sorted(t.lower() for t in topics))
    return f"{(language or '').lower()}::{topics_part}::{window}"


class TrendingStore:
    """Global snapshot history and exclude list for the Trending tool."""

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent.parent)
        self.base_path = Path(base_path)
        self.trending_dir = self.base_path / "memory" / "trending"
        self.trending_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.trending_dir / "snapshots.json"

    def _load(self) -> dict[str, Any]:
        if self.file.exists():
            try:
                with open(self.file) as fh:
                    return json.load(fh)
            except json.JSONDecodeError as exc:
                logger.error("Corrupt trending file %s: %s", self.file, exc)
                return {"snapshots": {}, "excluded": []}
            except OSError as exc:
                logger.error("Failed to read trending file %s: %s", self.file, exc)
                return {"snapshots": {}, "excluded": []}
        return {"snapshots": {}, "excluded": []}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            with open(self.file, "w") as f:
                json.dump(data, f, indent=2)
        except (OSError, TypeError) as exc:
            logger.error("Failed to save trending data: %s", exc)

    # ── Snapshots ────────────────────────────────────────────────────────

    def new_snapshot_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def add_snapshot(self, key: str, snapshot: dict[str, Any]) -> None:
        """Append a snapshot under key, trimming to the most recent
        _MAX_SNAPSHOTS_PER_KEY entries."""
        data = self._load()
        snapshots = data.setdefault("snapshots", {})
        history = snapshots.setdefault(key, [])
        history.append(snapshot)
        if len(history) > _MAX_SNAPSHOTS_PER_KEY:
            snapshots[key] = history[-_MAX_SNAPSHOTS_PER_KEY:]
        self._save(data)

    def last_snapshot(self, key: str) -> dict[str, Any] | None:
        """Most recent snapshot stored under key, or None if this is the
        first pull for this filter combination."""
        data = self._load()
        history = data.get("snapshots", {}).get(key, [])
        return history[-1] if history else None

    def list_snapshots(self, key: str) -> list[dict[str, Any]]:
        return self._load().get("snapshots", {}).get(key, [])

    # ── Exclude list ─────────────────────────────────────────────────────

    def exclude_add(self, url: str, title: str) -> None:
        data = self._load()
        excluded = data.setdefault("excluded", [])
        if any(e.get("url") == url for e in excluded):
            return  # already excluded, no duplicate entry
        excluded.append({"url": url, "title": title, "excluded_at": _now()})
        self._save(data)

    def exclude_remove(self, url: str) -> bool:
        """Returns True if something was actually removed."""
        data = self._load()
        excluded = data.get("excluded", [])
        new_excluded = [e for e in excluded if e.get("url") != url]
        if len(new_excluded) == len(excluded):
            return False
        data["excluded"] = new_excluded
        self._save(data)
        return True

    def exclude_list(self) -> list[dict[str, Any]]:
        return self._load().get("excluded", [])

    def excluded_urls(self) -> set[str]:
        """Convenience: just the URL set, for filtering search results."""
        return {e.get("url") for e in self.exclude_list() if e.get("url")}
