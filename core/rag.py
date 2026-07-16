"""
Tropelex Memory-Driven RAG & Cross-Pollination

RAG: Semantic retrieval from project memory + tropebook at query time.
Cross-Pollination: Surface solutions from similar projects.

Instead of injecting full context, retrieve relevant snippets when queried.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("tropelex.rag")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _keyword_match_score(query: str, text: str) -> float:
    """Simple keyword overlap score (0.0 to 1.0)."""
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
        "has", "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "can", "to", "of", "in", "for", "on", "with", "at",
        "by", "from", "as", "and", "but", "or", "not", "so", "if", "then",
        "that", "this", "it", "its", "we", "our", "i", "my", "you", "your",
    }
    query_words = {w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]+", query)} - stop
    text_words = {w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]+", text)} - stop

    if not query_words:
        return 0.0

    overlap = query_words & text_words
    return len(overlap) / len(query_words)


class MemoryRAG:
    """
    Retrieves relevant memory snippets for a query.
    Combines keyword matching with optional semantic search.
    """

    def __init__(self, memory_manager, embed_store=None):
        self.memory = memory_manager
        self.embed_store = embed_store

    def retrieve(
        self,
        project_name: str,
        query: str,
        top_k: int = 5,
        include_decisions: bool = True,
        include_sessions: bool = True,
        include_tropebook: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant memory snippets for a query.
        Returns sorted list of {text, source, score, metadata}.
        """
        results = []

        memory = self.memory.get_project_memory(project_name)

        # Search decisions
        if include_decisions:
            for d in memory.get("decisions", []):
                text = d.get("decision", "")
                context = d.get("context", "")
                full_text = f"{text} {context}"
                score = _keyword_match_score(query, full_text)
                if score > 0.1:
                    results.append({
                        "text": text,
                        "source": "decision",
                        "score": score,
                        "metadata": {
                            "timestamp": d.get("timestamp", ""),
                            "context": context,
                            "confidence": d.get("confidence", {}).get("score"),
                        },
                    })

        # Search session history
        if include_sessions:
            for s in memory.get("session_history", []):
                insights = s.get("insights", [])
                summary = s.get("summary", "")
                full_text = " ".join(insights) + " " + summary
                score = _keyword_match_score(query, full_text)
                if score > 0.1:
                    results.append({
                        "text": full_text[:200],
                        "source": "session",
                        "score": score,
                        "metadata": {
                            "timestamp": s.get("timestamp", ""),
                            "day": s.get("day"),
                        },
                    })

        # Search quick captures
        for qc in memory.get("quick_captures", []):
            text = qc.get("text", "")
            score = _keyword_match_score(query, text)
            if score > 0.1:
                results.append({
                    "text": text,
                    "source": "capture",
                    "score": score,
                    "metadata": {"type": qc.get("type", "thought")},
                })

        # Sort by score, return top_k
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def retrieve_with_context(
        self, project_name: str, query: str, top_k: int = 5
    ) -> str:
        """
        Retrieve and format as context string for injection into prompts.
        """
        results = self.retrieve(project_name, query, top_k)

        if not results:
            return ""

        lines = [f"## Relevant Memory for: {query}", ""]
        for r in results:
            source = r["source"]
            text = r["text"]
            score = r["score"]
            lines.append(f"- [{source} score={score:.2f}] {text}")

        return "\n".join(lines)


class CrossPollinator:
    """
    Surfaces solutions from similar projects.
    When working on Project A, finds relevant patterns/decisions
    from Projects B, C that have similar tech stacks.
    """

    def __init__(self, memory_manager):
        self.memory = memory_manager

    def find_transferable_knowledge(
        self,
        project_name: str,
        query: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Find knowledge from other projects that might be relevant.
        Returns list of {project, decision, relevance_reason, score}.
        """
        current = self.memory.get_project_memory(project_name)
        current_tech = set(t.lower() for t in current.get("tech_stack", []))
        current_decisions = current.get("decisions", [])

        # Extract keywords from current context
        context_words = set()
        if query:
            context_words = set(re.findall(r"[a-z][a-z0-9]+", query.lower()))

        for d in current_decisions[-10:]:
            context_words.update(re.findall(r"[a-z][a-z0-9]+", d.get("decision", "").lower()))

        all_projects = self.memory.list_projects()
        transferable = []

        for other_name in all_projects:
            if other_name == project_name:
                continue

            other = self.memory.get_project_memory(other_name)
            other_tech = set(t.lower() for t in other.get("tech_stack", []))

            # Tech overlap score
            tech_overlap = current_tech & other_tech
            if not tech_overlap:
                continue

            # Find relevant decisions from other project
            for d in other.get("decisions", []):
                decision_text = d.get("decision", "")
                decision_words = set(re.findall(r"[a-z][a-z0-9]+", decision_text.lower()))

                # Score based on keyword overlap with current context
                word_overlap = decision_words & context_words
                if word_overlap:
                    score = len(word_overlap) / max(len(context_words), 1)
                    transferable.append({
                        "project": other_name,
                        "decision": decision_text,
                        "context": d.get("context", ""),
                        "shared_tech": list(tech_overlap),
                        "shared_keywords": list(word_overlap)[:5],
                        "relevance_score": round(score, 3),
                        "relevance_reason": f"Similar project ({', '.join(list(tech_overlap)[:3])}) solved: {decision_text[:80]}",
                    })

        # Sort by relevance
        transferable.sort(key=lambda x: x["relevance_score"], reverse=True)
        return transferable[:limit]

    def get_project_briefing(
        self, project_name: str, query: str | None = None
    ) -> str:
        """
        Generate a briefing of transferable knowledge for a project.
        Suitable for injection into agent context.
        """
        transfers = self.find_transferable_knowledge(project_name, query)

        if not transfers:
            return ""

        lines = [
            "## Cross-Project Knowledge",
            "",
            "Similar projects have solved related problems:",
            "",
        ]

        for t in transfers:
            lines.append(f"- **{t['project']}**: {t['relevance_reason']}")
            if t.get("context"):
                lines.append(f"  Context: {t['context'][:100]}")

        return "\n".join(lines)

    def suggest_approaches(
        self, project_name: str, problem_description: str
    ) -> list[dict[str, Any]]:
        """
        Given a problem description, find approaches used by similar projects.
        """
        transfers = self.find_transferable_knowledge(project_name, problem_description)

        # Group by approach (deduplicate similar decisions)
        seen = set()
        approaches = []
        for t in transfers:
            decision = t["decision"].lower()
            # Simple dedup by first 50 chars
            key = decision[:50]
            if key not in seen:
                seen.add(key)
                approaches.append({
                    "approach": t["decision"],
                    "from_project": t["project"],
                    "reason": t["relevance_reason"],
                    "confidence": t["relevance_score"],
                })

        return approaches[:5]
