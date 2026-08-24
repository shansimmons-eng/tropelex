"""
Safety metadata model and heuristic auto-classifier for decisions.

Moved out of core/tropebook/web/server.py (wishlist #73) — #54's own
writeup already named this as a deferred fast-follow ("core/safety/
created as its own module... not a relocation of the ~150-line inline
safety block still living in server.py"). Pure model + pure function, no
FastAPI/request coupling, so this is a straight relocation: server.py's
add_decision and preview_decision_category call auto_classify_safety the
same way _auto_classify_safety was called before, just imported instead
of defined locally.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SafetyMetadata(BaseModel):
    """Safety metadata for decisions, aligned with AI safety research priorities."""
    risk_level: str = Field(
        default="low",
        pattern="^(low|medium|high|critical)$",
        description="Risk level: low, medium, high, or critical"
    )
    reversibility: bool = Field(
        default=True,
        description="Whether this decision can be easily reversed"
    )
    affected_systems: list[str] = Field(
        default_factory=list,
        description="List of systems/components affected by this decision"
    )
    rationale_quality: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for the decision rationale (0.0-1.0)"
    )
    alignment_considerations: str = Field(
        default="",
        max_length=500,
        description="Notes on alignment/safety considerations"
    )
    requires_review: bool = Field(
        default=False,
        description="Whether this decision requires human review"
    )
    safety_category: str | None = Field(
        default=None,
        pattern="^(general|adversarial|robustness|monitoring|governance|alignment)$",
        description=(
            "Safety category for classification. No default on purpose — "
            "add_decision requires this to be an explicit choice, not a "
            "silently-assigned one. See core/triggers/tag_gate.py."
        ),
    )


def auto_classify_safety(decision: str, context: str) -> dict:
    """
    Auto-classify safety metadata for a decision based on content analysis.
    Uses keyword matching and heuristics to assign risk levels and categories.
    """
    decision_lower = decision.lower()
    context_lower = context.lower()
    combined = f"{decision_lower} {context_lower}"

    # Risk level classification
    risk_level = "low"
    requires_review = False

    # High-risk indicators
    high_risk_keywords = [
        "delete", "remove", "drop", "destroy", "purge", "wipe",
        "security", "auth", "permission", "access", "credential",
        "production", "live", "deploy", "release",
        "database", "schema", "migration", "backup",
        "api key", "secret", "token", "password",
    ]

    # Critical-risk indicators
    critical_risk_keywords = [
        "rm -rf", "drop table", "delete all", "purge all",
        "revoke access", "disable security", "bypass auth",
        "emergency", "hotfix", "rollback",
    ]

    # Medium-risk indicators
    medium_risk_keywords = [
        "change", "update", "modify", "refactor",
        "config", "settings", "environment",
        "dependency", "upgrade", "version",
    ]

    # Check for critical risks first
    if any(kw in combined for kw in critical_risk_keywords):
        risk_level = "critical"
        requires_review = True
    elif any(kw in combined for kw in high_risk_keywords):
        risk_level = "high"
        requires_review = True
    elif any(kw in combined for kw in medium_risk_keywords):
        risk_level = "medium"

    # Safety category classification
    safety_category = "general"

    category_keywords = {
        "adversarial": ["adversarial", "attack", "exploit", "vulnerability", "penetration", "red team"],
        "robustness": ["robust", "reliable", "fault tolerant", "resilient", "fail safe", "error handling"],
        "monitoring": ["monitor", "observe", "track", "log", "alert", "detect", "anomaly"],
        "governance": ["govern", "compliance", "audit", "policy", "standard", "regulation"],
        "alignment": ["alignment", "value", "ethical", "safety", "harm", "bias", "fairness"],
    }

    for category, keywords in category_keywords.items():
        if any(kw in combined for kw in keywords):
            safety_category = category
            break

    # Reversibility assessment
    reversible_indicators = ["add", "create", "enable", "extend", "augment"]
    irreversible_indicators = ["delete", "remove", "drop", "destroy", "migrate", "convert"]

    reversibility = True
    if any(kw in combined for kw in irreversible_indicators):
        reversibility = False
    elif any(kw in combined for kw in reversible_indicators):
        reversibility = True

    # Affected systems detection
    affected_systems = []
    system_keywords = {
        "memory": ["memory", "storage", "persistence", "database", "db"],
        "api": ["api", "endpoint", "route", "server", "http"],
        "auth": ["auth", "authentication", "authorization", "login", "session"],
        "ui": ["ui", "frontend", "dashboard", "interface", "display"],
        "security": ["security", "encryption", "hash", "token", "key"],
        "git": ["git", "commit", "branch", "merge", "repository"],
    }

    for system, keywords in system_keywords.items():
        if any(kw in combined for kw in keywords):
            affected_systems.append(system)

    return {
        "risk_level": risk_level,
        "reversibility": reversibility,
        "affected_systems": affected_systems,
        "rationale_quality": 0.5,  # Default, can be overridden
        "alignment_considerations": "",
        "requires_review": requires_review,
        "safety_category": safety_category,
    }
