"""
Tropelex Memory Manager
Handles reading/writing project knowledge files and session memory.

File-level locking (fcntl.flock) prevents concurrent corruption when
multiple agents write to the same project memory simultaneously.
"""

import fcntl
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("tropelex.memory")

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _read_lock(path: Path):
    """Acquire a shared (read) lock on a file."""
    fh = path.open("r")
    try:
        fcntl.flock(fh, fcntl.LOCK_SH)
        yield fh
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


@contextmanager
def _write_lock(path: Path):
    """Acquire an exclusive (write) lock on a file.

    Creates the file if it doesn't exist so the lock can be acquired.
    """
    fh = path.open("a+")  # create if missing, position at end
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        yield fh
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


class MemoryManager:
    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent.parent)
        self.base_path = Path(base_path)
        self.memory_dir = self.base_path / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, project_name: str) -> Path:
        """Resolve path and guard against directory traversal."""
        name = Path(project_name).name
        if not name or not _SAFE_NAME.match(name):
            raise ValueError(f"Invalid project name: {project_name!r}")
        return self.memory_dir / f"{name}.json"

    def get_project_memory(self, project_name: str) -> dict[str, Any]:
        memory_file = self._safe_path(project_name)
        if memory_file.exists():
            try:
                with _read_lock(memory_file) as fh:
                    return json.load(fh)
            except json.JSONDecodeError as exc:
                logger.error("Corrupt memory file %s: %s", memory_file, exc)
                raise
            except OSError as exc:
                logger.error("Failed to read %s: %s", memory_file, exc)
                raise
        return self._create_empty_project_memory(project_name)

    def save_project_memory(self, project_name: str, memory: dict[str, Any]) -> None:
        memory_file = self._safe_path(project_name)
        try:
            with _write_lock(memory_file) as fh:
                fh.seek(0)
                fh.truncate()
                json.dump(memory, fh, indent=2)
        except (OSError, TypeError) as exc:
            logger.error("Failed to save %s: %s", memory_file, exc)
            raise

    def update_project_memory(self, project_name: str, key: str, value: Any) -> None:
        memory = self.get_project_memory(project_name)
        memory[key] = value
        memory["last_updated"] = _now()
        self.save_project_memory(project_name, memory)

    def append_to_history(self, project_name: str, entry: dict[str, Any]) -> None:
        memory = self.get_project_memory(project_name)
        memory.setdefault("session_history", []).append({"timestamp": _now(), **entry})
        memory["last_updated"] = _now()
        self.save_project_memory(project_name, memory)

    def add_decision(self, project_name: str, decision: str, context: str) -> None:
        memory = self.get_project_memory(project_name)
        memory.setdefault("decisions", []).append(
            {"timestamp": _now(), "decision": decision, "context": context}
        )
        memory["last_updated"] = _now()
        self.save_project_memory(project_name, memory)

    def get_preference(self, project_name: str, key: str, default: Any = None) -> Any:
        memory = self.get_project_memory(project_name)
        return memory.get("preferences", {}).get(key, default)

    def set_preference(self, project_name: str, key: str, value: Any) -> None:
        memory = self.get_project_memory(project_name)
        memory.setdefault("preferences", {})[key] = value
        memory["last_updated"] = _now()
        self.save_project_memory(project_name, memory)

    def get_context_for_project(self, project_name: str) -> str:
        memory = self.get_project_memory(project_name)
        lines = [f"## {project_name} Memory\n"]
        lines.append(f"- Last updated: {memory.get('last_updated', 'never')}\n")

        if memory.get("description"):
            lines.append(f"- Description: {memory['description']}\n")

        if memory.get("preferences"):
            lines.append("\n### User Preferences")
            for k, v in memory["preferences"].items():
                lines.append(f"- {k}: {v}\n")

        if memory.get("decisions"):
            lines.append("\n### Key Decisions")
            for d in memory["decisions"][-5:]:
                ts = str(d.get("timestamp", ""))[:10]
                dec = d.get("decision", "")
                lines.append(f"- [{ts}] {dec}\n")

        if memory.get("tech_stack"):
            lines.append("\n### Tech Stack\n")
            for tech in memory["tech_stack"]:
                lines.append(f"- {tech}\n")

        if memory.get("session_history"):
            lines.append("\n### Recent Sessions\n")
            for s in memory["session_history"][-3:]:
                ts = str(s.get("timestamp", ""))[:10]
                insights = s.get("insights", [])
                if insights:
                    lines.append(f"- [{ts}] {'; '.join(insights[:2])}\n")

        return "".join(lines)

    def list_projects(self) -> list[str]:
        """List projects, excluding the tropebook subdirectory files."""
        return [f.stem for f in self.memory_dir.glob("*.json") if f.is_file()]

    def _create_empty_project_memory(self, project_name: str) -> dict[str, Any]:
        return {
            "project_name": project_name,
            "created": _now(),
            "last_updated": _now(),
            "description": "",
            "decisions": [],
            "session_history": [],
            "preferences": {},
            "patterns": [],
            "tech_stack": [],
            "context": {},
        }
