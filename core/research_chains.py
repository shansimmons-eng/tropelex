"""
Tropelex Research Chains
Multi-hop knowledge building: search → find gaps → search again → link → synthesize.

Mirrors how real research works by building chains of connected findings.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("tropelex.research_chains")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chain_id(steps: list[dict]) -> str:
    """Generate a deterministic ID for a research chain."""
    content = "|".join(s.get("query", "") for s in steps)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class ResearchChain:
    """
    Represents a multi-step research investigation.

    Each chain has:
    - id: unique identifier
    - goal: the research question
    - steps: list of {query, findings, gaps, timestamp}
    - links: connections found between findings
    - synthesis: final summary
    - status: active | completed | abandoned
    """

    def __init__(self, goal: str):
        self.goal = goal
        self.steps: list[dict[str, Any]] = []
        self.links: list[dict[str, str]] = []
        self.synthesis: str = ""
        self.status = "active"
        self.created_at = _now()
        self.updated_at = _now()

    def add_step(
        self,
        query: str,
        findings: list[dict],
        gaps: list[str] | None = None,
        source: str = "web_search",
    ) -> dict[str, Any]:
        """Add a research step with findings and identified gaps."""
        step = {
            "step_number": len(self.steps) + 1,
            "query": query,
            "findings": findings[:10],  # cap for storage
            "gaps": gaps or [],
            "source": source,
            "timestamp": _now(),
            "finding_count": len(findings),
        }
        self.steps.append(step)
        self.updated_at = _now()
        return step

    def add_link(self, from_finding: str, to_finding: str, relationship: str) -> None:
        """Record a connection between two findings."""
        self.links.append({
            "from": from_finding,
            "to": to_finding,
            "relationship": relationship,
            "timestamp": _now(),
        })
        self.updated_at = _now()

    def complete(self, synthesis: str) -> None:
        """Mark the chain as completed with a synthesis."""
        self.synthesis = synthesis
        self.status = "completed"
        self.updated_at = _now()

    def abandon(self, reason: str) -> None:
        """Mark the chain as abandoned."""
        self.synthesis = f"Abandoned: {reason}"
        self.status = "abandoned"
        self.updated_at = _now()

    def get_next_queries(self) -> list[str]:
        """Suggest next queries based on identified gaps."""
        queries = []
        for step in self.steps:
            for gap in step.get("gaps", []):
                if gap and len(gap) > 5:
                    queries.append(gap)
        return queries[-5:]  # last 5 gaps

    def get_all_findings(self) -> list[dict]:
        """Get all findings across all steps."""
        findings = []
        for step in self.steps:
            for f in step.get("findings", []):
                findings.append({**f, "step": step["step_number"]})
        return findings

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "goal": self.goal,
            "steps": self.steps,
            "links": self.links,
            "synthesis": self.synthesis,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "step_count": len(self.steps),
            "finding_count": sum(s.get("finding_count", 0) for s in self.steps),
            "link_count": len(self.links),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchChain":
        """Deserialize from dict."""
        chain = cls(data.get("goal", ""))
        chain.steps = data.get("steps", [])
        chain.links = data.get("links", [])
        chain.synthesis = data.get("synthesis", "")
        chain.status = data.get("status", "active")
        chain.created_at = data.get("created_at", _now())
        chain.updated_at = data.get("updated_at", _now())
        return chain


class ResearchChainManager:
    """
    Manages research chains for a project.
    Storage: memory/research_chains/{project}/
    """

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)
        self.chains_dir = self.base_path / "memory" / "research_chains"
        self.chains_dir.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_name: str) -> Path:
        d = self.chains_dir / project_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_chain(self, project_name: str, chain: ResearchChain) -> str:
        """Save a research chain and return its ID."""
        chain_id = _chain_id(chain.steps) if chain.steps else hashlib.sha256(
            chain.goal.encode()
        ).hexdigest()[:16]

        chain_file = self._project_dir(project_name) / f"{chain_id}.json"
        data = chain.to_dict()
        data["id"] = chain_id

        with open(chain_file, "w") as f:
            json.dump(data, f, indent=2)

        self._update_index(project_name, chain_id, data)
        return chain_id

    def _update_index(self, project_name: str, chain_id: str, data: dict) -> None:
        """Update project chain index."""
        index_file = self._project_dir(project_name) / "index.json"
        index = []
        if index_file.exists():
            with open(index_file) as f:
                index = json.load(f)

        # Update or add
        existing = [i for i, x in enumerate(index) if x.get("id") == chain_id]
        entry = {
            "id": chain_id,
            "goal": data.get("goal", ""),
            "status": data.get("status", "active"),
            "step_count": data.get("step_count", 0),
            "finding_count": data.get("finding_count", 0),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        }
        if existing:
            index[existing[0]] = entry
        else:
            index.append(entry)

        with open(index_file, "w") as f:
            json.dump(index, f, indent=2)

    def load_chain(self, project_name: str, chain_id: str) -> ResearchChain | None:
        """Load a research chain by ID."""
        chain_file = self._project_dir(project_name) / f"{chain_id}.json"
        if not chain_file.exists():
            return None
        with open(chain_file) as f:
            data = json.load(f)
        return ResearchChain.from_dict(data)

    def list_chains(self, project_name: str, status: str | None = None) -> list[dict]:
        """List chains for a project, optionally filtered by status."""
        index_file = self._project_dir(project_name) / "index.json"
        if not index_file.exists():
            return []
        with open(index_file) as f:
            index = json.load(f)
        if status:
            index = [c for c in index if c.get("status") == status]
        return index

    def delete_chain(self, project_name: str, chain_id: str) -> bool:
        """Delete a research chain."""
        chain_file = self._project_dir(project_name) / f"{chain_id}.json"
        if chain_file.exists():
            chain_file.unlink()
            index_file = self._project_dir(project_name) / "index.json"
            if index_file.exists():
                with open(index_file) as f:
                    index = json.load(f)
                index = [c for c in index if c.get("id") != chain_id]
                with open(index_file, "w") as f:
                    json.dump(index, f, indent=2)
            return True
        return False

    def auto_research(
        self, project_name: str, goal: str, max_steps: int = 3
    ) -> ResearchChain:
        """
        Run an automated research chain for a goal.
        This is the entry point for multi-hop research.

        Uses the tropebook research module for each step.
        """
        chain = ResearchChain(goal)

        # Step 1: Initial search
        initial_findings = self._search(goal)
        initial_gaps = self._identify_gaps(goal, initial_findings)
        chain.add_step(goal, initial_findings, gaps=initial_gaps)

        # Steps 2+: Follow gaps
        for i in range(max_steps - 1):
            next_queries = chain.get_next_queries()
            if not next_queries:
                break

            query = next_queries[0]
            findings = self._search(query)
            gaps = self._identify_gaps(query, findings)
            chain.add_step(query, findings, gaps=gaps)

            # Auto-link findings that share topics
            self._auto_link_findings(chain)

        # Generate synthesis
        all_findings = chain.get_all_findings()
        if all_findings:
            chain.complete(self._generate_synthesis(goal, all_findings))
        else:
            chain.abandon("No findings found")

        self.save_chain(project_name, chain)
        return chain

    def _search(self, query: str) -> list[dict]:
        """Search using available backends (tropebook, web, or local)."""
        # Try tropebook first (local knowledge)
        try:
            from core.tropebook import Tropebook

            tb = Tropebook(
                storage_path=str(self.base_path / "memory" / "tropebook")
            )
            results = tb.search(query, limit=5)
            if results:
                return [
                    {
                        "title": getattr(r, "title", str(r)),
                        "url": getattr(r, "url", ""),
                        "summary": getattr(r, "summary", "")[:200],
                        "source": "tropebook",
                    }
                    for r in results
                ]
        except Exception as e:
            logger.debug("Tropebook search failed: %s", e)

        # Return empty — the chain can still track gaps
        return []

    def _identify_gaps(self, query: str, findings: list[dict]) -> list[str]:
        """Identify knowledge gaps from findings."""
        gaps = []
        if not findings:
            gaps.append(f"Need more information about: {query}")
            return gaps

        # Check if findings cover the query topic
        query_words = set(query.lower().split())
        covered_words = set()
        for f in findings:
            title = f.get("title", "").lower()
            summary = f.get("summary", "").lower()
            covered_words.update(title.split())
            covered_words.update(summary.split())

        missing = query_words - covered_words - {"the", "a", "for", "in", "of", "to"}
        if missing:
            gaps.append(f"Deeper look at: {' '.join(missing)}")

        return gaps[:3]

    def _auto_link_findings(self, chain: ResearchChain) -> None:
        """Auto-link findings that share significant topics."""
        all_findings = chain.get_all_findings()
        for i, f1 in enumerate(all_findings):
            for f2 in all_findings[i+1:]:
                title1 = set(f1.get("title", "").lower().split())
                title2 = set(f2.get("title", "").lower().split())
                overlap = title1 & title2 - {"the", "a", "for", "in", "of", "to"}
                if len(overlap) >= 2:
                    chain.add_link(
                        f1.get("title", ""),
                        f2.get("title", ""),
                        f"shared: {', '.join(list(overlap)[:3])}",
                    )

    def _generate_synthesis(self, goal: str, findings: list[dict]) -> str:
        """Generate a synthesis from all findings."""
        titles = [f.get("title", "") for f in findings[:10]]
        summaries = [f.get("summary", "")[:200] for f in findings[:5]]

        lines = [f"Research synthesis for: {goal}", ""]
        lines.append(f"Based on {len(findings)} findings:")
        lines.append("")

        for i, title in enumerate(titles, 1):
            lines.append(f"{i}. {title}")

        if summaries:
            lines.append("")
            lines.append("Key findings:")
            for s in summaries:
                if s:
                    lines.append(f"- {s}")

        return "\n".join(lines)
