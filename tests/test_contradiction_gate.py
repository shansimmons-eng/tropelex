"""Tests for add_decision's contradiction gate (#72) -- Generalized
Soft-Enforcement + Override-as-Decision, wired into Contradiction
Detection. Closes #53's own disclosed deferral ("Contradiction Detection
isn't gated yet, Ghost Preventive Check only").

Uses the real app/MemoryManager (add_decision lives inline in
core.tropebook.web.server, not a standalone router), same pattern as
tests/test_safety_features.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_contra_gate_{uuid.uuid4().hex[:8]}"


def _create(client, project, decision, **extra):
    body = {"decision": decision, "context": "", "safety_metadata": {"safety_category": "general"}, **extra}
    return client.post(f"/api/memory/{project}/decisions", json=body)


class TestContradictionGateBlocking:
    def test_high_severity_contradiction_blocks_by_default(self, client, project):
        first = _create(client, project, "Use React for frontend")
        assert first.status_code == 200

        second = _create(client, project, "Use Vue for frontend")
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert detail["blocking_contradictions"][0]["conflicting_decision_id"] == first.json()["decision"]["id"]
        assert detail["blocking_contradictions"][0]["contradiction_type"] == "direct"

    def test_blocked_decision_is_not_persisted(self, client, project):
        _create(client, project, "Use React for frontend")
        _create(client, project, "Use Vue for frontend")

        decisions = client.get(f"/api/memory/{project}").json()["decisions"]
        texts = [d["decision"] for d in decisions]
        assert "Use React for frontend" in texts
        assert "Use Vue for frontend" not in texts

    def test_unrelated_decision_not_blocked(self, client, project):
        first = _create(client, project, "Use React for frontend")
        assert first.status_code == 200
        second = _create(client, project, "Adopt pytest for the test suite")
        assert second.status_code == 200

    def test_gate_blocked_audit_event_recorded(self, client, project):
        _create(client, project, "Use React for frontend")
        _create(client, project, "Use Vue for frontend")

        memory = client.get(f"/api/memory/{project}").json()
        audit_types = [e["event_type"] for e in memory.get("audit_log", [])]
        assert "gate_blocked" in audit_types


class TestContradictionGateOverride:
    def test_override_then_retry_succeeds(self, client, project):
        first = _create(client, project, "Use React for frontend")
        first_id = first.json()["decision"]["id"]

        blocked = _create(client, project, "Use Vue for frontend")
        assert blocked.status_code == 409

        override_resp = client.post(
            f"/api/memory/{project}/decisions/{first_id}/override",
            json={"rationale": "Migrating incrementally, both coexist temporarily", "agent_name": "claude"},
        )
        assert override_resp.status_code == 200

        retried = _create(client, project, "Use Vue for frontend")
        assert retried.status_code == 200

    def test_override_is_shared_with_ghost_mechanism(self, client, project):
        """The override endpoint (#53) is generic -- accepting the risk on
        an existing decision applies regardless of which detector raised
        it, not a separate Contradictions-only override list."""
        first = _create(client, project, "Use React for frontend")
        first_id = first.json()["decision"]["id"]
        client.post(
            f"/api/memory/{project}/decisions/{first_id}/override",
            json={"rationale": "x", "agent_name": "claude"},
        )
        memory = client.get(f"/api/memory/{project}").json()
        assert memory.get("overrides", [{}])[0]["decision_id"] == first_id


class TestContradictionGatePolicy:
    def test_detector_selector_isolates_from_ghost_gate_policy(self, client, project):
        first = _create(client, project, "Use React for frontend")
        assert first.status_code == 200
        put_resp = client.put(f"/api/memory/{project}/gate-policy?detector=ghost", json={"high": "log_only"})
        assert put_resp.status_code == 200

        # Ghost's gate_policy loosened, but contradiction_gate_policy is
        # untouched -- still defaults to block.
        second = _create(client, project, "Use Vue for frontend")
        assert second.status_code == 409

    def test_warn_policy_lets_decision_through_with_audit_trace(self, client, project):
        first = _create(client, project, "Use React for frontend")
        assert first.status_code == 200
        put_resp = client.put(f"/api/memory/{project}/gate-policy?detector=contradictions", json={"high": "warn"})
        assert put_resp.status_code == 200
        second = _create(client, project, "Use Vue for frontend")
        assert second.status_code == 200

        memory = client.get(f"/api/memory/{project}").json()
        audit_types = [e["event_type"] for e in memory.get("audit_log", [])]
        assert "gate_warned" in audit_types
        assert "gate_blocked" not in audit_types

    def test_log_only_policy_lets_decision_through_no_audit_trace(self, client, project):
        _create(client, project, "Use React for frontend")
        put_resp = client.put(f"/api/memory/{project}/gate-policy?detector=contradictions", json={"high": "log_only"})
        assert put_resp.status_code == 200
        second = _create(client, project, "Use Vue for frontend")
        assert second.status_code == 200

        memory = client.get(f"/api/memory/{project}").json()
        audit_types = [e["event_type"] for e in memory.get("audit_log", [])]
        assert "gate_warned" not in audit_types
        assert "gate_blocked" not in audit_types

    def test_get_gate_policy_contradictions_detector(self, client, project):
        _create(client, project, "seed decision to create the project file")
        resp = client.get(f"/api/memory/{project}/gate-policy?detector=contradictions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["detector"] == "contradictions"
        assert body["effective_policy"] == {"high": "block", "medium": "warn", "low": "log_only"}
        assert body["overrides"] == {}


class TestContradictionGateFailsOpen:
    """A bug in detection logic must not brick add_decision -- the single
    most central write path in the system. Fail open (skip the gate),
    not closed (500 or accidental universal block)."""

    def test_detector_exception_does_not_break_decision_creation(self, client, project):
        with patch(
            "core.contradictions.detector.detect_contradictions_for_candidate",
            side_effect=RuntimeError("boom"),
        ):
            resp = _create(client, project, "Use React for frontend")
        assert resp.status_code == 200

    def test_detector_exception_logged_not_silent(self, client, project):
        with patch(
            "core.contradictions.detector.detect_contradictions_for_candidate",
            side_effect=RuntimeError("boom"),
        ), patch("core.tropebook.web.server.logger") as mock_logger:
            _create(client, project, "Use React for frontend")
        assert mock_logger.error.called
