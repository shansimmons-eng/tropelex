"""
Tests for core.safety's re-export index (#103) -- the single importable
place listing every safety-relevant pure function/class, per module. The
whole point of this index is that it stays accurate; these tests exist so
a future rename at a symbol's real source silently breaks a test instead
of silently going stale in the index nobody re-checks by hand.
"""

from __future__ import annotations

import core.safety as safety_index


class TestSafetyIndexCompleteness:
    def test_every_all_entry_is_actually_importable(self):
        missing = [name for name in safety_index.__all__ if not hasattr(safety_index, name)]
        assert missing == []

    def test_no_duplicate_names_in_all(self):
        assert len(safety_index.__all__) == len(set(safety_index.__all__))


class TestSafetyIndexIdentity:
    """Each re-exported symbol must be the exact same object as its real
    source -- a re-export index is worthless if it silently forked into a
    copy instead of pointing at the live implementation."""

    def test_ghost_symbols_match_source(self):
        from core.ghost.detector import GhostDecision, GhostReport, detect_ghost_decisions
        from core.ghost.preventive import GhostWarning, check_diff_for_warnings

        assert safety_index.detect_ghost_decisions is detect_ghost_decisions
        assert safety_index.GhostDecision is GhostDecision
        assert safety_index.GhostReport is GhostReport
        assert safety_index.check_diff_for_warnings is check_diff_for_warnings
        assert safety_index.GhostWarning is GhostWarning

    def test_contradictions_symbols_match_source(self):
        from core.contradictions import Contradiction, ContradictionReport
        from core.contradictions.detector import classify_contradiction, detect_contradictions

        assert safety_index.detect_contradictions is detect_contradictions
        assert safety_index.classify_contradiction is classify_contradiction
        assert safety_index.Contradiction is Contradiction
        assert safety_index.ContradictionReport is ContradictionReport

    def test_handoff_symbols_match_source(self):
        from core.handoff.packet_builder import (
            HandoffCompletenessFinding,
            HandoffPacket,
            build_handoff_packet,
        )

        assert safety_index.build_handoff_packet is build_handoff_packet
        assert safety_index.HandoffPacket is HandoffPacket
        assert safety_index.HandoffCompletenessFinding is HandoffCompletenessFinding

    def test_session_shape_symbols_match_source(self):
        from core.session_shape.baseline import classify_deviation, compute_baseline, record_session_shape

        assert safety_index.compute_baseline is compute_baseline
        assert safety_index.classify_deviation is classify_deviation
        assert safety_index.record_session_shape is record_session_shape

    def test_market_coordination_symbol_matches_source(self):
        from core.market.coordination import score_coordination_drift

        assert safety_index.score_coordination_drift is score_coordination_drift

    def test_safety_budget_symbol_matches_source(self):
        from core.safety_budget import compute_safety_budget

        assert safety_index.compute_safety_budget is compute_safety_budget

    def test_driftbench_symbols_match_source(self):
        from core.driftbench import CATEGORIES, Scenario, ScenarioResult
        from core.driftbench.report import run_suite
        from core.driftbench.scenarios import build_corpus

        assert safety_index.build_drift_bench_corpus is build_corpus
        assert safety_index.run_drift_bench_suite is run_suite
        assert safety_index.Scenario is Scenario
        assert safety_index.ScenarioResult is ScenarioResult
        assert safety_index.DRIFT_BENCH_CATEGORIES is CATEGORIES

    def test_gate_symbols_match_source(self):
        """core.gate (the generalized severity->action gate, #72/#101) --
        not to be confused with core.safety.gate (a different module,
        the required-safety-metadata check, #54), also re-exported here
        under non-colliding names."""
        from core.gate import DEFAULT_GATE_POLICY, GATE_ACTIONS, GATE_SEVERITIES, overridden_ids, policy_for

        assert safety_index.policy_for is policy_for
        assert safety_index.overridden_ids is overridden_ids
        assert safety_index.DEFAULT_GATE_POLICY is DEFAULT_GATE_POLICY
        assert safety_index.GATE_ACTIONS is GATE_ACTIONS
        assert safety_index.GATE_SEVERITIES is GATE_SEVERITIES

    def test_safety_metadata_symbols_match_source(self):
        from core.safety.classifier import SafetyMetadata, auto_classify_safety
        from core.safety.gate import SafetyMetadataRequiredError, require_safety_metadata

        assert safety_index.SafetyMetadata is SafetyMetadata
        assert safety_index.auto_classify_safety is auto_classify_safety
        assert safety_index.SafetyMetadataRequiredError is SafetyMetadataRequiredError
        assert safety_index.require_safety_metadata is require_safety_metadata
