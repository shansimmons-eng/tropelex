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

    def get_context_for_project(self, project_name: str, role: str = "CoderAgent") -> str:
        """
        Get Tropelex context for a project to inject into agent session.
        Uses handoff packets for role-aware, budget-optimized context.
        Falls back to naive dump if handoff builder is unavailable.
        """
        if not self.memory_manager:
            return f"[Tropelex not initialized at {self.tropelex_path}]"

        try:
            from core.handoff.packet_builder import build_handoff_packet
            memory = self.memory_manager.get_project_memory(project_name)
            packet = build_handoff_packet(project_name, role, memory)
            return self._format_handoff_packet(packet)
        except Exception:
            # Fallback to naive context dump
            return self.memory_manager.get_context_for_project(project_name)

    def _format_handoff_packet(self, packet) -> str:
        """Format a HandoffPacket into a readable context string."""
        lines = [f"## {packet.project} Memory (role: {packet.role})\n"]

        if packet.skills_summary:
            lines.append("### Agent Skills")
            for cat, level in packet.skills_summary.items():
                lines.append(f"- {cat}: {level}")
            lines.append("")

        if packet.context_slices:
            lines.append("### Context")
            for slice in packet.context_slices:
                lines.append(f"- {slice.content}")
            lines.append("")

        if packet.recent_sessions:
            lines.append("### Recent Sessions")
            for s in packet.recent_sessions:
                ts = str(s.get("timestamp", ""))[:10]
                summary = s.get("summary", s.get("insights", [""])[0] if s.get("insights") else "")
                lines.append(f"- [{ts}] {summary}")
            lines.append("")

        lines.append(f"*Generated: {packet.generated_at} | Tokens: {packet.token_count}/{packet.token_budget}*")
        return "\n".join(lines)

    def get_cross_project_briefing(self, project_name: str) -> str:
        """
        Get transferable knowledge from similar projects.
        Inject into session context for cross-project learning.
        """
        if not self.memory_manager:
            return ""
        try:
            from core.rag import CrossPollinator
            pollinator = CrossPollinator(self.memory_manager)
            return pollinator.get_project_briefing(project_name)
        except Exception:
            return ""

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
        Also runs friction mining to detect implicit signals.
        Call this at end of session.
        """
        if not self.memory_manager:
            return
        from core.learner.learner import PatternLearner

        learner = PatternLearner(self.memory_manager)
        analysis = learner.analyze_session(project_name, session_text)
        learner.update_project_from_session(project_name, analysis)

        # Run friction mining on the session transcript
        self._mine_friction(project_name, session_text)

    def _mine_friction(self, project_name: str, transcript: str) -> None:
        """Run friction mining on a transcript and persist results."""
        try:
            from core.friction.miner import (
                detect_friction_signals,
                compute_friction_score,
                group_signals_by_zone,
            )
            result = detect_friction_signals(transcript)
            if hasattr(result, "error"):
                return
            signals = result.value
            if not signals:
                return
            score = compute_friction_score(signals)
            zones = group_signals_by_zone(signals)

            # Persist friction history into project memory
            def _mutate(memory):
                friction = memory.setdefault("friction_history", [])
                friction.append({
                    "timestamp": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                    "score": score,
                    "signal_count": len(signals),
                    "zone_count": len(zones),
                    "high_severity_count": sum(
                        1 for s in signals if s.severity == "high"
                    ),
                })
                # Keep last 50 entries
                if len(friction) > 50:
                    memory["friction_history"] = friction[-50:]

            self.memory_manager._modify_project_memory(project_name, _mutate)
        except Exception:
            pass  # Friction mining is best-effort

    def compress_context(self, content: str, max_tokens: int = 4000) -> str:
        """
        Compress context for prompt optimization.
        """
        import importlib.util
        compressor_path = self.tropelex_path / "core" / "context-compressor" / "compressor.py"
        spec = importlib.util.spec_from_file_location("context_compressor", compressor_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        compressor = mod.ContextCompressor(max_tokens=max_tokens)
        result = compressor.compress(content)
        return result.content

    def list_projects(self) -> list:
        """List all projects in Tropelex memory."""
        if not self.memory_manager:
            return []
        return self.memory_manager.list_projects()

    def generate_session_prompt(self, project_name: str, role: str = "CoderAgent") -> str:
        """
        Generate the Tropelex context section for a new session.
        Uses handoff packets for role-aware context + cross-project briefing.
        This is what gets injected into the agent's system prompt.
        """
        context = self.get_context_for_project(project_name, role=role)
        briefing = self.get_cross_project_briefing(project_name)

        parts = []
        if context:
            parts.append(f"[TROPELEX MEMORY]\n{context}")
        if briefing:
            parts.append(f"[CROSS-PROJECT BRIEFING]\n{briefing}")

        if not parts:
            return ""
        return "\n\n".join(parts) + "\n[END TROPELEX MEMORY]"
