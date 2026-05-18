"""
Tropelex Learner
Tracks patterns over time and evolves project memory.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from collections import defaultdict
import json

class PatternLearner:
    """
    Analyzes sessions and updates patterns in project memory.
    Looks for:
    - Recurring issues
    - User preferences
    - Common solutions
    - Tech stack evolution
    """

    def __init__(self, memory_manager):
        self.memory = memory_manager
        self.pattern_keywords = {
            'ui': ['css', 'tailwind', 'component', 'render', 'layout', 'mobile'],
            'backend': ['api', 'server', 'database', 'auth', 'endpoint'],
            'bug': ['fix', 'crash', 'error', 'break', 'issue'],
            'architecture': ['refactor', 'structure', 'pattern', 'design'],
            'performance': ['optimize', 'slow', 'cache', 'speed', 'memory']
        }

    def analyze_session(self, project_name: str, session_summary: str) -> Dict[str, Any]:
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
                key_insights.append(f"Session involved {category}: {', '.join(matches)}")
        
        updates = {
            'detected_categories': detected_categories,
            'key_insights': key_insights,
            'session_date': datetime.now(timezone.utc).isoformat()
        }
        
        return updates

    def update_project_from_session(self, project_name: str, session_data: Dict[str, Any]) -> None:
        """Update project memory based on session analysis."""
        project_memory = self.memory.get_project_memory(project_name)
        
        if 'patterns' not in project_memory:
            project_memory['patterns'] = []
        
        # Track categories worked on
        categories = session_data.get('detected_categories', [])
        for cat in categories:
            self._increment_pattern(project_memory, f'category:{cat}')
        
        # Track key insights
        insights = session_data.get('key_insights', [])
        if insights:
            project_memory['session_history'].append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'type': 'session_summary',
                'insights': insights
            })
        
        # Update tech stack from commits
        if 'tech_stack' in session_data:
            for tech in session_data['tech_stack']:
                if tech not in project_memory['tech_stack']:
                    project_memory['tech_stack'].append(tech)
        
        project_memory['last_updated'] = datetime.now(timezone.utc).isoformat()
        self.memory.save_project_memory(project_name, project_memory)

    def _increment_pattern(self, project_memory: Dict, pattern_key: str) -> None:
        """Increment a pattern counter."""
        patterns = project_memory['patterns']
        pattern_names = [p['name'] for p in patterns]
        
        if pattern_key in pattern_names:
            for p in patterns:
                if p['name'] == pattern_key:
                    p['count'] = p.get('count', 0) + 1
                    p['last_seen'] = datetime.now(timezone.utc).isoformat()
        else:
            patterns.append({
                'name': pattern_key,
                'count': 1,
                'first_seen': datetime.now(timezone.utc).isoformat(),
                'last_seen': datetime.now(timezone.utc).isoformat()
            })

    def get_common_patterns(self, project_name: str, limit: int = 5) -> List[Dict]:
        """Get most common patterns for a project."""
        project_memory = self.memory.get_project_memory(project_name)
        patterns = project_memory.get('patterns', [])
        sorted_patterns = sorted(patterns, key=lambda x: x.get('count', 0), reverse=True)
        return sorted_patterns[:limit]

    def suggest_next_steps(self, project_name: str) -> List[str]:
        """Analyze patterns and suggest likely next steps."""
        common = self.get_common_patterns(project_name, 3)
        suggestions = []
        
        for pattern in common:
            name = pattern['name']
            if name.startswith('category:ui'):
                suggestions.append("Continue UI development — this is a common focus area")
            elif name.startswith('category:backend'):
                suggestions.append("Backend work detected — consider API review")
            elif name.startswith('category:bug'):
                suggestions.append("Bug fixing pattern — ensure tests cover recent fixes")
            elif name.startswith('category:architecture'):
                suggestions.append("Architecture work — document decisions as they happen")
        
        return suggestions