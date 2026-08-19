"""Pure-function scoring engine for RepoSeek results."""

from __future__ import annotations

import math
from dataclasses import replace

from core.reposeek.models import RepoResult

_STAR_REF = 100_000  # Reference point for log-scaled star normalization


def _language_score(repo_lang: str | None, profile_stack: list[str]) -> tuple[float, str | None]:
    """Exact match = 1.0, substring match = 0.5, none = 0.0."""
    if not repo_lang:
        return 0.0, None
    repo_lower = repo_lang.lower()
    for tech in profile_stack:
        if tech.lower() == repo_lower:
            return 1.0, tech
        if repo_lower in tech.lower() or tech.lower() in repo_lower:
            return 0.5, tech
    return 0.0, None


def _topic_score(repo_title: str, repo_desc: str, profile_stack: list[str]) -> float:
    """Jaccard similarity between repo-derived tokens and profile tech_stack."""
    tokens = set(repo_title.lower().split() + repo_desc.lower().split())
    stack = {t.lower() for t in profile_stack}
    if not tokens and not stack:
        return 0.0
    return len(tokens & stack) / len(tokens | stack)


def _star_score(stars: int) -> float:
    """Log-scaled normalization against a 100K reference."""
    return math.log1p(stars) / math.log1p(_STAR_REF)


def _description_score(repo_desc: str, profile_desc: str) -> float:
    """Word-overlap (Jaccard) between profile description and repo description."""
    a = set(repo_desc.lower().split())
    b = set(profile_desc.lower().split())
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_results(results: list[RepoResult], profile: dict) -> list[RepoResult]:
    """Score and rank results by similarity to the user profile.

    Args:
        results: Raw search results to score.
        profile: Keys — tech_stack (list[str]), description (str), patterns (list[str]).

    Returns:
        New list of RepoResult sorted by similarity_score descending (pure, no mutation).
    """
    stack = profile.get("tech_stack", [])
    desc = profile.get("description", "")

    scored: list[RepoResult] = []
    for r in results:
        lang_s, matched_tech = _language_score(r.language, stack)
        topic_s = _topic_score(r.title, r.description, stack)
        star_s = _star_score(r.stars)
        desc_s = _description_score(r.description, desc)

        score = 0.3 * lang_s + 0.3 * topic_s + 0.2 * star_s + 0.2 * desc_s

        reasons: list[str] = []
        if lang_s > 0 and matched_tech:
            reasons.append(f"language:{matched_tech.lower()}")
        if star_s > 0.01:
            reasons.append(f"stars:{r.stars}")
        if desc_s > 0.05:
            reasons.append("description_match")

        scored.append(replace(r, similarity_score=round(score, 4), match_reasons=reasons))

    return sorted(scored, key=lambda x: x.similarity_score, reverse=True)
