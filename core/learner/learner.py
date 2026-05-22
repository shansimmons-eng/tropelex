"""
Tropelex Learner
Tracks patterns over time and evolves project memory.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict
import json
import re


class PatternLearner:
    """
    Analyzes sessions and updates patterns in project memory.
    Looks for:
    - Recurring issues
    - User preferences
    - Common solutions
    - Tech stack evolution
    - Time-based patterns (best days, peak hours)
    - Cross-project similarities
    """

    def __init__(self, memory_manager):
        self.memory = memory_manager
        self.pattern_keywords = {
            "ui": [
                "css",
                "tailwind",
                "component",
                "render",
                "layout",
                "mobile",
                "html",
                "style",
            ],
            "backend": [
                "api",
                "server",
                "database",
                "auth",
                "endpoint",
                "route",
                "model",
            ],
            "bug": [
                "fix",
                "crash",
                "error",
                "break",
                "issue",
                "debug",
                "null",
                "undefined",
            ],
            "architecture": ["refactor", "structure", "pattern", "design", "abstract"],
            "performance": ["optimize", "slow", "cache", "speed", "memory", "load"],
            "security": [
                "auth",
                "token",
                "encrypt",
                "sanitize",
                "validate",
                "permission",
            ],
        }

    def analyze_session(
        self, project_name: str, session_summary: str
    ) -> Dict[str, Any]:
        """
        Analyze a session summary and extract patterns.
        Returns pattern updates to apply to memory.
        """
        summary_lower = session_summary.lower()
        detected_categories = []
        key_insights = []

        for category, keywords in self.pattern_keywords.items():
            matches = [kw for kw in keywords if kw in summary_lower]
            if matches:
                detected_categories.append(category)
                key_insights.append(
                    f"Session involved {category}: {', '.join(matches)}"
                )

        # Time-based analysis
        now = datetime.now(timezone.utc)
        day_of_week = now.strftime("%A").lower()  # monday, tuesday, etc.

        updates = {
            "detected_categories": detected_categories,
            "key_insights": key_insights,
            "session_date": now.isoformat(),
            "day_of_week": day_of_week,
        }

        return updates

    def update_project_from_session(
        self, project_name: str, session_data: Dict[str, Any]
    ) -> None:
        """Update project memory based on session analysis."""
        project_memory = self.memory.get_project_memory(project_name)

        if "patterns" not in project_memory:
            project_memory["patterns"] = []

        # Track categories worked on
        categories = session_data.get("detected_categories", [])
        for cat in categories:
            self._increment_pattern(project_memory, f"category:{cat}")

        # Track day-of-week patterns
        day = session_data.get("day_of_week")
        if day:
            self._increment_pattern(project_memory, f"day:{day}")

        # Track key insights
        insights = session_data.get("key_insights", [])
        if insights:
            project_memory["session_history"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "session_summary",
                    "insights": insights,
                    "day": day,
                }
            )

        # Update tech stack from commits
        if "tech_stack" in session_data:
            for tech in session_data["tech_stack"]:
                if tech not in project_memory["tech_stack"]:
                    project_memory["tech_stack"].append(tech)

        project_memory["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.memory.save_project_memory(project_name, project_memory)

    def _increment_pattern(self, project_memory: Dict, pattern_key: str) -> None:
        """Increment a pattern counter."""
        patterns = project_memory["patterns"]
        pattern_names = [p["name"] for p in patterns]

        if pattern_key in pattern_names:
            for p in patterns:
                if p["name"] == pattern_key:
                    p["count"] = p.get("count", 0) + 1
                    p["last_seen"] = datetime.now(timezone.utc).isoformat()
        else:
            patterns.append(
                {
                    "name": pattern_key,
                    "count": 1,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }
            )

    def get_common_patterns(self, project_name: str, limit: int = 5) -> List[Dict]:
        """Get most common patterns for a project."""
        project_memory = self.memory.get_project_memory(project_name)
        patterns = project_memory.get("patterns", [])
        sorted_patterns = sorted(
            patterns, key=lambda x: x.get("count", 0), reverse=True
        )
        return sorted_patterns[:limit]

    def suggest_next_steps(self, project_name: str) -> List[str]:
        """Analyze patterns and suggest likely next steps."""
        common = self.get_common_patterns(project_name, 3)
        suggestions = []

        for pattern in common:
            name = pattern["name"]
            if name.startswith("category:ui"):
                suggestions.append(
                    "Continue UI development — this is a common focus area"
                )
            elif name.startswith("category:backend"):
                suggestions.append("Backend work detected — consider API review")
            elif name.startswith("category:bug"):
                suggestions.append(
                    "Bug fixing pattern — ensure tests cover recent fixes"
                )
            elif name.startswith("category:architecture"):
                suggestions.append(
                    "Architecture work — document decisions as they happen"
                )

        return suggestions

    def detect_decisions(self, text: str) -> List[Dict[str, str]]:
        """
        Analyze text to detect potential decisions that should be recorded.
        Returns list of detected decisions with context.
        """
        decision_patterns = [
            (
                r"(?:decided|choosing|going with|using|selected)\s+(?:to\s+)?(.+?)(?:\.|$)",
                "decision",
            ),
            (
                r"(?:created|built|implemented)\s+(?:a\s+)?(.+?)\s+(?:instead of|because|rather than)(?:\s+)(.+?)(?:\.|$)",
                "comparison",
            ),
            (
                r"(?:because|since|given that)\s+(.+?),\s+(?:we|I)\s+(?:decided|chose|went with)",
                "rationale",
            ),
            (r"the\s+best\s+approach\s+is\s+(.+?)(?:\.|$)", "recommendation"),
            (r"(?:will|should)\s+use\s+(.+?)(?:\.|$)", "intent"),
            (r"opted\s+for\s+(.+?)(?:\.|$)", "selection"),
        ]

        detected = []
        for pattern, decision_type in decision_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    content = " ".join(match)
                else:
                    content = match
                if len(content) > 10 and len(content) < 500:
                    detected.append(
                        {
                            "type": decision_type,
                            "content": content.strip(),
                            "confidence": "high"
                            if decision_type in ["decision", "comparison"]
                            else "medium",
                        }
                    )

        return detected[:5]

    def get_similar_projects(
        self, project_name: str, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Find projects with similar tech stacks or patterns.
        Returns list of similar projects with match reasons.
        """
        current = self.memory.get_project_memory(project_name)
        current_tech = set(t.lower() for t in current.get("tech_stack", []))
        current_categories = set(
            p["name"]
            for p in current.get("patterns", [])
            if p["name"].startswith("category:")
        )

        all_projects = self.memory.list_projects()
        similarities = []

        for other_name in all_projects:
            if other_name == project_name:
                continue

            other = self.memory.get_project_memory(other_name)
            other_tech = set(t.lower() for t in other.get("tech_stack", []))
            other_categories = set(
                p["name"]
                for p in other.get("patterns", [])
                if p["name"].startswith("category:")
            )

            tech_overlap = current_tech & other_tech
            category_overlap = current_categories & other_categories

            if tech_overlap or category_overlap:
                score = len(tech_overlap) * 2 + len(category_overlap)
                similarities.append(
                    {
                        "project": other_name,
                        "match_score": score,
                        "shared_tech": list(tech_overlap),
                        "shared_categories": list(category_overlap),
                        "description": other.get("description", ""),
                    }
                )

        similarities.sort(key=lambda x: x["match_score"], reverse=True)
        return similarities[:limit]
