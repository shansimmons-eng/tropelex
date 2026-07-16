"""
Tropelex Agent Skill Graph & Prompt Genealogy

Agent Skill Graph: Tracks what the agent has become proficient at per project.
Prompt Genealogy: Tracks which compressed prompts produced good outcomes.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("tropelex.agent_skills")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentSkillGraph:
    """
    Tracks agent proficiency per project.

    Skills are detected from session outcomes:
    - Did the user continue working (good) or rephrase (bad)?
    - What categories of work succeeded?
    - What compression strategies preserved meaning?

    Stored in memory/agent_skills/{project}.json
    """

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)
        self.skills_dir = self.base_path / "memory" / "agent_skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _skills_file(self, project_name: str) -> Path:
        return self.skills_dir / f"{project_name}.json"

    def _load(self, project_name: str) -> dict:
        f = self._skills_file(project_name)
        if f.exists():
            with open(f) as fh:
                return json.load(fh)
        return {"project": project_name, "skills": {}, "sessions": [], "created": _now()}

    def _save(self, project_name: str, data: dict) -> None:
        with open(self._skills_file(project_name), "w") as f:
            json.dump(data, f, indent=2)

    def record_session_outcome(
        self,
        project_name: str,
        session_type: str,
        categories: list[str],
        outcome: str = "success",
        details: str = "",
    ) -> None:
        """
        Record the outcome of a session to update skill scores.

        outcome: "success" (user continued), "partial" (some rephrasing),
                 "failure" (user gave up or rephrased completely)
        """
        data = self._load(project_name)

        # Update skill scores
        score_delta = {"success": 1, "partial": 0, "failure": -1}.get(outcome, 0)

        for cat in categories:
            skill = data["skills"].setdefault(cat, {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "score": 0.0,
                "first_seen": _now(),
                "last_seen": _now(),
            })
            skill["attempts"] += 1
            if outcome == "success":
                skill["successes"] += 1
            elif outcome == "failure":
                skill["failures"] += 1
            skill["score"] = skill["successes"] / max(skill["attempts"], 1)
            skill["last_seen"] = _now()

        # Record session
        data["sessions"].append({
            "timestamp": _now(),
            "type": session_type,
            "categories": categories,
            "outcome": outcome,
            "details": details[:200],
        })

        # Keep last 100 sessions
        if len(data["sessions"]) > 100:
            data["sessions"] = data["sessions"][-100:]

        self._save(project_name, data)

    def get_skills(self, project_name: str) -> list[dict]:
        """Get all skills for a project, sorted by score."""
        data = self._load(project_name)
        skills = []
        for name, info in data.get("skills", {}).items():
            skills.append({
                "skill": name,
                "score": round(info.get("score", 0), 3),
                "attempts": info.get("attempts", 0),
                "successes": info.get("successes", 0),
                "failures": info.get("failures", 0),
                "proficiency": _proficiency_label(info.get("score", 0)),
            })
        skills.sort(key=lambda x: x["score"], reverse=True)
        return skills

    def get_strengths(self, project_name: str, min_score: float = 0.7) -> list[str]:
        """Get skills where the agent is proficient."""
        skills = self.get_skills(project_name)
        return [s["skill"] for s in skills if s["score"] >= min_score and s["attempts"] >= 3]

    def get_weaknesses(self, project_name: str, max_score: float = 0.4) -> list[str]:
        """Get skills where the agent struggles."""
        skills = self.get_skills(project_name)
        return [s["skill"] for s in skills if s["score"] <= max_score and s["attempts"] >= 3]

    def get_briefing(self, project_name: str) -> str:
        """Generate a briefing of agent skills for context injection."""
        skills = self.get_skills(project_name)
        if not skills:
            return ""

        strengths = self.get_strengths(project_name)
        weaknesses = self.get_weaknesses(project_name)

        lines = ["## Agent Proficiency", ""]
        if strengths:
            lines.append(f"Strong at: {', '.join(strengths)}")
        if weaknesses:
            lines.append(f"Needs care: {', '.join(weaknesses)}")

        return "\n".join(lines)


def _proficiency_label(score: float) -> str:
    if score >= 0.9:
        return "expert"
    elif score >= 0.7:
        return "proficient"
    elif score >= 0.5:
        return "competent"
    elif score >= 0.3:
        return "learning"
    else:
        return "novice"


class PromptGenealogy:
    """
    Tracks which compressed prompts produced good outcomes.

    When the Agent Pipeline compresses a prompt, we record:
    - Original and compressed text
    - Compression strategy used
    - Whether the user continued (good) or rephrased (bad)

    Over time, learns which compression strategies preserve meaning.

    Stored in memory/prompt_genealogy/{project}.json
    """

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)
        self.genealogy_dir = self.base_path / "memory" / "prompt_genealogy"
        self.genealogy_dir.mkdir(parents=True, exist_ok=True)

    def _file(self, project_name: str) -> Path:
        return self.genealogy_dir / f"{project_name}.json"

    def _load(self, project_name: str) -> dict:
        f = self._file(project_name)
        if f.exists():
            with open(f) as fh:
                return json.load(fh)
        return {"project": project_name, "prompts": [], "strategy_scores": {}, "created": _now()}

    def _save(self, project_name: str, data: dict) -> None:
        with open(self._file(project_name), "w") as f:
            json.dump(data, f, indent=2)

    def record_compression(
        self,
        project_name: str,
        original: str,
        compressed: str,
        strategy: str = "default",
        compression_ratio: float = 0.0,
    ) -> str:
        """
        Record a prompt compression event.
        Returns a prompt_id for later outcome recording.
        """
        data = self._load(project_name)

        prompt_id = hashlib.sha256(
            f"{original[:100]}{compressed[:100]}{_now()}".encode()
        ).hexdigest()[:12]

        data["prompts"].append({
            "id": prompt_id,
            "original_length": len(original),
            "compressed_length": len(compressed),
            "compression_ratio": compression_ratio or (len(compressed) / max(len(original), 1)),
            "strategy": strategy,
            "timestamp": _now(),
            "outcome": None,
        })

        # Keep last 200
        if len(data["prompts"]) > 200:
            data["prompts"] = data["prompts"][-200:]

        self._save(project_name, data)
        return prompt_id

    def record_outcome(
        self,
        project_name: str,
        prompt_id: str,
        outcome: str,
    ) -> None:
        """
        Record the outcome of a compressed prompt.

        outcome: "good" (user continued normally),
                 "rephrased" (user had to rephrase),
                 "failed" (compression lost meaning)
        """
        data = self._load(project_name)

        for p in data["prompts"]:
            if p["id"] == prompt_id:
                p["outcome"] = outcome
                # Update strategy scores
                strategy = p["strategy"]
                scores = data["strategy_scores"].setdefault(strategy, {
                    "good": 0, "rephrased": 0, "failed": 0, "total": 0,
                })
                scores["total"] += 1
                scores[outcome] = scores.get(outcome, 0) + 1
                break

        self._save(project_name, data)

    def get_strategy_rankings(self, project_name: str) -> list[dict]:
        """Get compression strategies ranked by effectiveness."""
        data = self._load(project_name)
        rankings = []

        for strategy, scores in data.get("strategy_scores", {}).items():
            total = scores.get("total", 0)
            if total == 0:
                continue
            good = scores.get("good", 0)
            effectiveness = good / total
            rankings.append({
                "strategy": strategy,
                "effectiveness": round(effectiveness, 3),
                "total_uses": total,
                "good": good,
                "rephrased": scores.get("rephrased", 0),
                "failed": scores.get("failed", 0),
            })

        rankings.sort(key=lambda x: x["effectiveness"], reverse=True)
        return rankings

    def get_best_strategy(self, project_name: str) -> str | None:
        """Get the most effective compression strategy."""
        rankings = self.get_strategy_rankings(project_name)
        if rankings and rankings[0]["total_uses"] >= 3:
            return rankings[0]["strategy"]
        return None

    def get_stats(self, project_name: str) -> dict[str, Any]:
        """Get prompt genealogy statistics."""
        data = self._load(project_name)
        prompts = data.get("prompts", [])

        with_outcomes = [p for p in prompts if p.get("outcome")]
        if not with_outcomes:
            return {"total_prompts": len(prompts), "with_outcomes": 0}

        good = sum(1 for p in with_outcomes if p["outcome"] == "good")
        avg_ratio = sum(p.get("compression_ratio", 0) for p in prompts) / max(len(prompts), 1)

        return {
            "total_prompts": len(prompts),
            "with_outcomes": len(with_outcomes),
            "success_rate": round(good / len(with_outcomes), 3) if with_outcomes else 0,
            "avg_compression_ratio": round(avg_ratio, 3),
            "best_strategy": self.get_best_strategy(project_name),
            "strategies": self.get_strategy_rankings(project_name),
        }
