"""
Tropelex OpenCode Adapter
Enables Tropelex memory system for OpenCode agent sessions.
"""
import sys
from pathlib import Path
from typing import Any

# Default Tropelex location
DEFAULT_TROPELEX_PATH = Path.home() / "Tropelex"


class TropelexAdapter:
    """
    Adapter for integrating Tropelex into OpenCode sessions.
    Usage:
        from adapters.opencode import TropelexAdapter
        adapter = TropelexAdapter()
        context = adapter.get_context_for_project("sovereign-mirror")
    """

    def __init__(self, tropelex_path: str | None = None):
        self.tropelex_path = Path(tropelex_path) if tropelex_path else DEFAULT_TROPELEX_PATH
        self.memory_manager = None
        self._init_memory()

    def _init_memory(self):
        """Lazy-load memory manager."""
        if self.tropelex_path.exists():
            # Add Tropelex root to sys.path once so core.* imports work
            tropelex_str = str(self.tropelex_path)
            if tropelex_str not in sys.path:
                sys.path.insert(0, tropelex_str)
            from core.memory.manager import MemoryManager

            self.memory_manager = MemoryManager(str(self.tropelex_path))

    def get_context_for_project(self, project_name: str) -> str:
        """
        Get Tropelex context for a project to inject into agent session.
        This is the primary method OpenCode will call.
        """
        if not self.memory_manager:
            return f"[Tropelex not initialized at {self.tropelex_path}]"
        return self.memory_manager.get_context_for_project(project_name)

    def inject_preferences(self, project_name: str, agent_preferences: dict[str, Any]) -> None:
        """
        Inject agent/user preferences for a project.
        Call this at start of session.
        """
        if not self.memory_manager:
            return
        for key, value in agent_preferences.items():
            self.memory_manager.set_preference(project_name, key, value)

    def record_decision(self, project_name: str, decision: str, context: str) -> None:
        """
        Record a key decision made during development.
        Call this when user makes an architectural choice.
        """
        if not self.memory_manager:
            return
        self.memory_manager.add_decision(project_name, decision, context)

    def summarize_session(self, project_name: str, session_text: str) -> None:
        """
        Summarize a session and update patterns.
        Call this at end of session.
        """
        if not self.memory_manager:
            return
        from core.learner.learner import PatternLearner

        learner = PatternLearner(self.memory_manager)
        analysis = learner.analyze_session(project_name, session_text)
        learner.update_project_from_session(project_name, analysis)

    def compress_context(self, content: str, max_tokens: int = 4000) -> str:
        """
        Compress context for prompt optimization.
        """
        from core.context_compressor.compressor import ContextCompressor

        compressor = ContextCompressor(max_tokens=max_tokens)
        result = compressor.compress(content)
        return result.content

    def list_projects(self) -> list:
        """List all projects in Tropelex memory."""
        if not self.memory_manager:
            return []
        return self.memory_manager.list_projects()

    def generate_session_prompt(self, project_name: str) -> str:
        """
        Generate the Tropelex context section for a new session.
        This is what gets injected into the agent's system prompt.
        """
        context = self.get_context_for_project(project_name)
        if not context:
            return ""
        return f"""
[TROPELEX MEMORY]
{context}
[END TROPELEX MEMORY]
"""
