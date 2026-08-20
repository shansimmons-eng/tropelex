"""
RepoSeek persistence — one JSON file per project at memory/reposeek/{project}.json.

Mirrors core/agent_skills.py's AgentSkillGraph pattern: a directory
auto-created in __init__, graceful missing-file defaults, no exceptions on
a project that's never scanned before.

Deliberately lowercases the project name in the filename -- a one-off
deviation from the rest of the codebase's inconsistent casing, taken to
avoid seeding a fifth copy of the case-split bug (memory/*.json,
memory/agent_skills/*.json) fixed twice already this session.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("reposeek.storage")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RepoSeekStore:
    """Batches and exclude list for RepoSeek, one file per project."""

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent.parent)
        self.base_path = Path(base_path)
        self.reposeek_dir = self.base_path / "memory" / "reposeek"
        self.reposeek_dir.mkdir(parents=True, exist_ok=True)

    def _file(self, project: str) -> Path:
        return self.reposeek_dir / f"{project.lower()}.json"

    def _load(self, project: str) -> dict[str, Any]:
        f = self._file(project)
        if f.exists():
            try:
                with open(f) as fh:
                    return json.load(fh)
            except json.JSONDecodeError as exc:
                logger.error("Corrupt reposeek file %s: %s", f, exc)
                return {"project": project, "batches": [], "excluded": [], "created": _now()}
            except OSError as exc:
                logger.error("Failed to read reposeek file %s: %s", f, exc)
                return {"project": project, "batches": [], "excluded": [], "created": _now()}
        return {"project": project, "batches": [], "excluded": [], "created": _now()}

    def _save(self, project: str, data: dict[str, Any]) -> None:
        try:
            with open(self._file(project), "w") as f:
                json.dump(data, f, indent=2)
        except (OSError, TypeError) as exc:
            logger.error("Failed to save reposeek data for %s: %s", project, exc)

    # ── Batches ──────────────────────────────────────────────────────────

    def new_batch_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def add_batch(self, project: str, batch: dict[str, Any]) -> None:
        data = self._load(project)
        data.setdefault("batches", []).append(batch)
        self._save(project, data)

    def get_batch(self, project: str, batch_id: str) -> dict[str, Any] | None:
        data = self._load(project)
        for b in data.get("batches", []):
            if b.get("id") == batch_id:
                return b
        return None

    def list_batches(self, project: str) -> list[dict[str, Any]]:
        return self._load(project).get("batches", [])

    def bump_item_scans_used(self, project: str, batch_id: str) -> None:
        """Increment a batch's item_scans_used counter in place. Caller is
        responsible for having already checked the width cap before this."""
        data = self._load(project)
        for b in data.get("batches", []):
            if b.get("id") == batch_id:
                b["item_scans_used"] = b.get("item_scans_used", 0) + 1
                break
        self._save(project, data)

    # ── Exclude list ─────────────────────────────────────────────────────

    def exclude_add(self, project: str, url: str, title: str) -> None:
        data = self._load(project)
        excluded = data.setdefault("excluded", [])
        if any(e.get("url") == url for e in excluded):
            return  # already excluded, no duplicate entry
        excluded.append({"url": url, "title": title, "excluded_at": _now()})
        self._save(project, data)

    def exclude_remove(self, project: str, url: str) -> bool:
        """Returns True if something was actually removed."""
        data = self._load(project)
        excluded = data.get("excluded", [])
        new_excluded = [e for e in excluded if e.get("url") != url]
        if len(new_excluded) == len(excluded):
            return False
        data["excluded"] = new_excluded
        self._save(project, data)
        return True

    def exclude_list(self, project: str) -> list[dict[str, Any]]:
        return self._load(project).get("excluded", [])

    def excluded_urls(self, project: str) -> set[str]:
        """Convenience: just the URL set, for filtering search results."""
        return {e.get("url") for e in self.exclude_list(project) if e.get("url")}
