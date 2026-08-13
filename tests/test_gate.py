"""Tests for core.gate -- the generalized severity gate (#72), extracted
from core.ghost.preventive_router's original _policy_for/
_overridden_decision_ids so any detector can reuse it under its own
namespaced storage key.
"""

from __future__ import annotations

from core.gate import DEFAULT_GATE_POLICY, GATE_ACTIONS, GATE_SEVERITIES, overridden_ids, policy_for


class TestPolicyFor:
    def test_missing_key_uses_defaults(self):
        assert policy_for({}, "high") == "block"
        assert policy_for({}, "medium") == "warn"
        assert policy_for({}, "low") == "log_only"

    def test_stored_value_not_a_dict_falls_back_to_defaults(self):
        for malformed in (["high", "block"], "block", 42, None):
            assert policy_for({"gate_policy": malformed}, "high") == "block"

    def test_unrecognized_action_value_falls_back_to_default(self):
        memory = {"gate_policy": {"high": "block_everything_always"}}
        assert policy_for(memory, "high") == "block"

    def test_valid_override_is_honored(self):
        memory = {"gate_policy": {"high": "log_only"}}
        assert policy_for(memory, "high") == "log_only"
        assert policy_for(memory, "medium") == "warn"  # unset tier keeps default

    def test_default_key_is_gate_policy(self):
        """Backward-compat: the original _policy_for always read
        memory["gate_policy"] -- the default key must match exactly, or
        every existing Ghost gate_policy override silently stops applying."""
        memory = {"gate_policy": {"high": "warn"}}
        assert policy_for(memory, "high") == "warn"

    def test_custom_key_isolates_from_default_gate_policy(self):
        """A detector using its own namespaced key must not read or be
        affected by another detector's gate_policy dict -- the whole point
        of the key parameter (#72's docstring: two detectors gating
        different things shouldn't silently share override state)."""
        memory = {"gate_policy": {"high": "warn"}, "contradiction_gate_policy": {"high": "log_only"}}
        assert policy_for(memory, "high", key="gate_policy") == "warn"
        assert policy_for(memory, "high", key="contradiction_gate_policy") == "log_only"

    def test_custom_key_missing_uses_defaults(self):
        assert policy_for({}, "high", key="contradiction_gate_policy") == "block"

    def test_unknown_severity_falls_back_to_log_only(self):
        assert policy_for({}, "nonsense_severity") == "log_only"


class TestOverriddenIds:
    def test_no_overrides_returns_empty_set(self):
        assert overridden_ids({}) == set()

    def test_overrides_not_a_list_returns_empty_set(self):
        for malformed in ({"decision_id": "d1"}, "d1", 42, None):
            assert overridden_ids({"overrides": malformed}) == set()

    def test_extracts_decision_ids_from_valid_overrides(self):
        memory = {"overrides": [
            {"decision_id": "d1", "rationale": "x"},
            {"decision_id": "d2", "rationale": "y"},
        ]}
        assert overridden_ids(memory) == {"d1", "d2"}

    def test_malformed_entries_skipped_not_crashed(self):
        memory = {"overrides": [
            {"decision_id": "d1"},
            "not a dict",
            {"no_decision_id": True},
            None,
            42,
        ]}
        assert overridden_ids(memory) == {"d1"}

    def test_default_key_is_overrides(self):
        """Backward-compat: the original _overridden_decision_ids always
        read memory["overrides"] -- must match exactly."""
        memory = {"overrides": [{"decision_id": "d1"}]}
        assert overridden_ids(memory) == {"d1"}

    def test_custom_key_reads_a_different_list(self):
        memory = {"overrides": [{"decision_id": "ghost-1"}], "other_overrides": [{"decision_id": "other-1"}]}
        assert overridden_ids(memory, key="other_overrides") == {"other-1"}


class TestModuleConstants:
    def test_default_gate_policy_shape(self):
        assert DEFAULT_GATE_POLICY == {"high": "block", "medium": "warn", "low": "log_only"}

    def test_gate_actions_shape(self):
        assert GATE_ACTIONS == {"block", "warn", "log_only"}

    def test_gate_severities_order(self):
        assert GATE_SEVERITIES == ("high", "medium", "low")
