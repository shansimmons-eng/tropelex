"""
Tropelex Session Replay
Tracks structured diffs of memory changes per session.
Allows querying "what changed?" and rolling back bad state.
"""

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_id(memory: dict) -> str:
    """Generate a deterministic hash of memory state."""
    content = json.dumps(memory, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _deep_diff(before: dict, after: dict, path: str = "") -> list[dict[str, Any]]:
    """
    Compute a structured diff between two memory states.
    Returns list of {path, type, before, after}.
    """
    changes = []

    all_keys = set(before.keys()) | set(after.keys())

    for key in sorted(all_keys):
        current_path = f"{path}.{key}" if path else key

        if key not in before:
            changes.append({
                "path": current_path,
                "type": "added",
                "after": _summarize_value(after[key]),
            })
        elif key not in after:
            changes.append({
                "path": current_path,
                "type": "removed",
                "before": _summarize_value(before[key]),
            })
        elif before[key] != after[key]:
            if isinstance(before[key], dict) and isinstance(after[key], dict):
                changes.extend(_deep_diff(before[key], after[key], current_path))
            elif isinstance(before[key], list) and isinstance(after[key], list):
                list_diff = _list_diff(before[key], after[key], current_path)
                changes.extend(list_diff)
            else:
                changes.append({
                    "path": current_path,
                    "type": "modified",
                    "before": _summarize_value(before[key]),
                    "after": _summarize_value(after[key]),
                })

    return changes


def _list_diff(before: list, after: list, path: str) -> list[dict]:
    """Diff two lists, detecting additions and removals."""
    changes = []

    # For simple lists of strings/numbers
    if all(isinstance(x, (str, int, float)) for x in before + after):
        added = set(after) - set(before)
        removed = set(before) - set(after)
        if added:
            changes.append({
                "path": path,
                "type": "items_added",
                "count": len(added),
                "items": list(added)[:5],
            })
        if removed:
            changes.append({
                "path": path,
                "type": "items_removed",
                "count": len(removed),
                "items": list(removed)[:5],
            })
    elif len(before) != len(after):
        changes.append({
            "path": path,
            "type": "list_length_changed",
            "before": len(before),
            "after": len(after),
        })
        # Detect new items at the end
        if len(after) > len(before):
            new_items = after[len(before):]
            changes.append({
                "path": path,
                "type": "items_appended",
                "count": len(new_items),
                "items": [_summarize_value(x) for x in new_items[:3]],
            })
    else:
        # Same length, check for item-level changes
        for i, (b, a) in enumerate(zip(before, after)):
            if b != a:
                if isinstance(b, dict) and isinstance(a, dict):
                    changes.extend(_deep_diff(b, a, f"{path}[{i}]"))
                else:
                    changes.append({
                        "path": f"{path}[{i}]",
                        "type": "modified",
                        "before": _summarize_value(b),
                        "after": _summarize_value(a),
                    })

    return changes


def _summarize_value(value: Any) -> Any:
    """Summarize a value for display in diffs."""
    if isinstance(value, str):
        return value[:200] if len(value) > 200 else value
    if isinstance(value, list):
        if len(value) > 5:
            return f"[{len(value)} items]"
        return value
    if isinstance(value, dict):
        return f"{{dict with {len(value)} keys}}"
    return value


class SessionReplay:
    """
    Tracks memory changes per session and allows querying/rollback.

    Storage: memory/replays/{project}/{session_id}.json
    Each session file contains:
    - session_id, timestamp
    - snapshot_before: memory state before session
    - snapshot_after: memory state after session
    - changes: structured diff
    - summary: human-readable summary
    """

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)
        self.replays_dir = self.base_path / "memory" / "replays"
        self.replays_dir.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_name: str) -> Path:
        d = self.replays_dir / project_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def record_session(
        self,
        project_name: str,
        memory_before: dict,
        memory_after: dict,
        summary: str = "",
        session_type: str = "manual",
    ) -> dict[str, Any]:
        """
        Record a session's memory changes.
        Returns the session record.
        """
        session_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_snapshot_id(memory_after)[:6]}"

        changes = _deep_diff(memory_before, memory_after)

        record = {
            "session_id": session_id,
            "project": project_name,
            "timestamp": _now(),
            "session_type": session_type,
            "summary": summary,
            "snapshot_id_before": _snapshot_id(memory_before),
            "snapshot_id_after": _snapshot_id(memory_after),
            "changes": changes,
            "change_count": len(changes),
            "snapshot_before": memory_before,
            "snapshot_after": memory_after,
        }

        # Save to disk
        session_file = self._project_dir(project_name) / f"{session_id}.json"
        with open(session_file, "w") as f:
            json.dump(record, f, indent=2, default=str)

        # Also maintain an index
        self._update_index(project_name, record)

        return {
            "session_id": session_id,
            "change_count": len(changes),
            "changes": changes,
        }

    def _update_index(self, project_name: str, record: dict) -> None:
        """Update the project's session index."""
        index_file = self._project_dir(project_name) / "index.json"
        index = []
        if index_file.exists():
            with open(index_file) as f:
                index = json.load(f)

        index.append({
            "session_id": record["session_id"],
            "timestamp": record["timestamp"],
            "session_type": record["session_type"],
            "summary": record["summary"],
            "change_count": record["change_count"],
        })

        # Keep last 100 sessions in index
        if len(index) > 100:
            index = index[-100:]

        with open(index_file, "w") as f:
            json.dump(index, f, indent=2)

    def get_sessions(
        self, project_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get recent sessions for a project."""
        index_file = self._project_dir(project_name) / "index.json"
        if not index_file.exists():
            return []
        with open(index_file) as f:
            index = json.load(f)
        return list(reversed(index[-limit:]))

    def get_session(self, project_name: str, session_id: str) -> dict[str, Any] | None:
        """Get full session record including snapshots."""
        session_file = self._project_dir(project_name) / f"{session_id}.json"
        if not session_file.exists():
            return None
        with open(session_file) as f:
            return json.load(f)

    def get_session_changes(
        self, project_name: str, session_id: str
    ) -> list[dict] | None:
        """Get just the changes for a session."""
        session = self.get_session(project_name, session_id)
        return session.get("changes") if session else None

    def get_changes_since(
        self, project_name: str, since_timestamp: str
    ) -> list[dict[str, Any]]:
        """Get all changes since a timestamp."""
        sessions = self.get_sessions(project_name, limit=100)
        result = []
        for s in sessions:
            if s["timestamp"] >= since_timestamp:
                full = self.get_session(project_name, s["session_id"])
                if full:
                    result.append({
                        "session_id": s["session_id"],
                        "timestamp": s["timestamp"],
                        "summary": s.get("summary", ""),
                        "changes": full.get("changes", []),
                    })
        return result

    def rollback_session(
        self, project_name: str, session_id: str, memory_manager
    ) -> dict[str, Any]:
        """
        Rollback a session by restoring the snapshot_before state.
        Returns the rollback result.
        """
        session = self.get_session(project_name, session_id)
        if not session:
            return {"rolled_back": False, "error": "Session not found"}

        snapshot_before = session.get("snapshot_before")
        if not snapshot_before:
            return {"rolled_back": False, "error": "No snapshot available for rollback"}

        # Record the rollback as a new session
        current_memory = memory_manager.get_project_memory(project_name)
        self.record_session(
            project_name,
            current_memory,
            snapshot_before,
            summary=f"Rollback of session {session_id}",
            session_type="rollback",
        )

        # Restore
        memory_manager.save_project_memory(project_name, snapshot_before)

        return {
            "rolled_back": True,
            "session_id": session_id,
            "restored_to": session["snapshot_id_before"],
        }

    def get_weekly_summary(self, project_name: str) -> dict[str, Any]:
        """Summarize what changed in the past week."""
        from datetime import timedelta

        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        changes = self.get_changes_since(project_name, week_ago)

        total_changes = sum(len(s.get("changes", [])) for s in changes)
        change_types: dict[str, int] = {}
        paths_changed: dict[str, int] = {}

        for session in changes:
            for change in session.get("changes", []):
                ct = change.get("type", "unknown")
                change_types[ct] = change_types.get(ct, 0) + 1
                path = change.get("path", "").split(".")[0]
                paths_changed[path] = paths_changed.get(path, 0) + 1

        return {
            "project": project_name,
            "period": "7 days",
            "sessions": len(changes),
            "total_changes": total_changes,
            "change_types": change_types,
            "top_areas": dict(sorted(paths_changed.items(), key=lambda x: -x[1])[:5]),
        }

    def cleanup(self, project_name: str, keep_last: int = 50) -> int:
        """Remove old session files, keeping the most recent N."""
        project_dir = self._project_dir(project_name)
        sessions = sorted(project_dir.glob("*.json"))
        sessions = [s for s in sessions if s.name != "index.json"]

        if len(sessions) <= keep_last:
            return 0

        to_remove = sessions[:-keep_last]
        for f in to_remove:
            f.unlink()

        return len(to_remove)
