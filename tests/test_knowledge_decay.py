"""
Tests for Knowledge Decay & Confidence.
"""

from datetime import datetime, timezone, timedelta

from core.decision_tree import DecisionTree
from core.knowledge_decay import (
    REATTESTATION_PERIOD_DAYS,
    _days_since,
    _parse_timestamp,
    apply_decay_to_memory,
    compute_inherited_discount,
    decay_score,
    get_confidence_summary,
    get_stale_decisions,
    score_citation,
    score_decision,
    score_decisions,
    score_decisions_with_inheritance,
)


class TestParseTimestamp:
    def test_iso_format(self):
        dt = _parse_timestamp("2026-01-15T00:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_none(self):
        assert _parse_timestamp(None) is None

    def test_empty(self):
        assert _parse_timestamp("") is None

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-01-15T00:00:00Z")
        assert dt is not None


class TestDaysSince:
    def test_recent(self):
        dt = datetime.now(timezone.utc) - timedelta(days=5)
        assert abs(_days_since(dt) - 5) < 0.1

    def test_none(self):
        assert _days_since(None) == float("inf")

    def test_old(self):
        dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert _days_since(dt) > 1000


class TestDecayScore:
    def test_recent_high_score(self):
        now = datetime.now(timezone.utc).isoformat()
        result = decay_score(now)
        assert result["score"] > 0.9
        assert result["tier"] == "high"

    def test_old_low_score(self):
        old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        result = decay_score(old, half_life_days=90)
        assert result["score"] < 0.3
        assert result["tier"] in ("low", "stale")

    def test_reference_boost(self):
        # Use a slightly old timestamp so base score is below 1.0
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        no_refs = decay_score(old, reference_count=0)
        with_refs = decay_score(old, reference_count=5)
        assert with_refs["score"] > no_refs["score"]

    def test_contradiction_penalty(self):
        now = datetime.now(timezone.utc).isoformat()
        clean = decay_score(now, contradiction_count=0)
        contradicted = decay_score(now, contradiction_count=1)
        assert contradicted["score"] < clean["score"]

    def test_half_life(self):
        half = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        result = decay_score(half, half_life_days=90)
        assert 0.4 < result["score"] < 0.7

    def test_zero_age(self):
        now = datetime.now(timezone.utc).isoformat()
        result = decay_score(now, half_life_days=30)
        assert result["score"] > 0.95


class TestScoreDecision:
    def test_basic_score(self):
        decision = {
            "decision": "Use FastAPI for backend",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        result = score_decision(decision)
        assert "score" in result
        assert "tier" in result
        assert result["score"] > 0

    def test_with_references(self):
        now = datetime.now(timezone.utc).isoformat()
        decisions = [
            {"decision": "Use FastAPI for backend", "timestamp": now},
            {"decision": "Use FastAPI for auth", "timestamp": now},
            {"decision": "Use FastAPI middleware", "timestamp": now},
        ]
        result = score_decision(decisions[0], decisions)
        assert result["reference_count"] >= 1


class TestScoreDecisions:
    def test_sorted_by_confidence(self):
        now = datetime.now(timezone.utc)
        decisions = [
            {"decision": "Old decision about Python", "timestamp": (now - timedelta(days=365)).isoformat()},
            {"decision": "New decision about Python", "timestamp": now.isoformat()},
        ]
        scored = score_decisions(decisions)
        assert scored[0]["score"] >= scored[1]["score"]


class TestGetStaleDecisions:
    def test_finds_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        decisions = [
            {"decision": "Use Python 2.7 for compatibility", "timestamp": old},
        ]
        stale = get_stale_decisions(decisions, threshold=0.5, max_age_days=180)
        assert len(stale) == 1

    def test_fresh_not_stale(self):
        now = datetime.now(timezone.utc).isoformat()
        decisions = [
            {"decision": "Use Python 3.12 for performance", "timestamp": now},
        ]
        stale = get_stale_decisions(decisions, threshold=0.3)
        assert len(stale) == 0

    def test_non_dict_entries_are_skipped_not_raised(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        decisions = [
            {"decision": "Use Python 2.7 for compatibility", "timestamp": old},
            "corrupted",
            None,
            42,
        ]
        stale = get_stale_decisions(decisions, threshold=0.5, max_age_days=180)
        assert len(stale) == 1


class TestScoreCitation:
    def test_recent_citation(self):
        citation = {
            "title": "Python Docs",
            "url": "https://docs.python.org",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result = score_citation(citation)
        assert result["score"] > 0.8
        assert result["title"] == "Python Docs"


class TestGetConfidenceSummary:
    def test_with_decisions(self):
        now = datetime.now(timezone.utc).isoformat()
        memory = {
            "decisions": [
                {"decision": "Use Python", "timestamp": now},
                {"decision": "Use FastAPI", "timestamp": now},
            ],
        }
        summary = get_confidence_summary(memory)
        assert summary["total"] == 2
        assert summary["average_confidence"] > 0

    def test_empty_memory(self):
        summary = get_confidence_summary({"decisions": []})
        assert summary["total"] == 0
        assert summary["average_confidence"] == 0


class TestPinning:
    def test_pinned_recently_attested_is_high(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        recent_attestation = datetime.now(timezone.utc).isoformat()
        result = decay_score(old, pinned=True, last_attested=recent_attestation)
        assert result["score"] == 1.0
        assert result["tier"] == "high"
        assert result["factors"]["pinned"] is True
        assert "pin_expired" not in result["factors"]

    def test_pinned_but_never_attested_decays_normally(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        pinned_unattested = decay_score(old, pinned=True, last_attested=None, half_life_days=90)
        unpinned = decay_score(old, pinned=False, half_life_days=90)
        assert pinned_unattested["score"] == unpinned["score"]
        assert pinned_unattested["factors"]["pinned"] is True
        assert pinned_unattested["factors"]["pin_expired"] is True

    def test_pinned_attestation_lapsed_decays_normally(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        stale_attestation = (
            datetime.now(timezone.utc) - timedelta(days=REATTESTATION_PERIOD_DAYS + 10)
        ).isoformat()
        result = decay_score(old, pinned=True, last_attested=stale_attestation, half_life_days=90)
        assert result["factors"]["pin_expired"] is True
        assert result["score"] < 1.0

    def test_pinned_attestation_just_inside_window_stays_exempt(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        fresh_attestation = (
            datetime.now(timezone.utc) - timedelta(days=REATTESTATION_PERIOD_DAYS - 1)
        ).isoformat()
        result = decay_score(old, pinned=True, last_attested=fresh_attestation)
        assert result["score"] == 1.0
        assert result["tier"] == "high"

    def test_unpinned_unaffected(self):
        now = datetime.now(timezone.utc).isoformat()
        result = decay_score(now, pinned=False)
        assert "pinned" not in result["factors"]

    def test_score_decision_reads_pinned_fields_from_decision(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        decision = {
            "decision": "Never delete audit logs",
            "timestamp": old,
            "pinned": True,
            "last_attested": datetime.now(timezone.utc).isoformat(),
        }
        result = score_decision(decision)
        assert result["score"] == 1.0
        assert result["tier"] == "high"

    def test_score_decision_defaults_to_unpinned(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        decision = {"decision": "Some old call", "timestamp": old}
        result = score_decision(decision)
        assert result["score"] < 1.0


class TestComputeInheritedDiscount:
    def test_no_ancestors_returns_full_confidence(self):
        tree = DecisionTree()
        tree.nodes["a"] = {"id": "a", "edges": []}
        assert compute_inherited_discount("a", tree, {"a": 0.9}) == 1.0

    def test_decayed_ancestor_discounts_descendant(self):
        tree = DecisionTree()
        tree.nodes["foundation"] = {"id": "foundation", "edges": []}
        tree.nodes["built_on_it"] = {"id": "built_on_it", "edges": []}
        tree.edges.append({"source": "built_on_it", "target": "foundation", "relationship": "supersedes"})
        score_by_id = {"foundation": 0.1, "built_on_it": 0.9}
        discount = compute_inherited_discount("built_on_it", tree, score_by_id)
        assert discount == 0.5 + 0.5 * 0.1

    def test_floors_at_half_even_with_zero_ancestor_score(self):
        tree = DecisionTree()
        tree.nodes["foundation"] = {"id": "foundation", "edges": []}
        tree.nodes["child"] = {"id": "child", "edges": []}
        tree.edges.append({"source": "child", "target": "foundation", "relationship": "caused_by"})
        discount = compute_inherited_discount("child", tree, {"foundation": 0.0})
        assert discount == 0.5

    def test_unrelated_edge_direction_is_ignored(self):
        # Edge points AT "child" (child is the target, i.e. someone else's
        # ancestor) -- get_ancestors only walks edges sourced FROM child, so
        # this must not count as one of child's own ancestors.
        tree = DecisionTree()
        tree.nodes["child"] = {"id": "child", "edges": []}
        tree.nodes["descendant"] = {"id": "descendant", "edges": []}
        tree.edges.append({"source": "descendant", "target": "child", "relationship": "supersedes"})
        discount = compute_inherited_discount("child", tree, {"descendant": 0.0})
        assert discount == 1.0

    def test_missing_ancestor_score_defaults_to_neutral(self):
        tree = DecisionTree()
        tree.nodes["child"] = {"id": "child", "edges": []}
        tree.nodes["ghost_parent"] = {"id": "ghost_parent", "edges": []}
        tree.edges.append({"source": "child", "target": "ghost_parent", "relationship": "reverts"})
        # ghost_parent deliberately absent from score_by_id
        discount = compute_inherited_discount("child", tree, {})
        assert discount == 1.0

    def test_get_ancestors_raising_does_not_propagate(self):
        class BrokenTree:
            def get_ancestors(self, decision_id, max_depth=5):
                raise RuntimeError("boom")

        assert compute_inherited_discount("x", BrokenTree(), {}) == 1.0

    def test_malformed_ancestor_entries_do_not_raise(self):
        class WeirdTree:
            def get_ancestors(self, decision_id, max_depth=5):
                return ["not a dict", {"decision": "also not a dict"}, {"decision": {}}]

        assert compute_inherited_discount("x", WeirdTree(), {}) == 1.0


class TestScoreDecisionsWithInheritance:
    def test_empty_list(self):
        assert score_decisions_with_inheritance([]) == []

    def test_independent_decisions_have_no_discount(self):
        now = datetime.now(timezone.utc).isoformat()
        decisions = [
            {"id": "d1", "decision": "Use Postgres for storage", "timestamp": now},
            {"id": "d2", "decision": "Use React for frontend", "timestamp": now},
        ]
        results = score_decisions_with_inheritance(decisions)
        assert len(results) == 2
        assert all(r["inherited_discount"] == 1.0 for r in results)
        assert all(r["effective_score"] == r["score"] for r in results)

    def test_decayed_foundation_discounts_the_decision_built_on_it(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        foundation = {"id": "foundation1", "decision": "Use MongoDB for storage", "timestamp": old}
        reversal = {
            "id": "reversal1",
            "decision": "Use MongoDB for caching",
            "timestamp": now,
            "is_revert": True,
            "reverts": "foundation1",
        }
        results = score_decisions_with_inheritance([foundation, reversal])
        # score_decisions_with_inheritance sorts its output by effective_score,
        # so match results back to inputs by decision text (the only field
        # decay_score's result dict carries), not by zipping input order.
        by_text = {r["decision"]: r for r in results}
        reversal_result = by_text[reversal["decision"][:100]]
        assert reversal_result["inherited_discount"] < 1.0
        assert reversal_result["effective_score"] < reversal_result["score"]

    def test_sorted_by_effective_score_descending(self):
        now = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        decisions = [
            {"id": "old1", "decision": "Old unrelated call about caching", "timestamp": old},
            {"id": "new1", "decision": "New unrelated call about routing", "timestamp": now},
        ]
        results = score_decisions_with_inheritance(decisions)
        assert results[0]["effective_score"] >= results[1]["effective_score"]


class TestApplyDecayToMemory:
    def test_enriches_memory(self):
        now = datetime.now(timezone.utc).isoformat()
        memory = {
            "decisions": [
                {"decision": "Use Python for backend", "timestamp": now},
            ],
        }
        result = apply_decay_to_memory(memory)
        assert "confidence" in result["decisions"][0]
        assert "confidence_summary" in result
