"""
Decision Impact Analysis — link decisions to outcomes, track reversals.

Pure functions that enrich decision data with relationship metadata,
reversal detection, and impact scoring.
"""

from typing import Any

from core.decision_tree import DecisionTree
from core.knowledge_decay import compute_inherited_discount, score_decisions


def compute_impact_analysis(memory: dict) -> dict[str, Any]:
    """Full impact report for a project's decisions.

    Returns:
        {
            linked_decisions: [...],
            reversals: [...],
            impact_scores: [...],
            summary: {total, reversal_rate, avg_impact},
        }
    """
    decisions = memory.get("decisions", [])
    if not decisions:
        return _empty_result()

    tree = DecisionTree.from_decisions(decisions)
    scored = score_decisions(decisions)
    linked = [_link_decision_metadata(d, tree) for d in decisions]
    reversals = _extract_reversals(decisions)
    impacts = _compute_impact_scores(decisions, tree, scored)
    summary = _compute_summary(decisions, reversals, impacts)

    return {
        "linked_decisions": linked,
        "reversals": reversals,
        "impact_scores": impacts,
        "summary": summary,
    }


def _extract_reversals(decisions: list[dict]) -> list[dict[str, Any]]:
    """Find decisions that supersede or revert other decisions."""
    reversals: list[dict[str, Any]] = []
    by_id: dict[str, dict] = {}
    for d in decisions:
        did = d.get("id") or d.get("timestamp", "")
        by_id[did] = d

    for d in decisions:
        did = d.get("id") or d.get("timestamp", "")
        edges = d.get("edges", [])
        for edge in edges:
            rel = edge.get("relationship", "")
            target = edge.get("target", "")
            if rel in ("supersedes", "reverts") and target in by_id:
                reversals.append({
                    "original_id": target,
                    "reversal_id": did,
                    "reversal_type": rel,
                    "original_decision": by_id[target].get("decision", "")[:80],
                    "reversal_decision": d.get("decision", "")[:80],
                })
        # Also check explicit reverts field
        reverts_id = d.get("reverts")
        if reverts_id and reverts_id in by_id:
            reversals.append({
                "original_id": reverts_id,
                "reversal_id": did,
                "reversal_type": "reverts",
                "original_decision": by_id[reverts_id].get("decision", "")[:80],
                "reversal_decision": d.get("decision", "")[:80],
            })
    return reversals


def _compute_impact_scores(
    decisions: list[dict], tree: DecisionTree, scored: list[dict]
) -> list[dict[str, Any]]:
    """Score each decision by its downstream impact."""
    score_map = {s.get("decision", ""): s for s in scored}
    # id-keyed (not text-keyed like score_map) so compute_inherited_discount
    # can look up an ancestor's own score by its node id (#58).
    score_by_id = {
        (d.get("id") or d.get("timestamp", "")): score_map.get(d.get("decision", ""), {}).get("score", 0.5)
        for d in decisions
    }
    impacts: list[dict[str, Any]] = []

    for d in decisions:
        did = d.get("id") or d.get("timestamp", "")
        # Count descendants (decisions caused by this one)
        descendants = tree.get_descendants(did, max_depth=3)
        # Count ancestors (what led to this decision)
        ancestors = tree.get_ancestors(did, max_depth=3)
        # Check if reversed
        is_reversed = any(
            e.get("relationship") in ("supersedes", "reverts")
            for e in d.get("edges", [])
        )

        conf = score_map.get(d.get("decision", ""), {})
        base_score = conf.get("score", 0.5)

        # #58: a decision's foundation decaying discounts its own effective
        # confidence -- "downstream decisions lose authority when their
        # foundation does". base_score keeps its existing meaning (own
        # decay only); effective_confidence is what actually feeds impact.
        inherited_discount = compute_inherited_discount(did, tree, score_by_id)
        effective_confidence = base_score * inherited_discount

        # Impact = confidence * (1 + downstream) * (penalty if reversed)
        downstream_bonus = min(len(descendants) * 0.1, 0.5)
        reversal_penalty = 0.5 if is_reversed else 1.0
        upstream_bonus = min(len(ancestors) * 0.05, 0.3)

        impact = (effective_confidence + downstream_bonus + upstream_bonus) * reversal_penalty
        impact = min(impact, 1.0)

        impacts.append({
            "decision_id": did,
            "decision": d.get("decision", "")[:80],
            "impact_score": round(impact, 3),
            "factors": {
                "confidence": round(base_score, 3),
                "inherited_discount": round(inherited_discount, 3),
                "downstream_count": len(descendants),
                "upstream_count": len(ancestors),
                "is_reversed": is_reversed,
            },
        })

    impacts.sort(key=lambda x: x["impact_score"], reverse=True)
    return impacts


def _link_decision_metadata(decision: dict, tree: DecisionTree) -> dict[str, Any]:
    """Enrich a single decision with its relationship graph info."""
    did = decision.get("id") or decision.get("timestamp", "")
    node = tree.nodes.get(did, {})
    edges = node.get("edges", decision.get("edges", []))

    related_ids = [e["target"] for e in edges if e.get("relationship") == "related_to"]
    caused_by = [e["target"] for e in edges if e.get("relationship") == "caused_by"]
    supersedes = [e["target"] for e in edges if e.get("relationship") == "supersedes"]

    return {
        "id": did,
        "decision": decision.get("decision", "")[:120],
        "timestamp": decision.get("timestamp", ""),
        "related_to": related_ids,
        "caused_by": caused_by,
        "supersedes": supersedes,
        "edge_count": len(edges),
    }


def _compute_summary(
    decisions: list[dict],
    reversals: list[dict],
    impacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Top-level summary stats."""
    total = len(decisions)
    reversal_rate = len(reversals) / total if total else 0
    avg_impact = (
        sum(i["impact_score"] for i in impacts) / len(impacts) if impacts else 0
    )
    return {
        "total_decisions": total,
        "reversal_count": len(reversals),
        "reversal_rate": round(reversal_rate, 3),
        "avg_impact_score": round(avg_impact, 3),
    }


def _empty_result() -> dict[str, Any]:
    """Return value when no decisions exist."""
    return {
        "linked_decisions": [],
        "reversals": [],
        "impact_scores": [],
        "summary": {
            "total_decisions": 0,
            "reversal_count": 0,
            "reversal_rate": 0,
            "avg_impact_score": 0,
        },
    }
