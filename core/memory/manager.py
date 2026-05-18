"""
Tropelex Memory Manager
Handles reading/writing project knowledge files and session memory.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

class MemoryManager:
    def __init__(self, base_path: Optional[str] = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent.parent)
        self.base_path = Path(base_path)
        self.memory_dir = self.base_path / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def get_project_memory(self, project_name: str) -> Dict[str, Any]:
        """Load memory for a specific project."""
        memory_file = self.memory_dir / f"{project_name}.json"
        if memory_file.exists():
            with open(memory_file, 'r') as f:
                return json.load(f)
        return self._create_empty_project_memory(project_name)

    def save_project_memory(self, project_name: str, memory: Dict[str, Any]) -> None:
        """Save memory for a specific project."""
        memory_file = self.memory_dir / f"{project_name}.json"
        with open(memory_file, 'w') as f:
            json.dump(memory, f, indent=2)

    def update_project_memory(self, project_name: str, key: str, value: Any) -> None:
        """Update a specific key in project memory."""
        memory = self.get_project_memory(project_name)
        memory[key] = value
        memory['last_updated'] = datetime.now(timezone.utc).isoformat()
        self.save_project_memory(project_name, memory)

    def append_to_history(self, project_name: str, entry: Dict[str, Any]) -> None:
        """Append an entry to session history."""
        memory = self.get_project_memory(project_name)
        if 'session_history' not in memory:
            memory['session_history'] = []
        memory['session_history'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            **entry
        })
        memory['last_updated'] = datetime.now(timezone.utc).isoformat()
        self.save_project_memory(project_name, memory)

    def add_decision(self, project_name: str, decision: str, context: str) -> None:
        """Record a key decision made during development."""
        memory = self.get_project_memory(project_name)
        if 'decisions' not in memory:
            memory['decisions'] = []
        memory['decisions'].append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'decision': decision,
            'context': context
        })
        memory['last_updated'] = datetime.now(timezone.utc).isoformat()
        self.save_project_memory(project_name, memory)

    def get_preference(self, project_name: str, key: str, default: Any = None) -> Any:
        """Get a user preference for a project."""
        memory = self.get_project_memory(project_name)
        return memory.get('preferences', {}).get(key, default)

    def set_preference(self, project_name: str, key: str, value: Any) -> None:
        """Set a user preference for a project."""
        memory = self.get_project_memory(project_name)
        if 'preferences' not in memory:
            memory['preferences'] = {}
        memory['preferences'][key] = value
        self.save_project_memory(project_name, memory)

    def get_context_for_project(self, project_name: str) -> str:
        """Generate a context string for injecting into agent sessions."""
        memory = self.get_project_memory(project_name)
        lines = [f"## {project_name} Memory\n"]
        lines.append(f"- Last updated: {memory.get('last_updated', 'never')}\n")

        if memory.get('description'):
            lines.append(f"- Description: {memory['description']}\n")

        if memory.get('preferences'):
            lines.append("\n### User Preferences")
            for k, v in memory['preferences'].items():
                lines.append(f"- {k}: {v}\n")

        if memory.get('decisions'):
            lines.append("\n### Key Decisions")
            for d in memory['decisions'][-5:]:
                ts = str(d.get('timestamp', ''))[:10]
                dec = d.get('decision', '')
                lines.append(f"- [{ts}] {dec}\n")

        if memory.get('tech_stack'):
            lines.append(f"\n### Tech Stack\n")
            for tech in memory['tech_stack']:
                lines.append(f"- {tech}\n")

        return "".join(lines)

    def list_projects(self) -> list:
        """List all projects in memory."""
        return [f.stem for f in self.memory_dir.glob("*.json")]

    def _create_empty_project_memory(self, project_name: str) -> Dict[str, Any]:
        return {
            'project_name': project_name,
            'created': datetime.now(timezone.utc).isoformat(),
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'description': '',
            'decisions': [],
            'session_history': [],
            'preferences': {},
            'patterns': [],
            'tech_stack': [],
            'context': {}
        }