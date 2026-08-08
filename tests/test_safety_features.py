"""Tests for Safety Metadata, Dashboard, Impact Analysis, and Review Workflow."""

from __future__ import annotations

import uuid
import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_safety_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sample_decision_with_safety():
    return {
        "decision": "Implement critical security patch",
        "context": "High priority vulnerability fix",
        "safety_metadata": {
            "risk_level": "high",
            "reversibility": True,
            "affected_systems": ["api", "database"],
            "rationale_quality": 0.8,
            "alignment_considerations": "Security critical",
            "requires_review": True,
            "safety_category": "robustness",
        },
    }


@pytest.fixture
def sample_decision_low_risk():
    return {
        "decision": "Update documentation",
        "context": "Minor improvement",
        "safety_metadata": {
            "risk_level": "low",
            "reversibility": True,
            "affected_systems": ["docs"],
            "requires_review": False,
            "safety_category": "general",
        },
    }


class TestSafetyMetadataEndpoint:
    """Tests for POST /api/memory/{project}/decisions with safety metadata."""

    def test_add_decision_with_safety_metadata(self, client, project, sample_decision_with_safety):
        response = client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        assert response.status_code == 200
        data = response.json()
        assert data["added"] is True
        assert data["decision"]["safety_metadata"]["risk_level"] == "high"
        assert data["decision"]["safety_metadata"]["requires_review"] is True

    def test_add_decision_without_safety_metadata_requires_tag(self, client, project):
        """A decision with no safety_category is rejected, not silently
        assigned "general" — see core/triggers/tag_gate.py. The 422 carries
        the auto-classifier's suggestion so a caller can retry with it."""
        response = client.post(
            f"/api/memory/{project}/decisions",
            json={"decision": "Simple decision", "context": "No safety metadata"},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["error"] == "tag_required"
        assert detail["suggested"] in detail["valid_categories"]

    def test_auto_classify_risk_level(self, client, project):
        # First call omits the category and only reads the suggestion off
        # the 422 — mirrors what the dashboard/TUI do via preview-category.
        rejected = client.post(
            f"/api/memory/{project}/decisions",
            json={"decision": "Critical production deployment", "context": "High risk change"},
        )
        assert rejected.status_code == 422

        response = client.post(
            f"/api/memory/{project}/decisions",
            json={
                "decision": "Critical production deployment",
                "context": "High risk change",
                "safety_metadata": {"safety_category": "general"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        # risk_level still comes from the heuristic even though the request
        # only supplied safety_category explicitly (model_fields_set merge).
        assert data["decision"]["safety_metadata"]["risk_level"] in ["medium", "high"]


class TestCategoryPreviewEndpoint:
    """Tests for POST /api/memory/{project}/decisions/preview-category — the
    suggestion the dashboard/TUI show before a user picks a category. Saves
    nothing; add_decision itself never accepts this as a value."""

    def test_preview_returns_a_suggestion_without_saving(self, client, project):
        resp = client.post(
            f"/api/memory/{project}/decisions/preview-category",
            json={"decision": "Critical production deployment", "context": "High risk change"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["safety_category"] in {
            "general", "adversarial", "robustness", "monitoring", "governance", "alignment",
        }
        assert data["risk_level"] in {"low", "medium", "high", "critical"}

        # Nothing was actually recorded.
        memory = client.get(f"/api/memory/{project}").json()
        assert memory.get("decisions", []) == []


class TestUntaggedDecisionsEndpoint:
    """Tests for GET /api/memory/{project}/decisions/untagged — the triage
    queue for decisions captured via /{project}/slack/capture (Emacs, Slack),
    which never go through add_decision's require_tag gate since that path
    fires with no human present."""

    def test_no_decisions_is_empty(self, client, project):
        resp = client.get(f"/api/memory/{project}/decisions/untagged")
        assert resp.status_code == 200
        assert resp.json() == {"decisions": [], "count": 0}

    def test_tagged_decision_not_listed(self, client, project, sample_decision_with_safety):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        resp = client.get(f"/api/memory/{project}/decisions/untagged")
        assert resp.json() == {"decisions": [], "count": 0}

    def test_slack_captured_decision_is_listed(self, client, project):
        # Simulates the /{project}/slack/capture write path, which writes
        # decisions with no safety_metadata key at all. slack_capture 404s
        # on an unknown project, so create it first.
        client.post("/api/memory", json={"project_name": project})
        client.post(f"/api/memory/{project}/slack/capture", json={
            "decision_text": "Rolled back the last deploy",
            "context": "auto-captured from a commit",
            "channel": "emacs",
        })
        resp = client.get(f"/api/memory/{project}/decisions/untagged")
        data = resp.json()
        assert data["count"] == 1
        assert data["decisions"][0]["decision"] == "Rolled back the last deploy"
        # Must have a real id — slack-captured decisions used to have none,
        # which meant nothing could ever address them individually.
        assert data["decisions"][0]["id"]


class TestTagDecisionEndpoint:
    """Tests for PATCH /{project}/decisions/{id}/safety-category — the only
    way a slack/capture-sourced decision leaves the untagged-decisions
    queue, since it never goes through add_decision."""

    def test_tags_a_slack_captured_decision(self, client, project):
        client.post("/api/memory", json={"project_name": project})
        client.post(f"/api/memory/{project}/slack/capture", json={
            "decision_text": "Rolled back the last deploy", "context": "", "channel": "emacs",
        })
        decision_id = client.get(f"/api/memory/{project}/decisions/untagged").json()["decisions"][0]["id"]

        resp = client.patch(
            f"/api/memory/{project}/decisions/{decision_id}/safety-category",
            json={"safety_category": "governance"},
        )
        assert resp.status_code == 200
        assert resp.json()["decision"]["safety_metadata"]["safety_category"] == "governance"

        # It's gone from the untagged queue now.
        assert client.get(f"/api/memory/{project}/decisions/untagged").json()["count"] == 0

    def test_invalid_category_rejected(self, client, project):
        client.post("/api/memory", json={"project_name": project})
        client.post(f"/api/memory/{project}/slack/capture", json={
            "decision_text": "Rolled back the last deploy", "context": "", "channel": "emacs",
        })
        decision_id = client.get(f"/api/memory/{project}/decisions/untagged").json()["decisions"][0]["id"]

        resp = client.patch(
            f"/api/memory/{project}/decisions/{decision_id}/safety-category",
            json={"safety_category": "not-a-real-category"},
        )
        assert resp.status_code == 422

    def test_unknown_decision_id_404s(self, client, project):
        client.post("/api/memory", json={"project_name": project})
        resp = client.patch(
            f"/api/memory/{project}/decisions/does-not-exist/safety-category",
            json={"safety_category": "general"},
        )
        assert resp.status_code == 404


class TestNeedsAttentionEndpoint:
    """Tests for GET /api/memory/{project}/needs-attention — the aggregation
    feeding the dashboard's Overview-page Needs Attention panel. Thin layer
    over /reviews/pending and /decisions/untagged, so these mostly confirm
    the merge and item shape rather than re-testing either source."""

    def test_empty_project_has_no_items(self, client, project):
        resp = client.get(f"/api/memory/{project}/needs-attention")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "count": 0}

    def test_pending_review_appears_as_an_item(self, client, project):
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Deploy without a rollback plan",
            "context": "",
            "safety_metadata": {"safety_category": "governance", "requires_review": True},
        })
        resp = client.get(f"/api/memory/{project}/needs-attention")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["kind"] == "pending_review"
        assert data["items"][0]["label"] == "Deploy without a rollback plan"

    def test_untagged_decision_appears_as_an_item(self, client, project):
        client.post("/api/memory", json={"project_name": project})
        client.post(f"/api/memory/{project}/slack/capture", json={
            "decision_text": "Rolled back the last deploy",
            "context": "",
            "channel": "emacs",
        })
        resp = client.get(f"/api/memory/{project}/needs-attention")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["kind"] == "untagged_decision"
        assert data["items"][0]["label"] == "Rolled back the last deploy"

    def test_both_kinds_combine(self, client, project):
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Deploy without a rollback plan",
            "context": "",
            "safety_metadata": {"safety_category": "governance", "requires_review": True},
        })
        client.post(f"/api/memory/{project}/slack/capture", json={
            "decision_text": "Rolled back the last deploy",
            "context": "",
            "channel": "emacs",
        })
        resp = client.get(f"/api/memory/{project}/needs-attention")
        data = resp.json()
        assert data["count"] == 2
        kinds = {item["kind"] for item in data["items"]}
        assert kinds == {"pending_review", "untagged_decision"}


class TestSafetyDashboardEndpoint:
    """Tests for GET /api/memory/{project}/safety-dashboard."""

    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/safety-dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0
        assert data["summary"]["safety_score"] == 1.0

    def test_dashboard_with_decisions(self, client, project, sample_decision_with_safety):
        # Add a decision first
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        
        response = client.get(f"/api/memory/{project}/safety-dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] >= 1
        assert "risk_trend" in data
        assert "category_distribution" in data


class TestFrictionSafetyCrossConnect:
    """Friction Mining feeds into the Safety score, not just Health Dashboard.

    A run of high-friction sessions (corrections, retries, escalation) is a
    leading risk indicator even when no individual decision looks risky yet.
    """

    _HIGH_FRICTION_TRANSCRIPT = (
        "user: no, that's wrong, I meant something else entirely here\n"
        "user: as I said, please just fix this already now\n"
        "user: for the last time, why did you do this again\n"
        "user: you broke the deploy and did not test it at all\n"
    )

    def test_friction_scan_persists_history(self, client, project, sample_decision_low_risk):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_low_risk)
        resp = client.post(
            f"/api/memory/{project}/friction/scan",
            json={"transcript": self._HIGH_FRICTION_TRANSCRIPT},
        )
        assert resp.status_code == 200
        assert resp.json()["friction_score"] > 0

        summary = client.get(f"/api/memory/{project}/friction/summary")
        assert summary.status_code == 200
        assert summary.json()["total_scans"] == 1

    def test_high_friction_reduces_safety_score(self, client, project, sample_decision_low_risk):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_low_risk)
        before = client.get(f"/api/memory/{project}/safety-stats").json()
        assert before["friction_penalty"] == 0.0

        for _ in range(3):
            client.post(
                f"/api/memory/{project}/friction/scan",
                json={"transcript": self._HIGH_FRICTION_TRANSCRIPT},
            )

        after = client.get(f"/api/memory/{project}/safety-stats").json()
        assert after["friction_penalty"] > 0.0
        assert after["safety_score"] < before["safety_score"]

    def test_friction_penalty_is_capped(self, client, project, sample_decision_low_risk):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_low_risk)
        for _ in range(15):
            client.post(
                f"/api/memory/{project}/friction/scan",
                json={"transcript": self._HIGH_FRICTION_TRANSCRIPT},
            )
        data = client.get(f"/api/memory/{project}/safety-stats").json()
        assert data["friction_penalty"] <= 0.15
        assert data["safety_score"] >= 0.0


class TestContradictionSafetyCrossConnect:
    """High-severity contradictions auto-escalate their decisions into the
    Safety Review queue instead of only surfacing in the Contradictions tab.
    """

    def test_direct_contradiction_escalates_both_decisions(self, client, project):
        client.post(f"/api/memory/{project}/decisions",
                    json={"decision": "Use REST for the public API", "context": "",
                          "safety_metadata": {"safety_category": "general"}})
        client.post(f"/api/memory/{project}/decisions",
                    json={"decision": "Use GraphQL for the public API", "context": "",
                          "safety_metadata": {"safety_category": "general"}})

        resp = client.get(f"/api/memory/{project}/contradictions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["severity_distribution"]["high"] >= 1
        assert data["escalated_to_review"] >= 1

        pending = client.get(f"/api/memory/{project}/reviews/pending").json()
        assert pending["total_pending"] >= 1

    def test_already_flagged_decision_not_double_counted(self, client, project):
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Use REST for the public API", "context": "",
            "safety_metadata": {"requires_review": True, "safety_category": "general"},
        })
        client.post(f"/api/memory/{project}/decisions",
                    json={"decision": "Use GraphQL for the public API", "context": "",
                          "safety_metadata": {"safety_category": "general"}})

        resp = client.get(f"/api/memory/{project}/contradictions")
        # Only the second decision should be newly escalated — the first was already flagged.
        assert resp.json()["escalated_to_review"] == 1

    def test_no_contradictions_no_escalation(self, client, project):
        client.post(f"/api/memory/{project}/decisions",
                    json={"decision": "Use FastAPI for the backend", "context": "",
                          "safety_metadata": {"safety_category": "general"}})
        resp = client.get(f"/api/memory/{project}/contradictions")
        assert resp.json()["escalated_to_review"] == 0


class TestDocMineSafetyEscalation:
    """Unit tests for the doc-mining escalation helper (not the full
    file-scanning endpoint, which reads real files under the repo root —
    exercising that here would mean writing test files into the live repo
    tree, the same kind of test/production storage collision fixed earlier
    for research feeds).
    """

    def test_escalates_matching_decision(self):
        from core.docmine.router import _escalate_to_review
        memory = {"decisions": [
            {"id": "d1", "decision": "Use REST", "safety_metadata": {}},
            {"id": "d2", "decision": "Use GraphQL", "safety_metadata": {"requires_review": True}},
        ]}
        count = _escalate_to_review(memory, {"d1", "d2"})
        assert count == 1  # only d1 was newly escalated
        assert memory["decisions"][0]["safety_metadata"]["requires_review"] is True
        assert memory["decisions"][0]["safety_metadata"]["risk_level"] == "medium"

    def test_missing_decision_id_ignored(self):
        from core.docmine.router import _escalate_to_review
        memory = {"decisions": [{"id": "d1", "decision": "x", "safety_metadata": {}}]}
        count = _escalate_to_review(memory, {"nonexistent"})
        assert count == 0

    def test_preserves_existing_high_risk_level(self):
        from core.docmine.router import _escalate_to_review
        memory = {"decisions": [
            {"id": "d1", "decision": "x", "safety_metadata": {"risk_level": "critical"}},
        ]}
        _escalate_to_review(memory, {"d1"})
        assert memory["decisions"][0]["safety_metadata"]["risk_level"] == "critical"


class _FakeSkillGraph:
    """Stand-in for AgentSkillGraph that never touches the filesystem —
    the real class writes to memory/agent_skills/<project>.json under
    whatever base_path it's given, and the production code path always
    points that at the live repo (BASE_DIR), not a tmp_path. Monkeypatching
    the class itself (rather than seeding real skill data for a throwaway
    test project) avoids leaking test files into production storage, the
    same class of bug fixed earlier for research feeds.
    """

    def __init__(self, base_path):
        pass

    def _skills_file(self, project):
        return self

    def exists(self):  # the object returned by _skills_file is queried with .exists()
        return True

    def _load(self, project):
        return {"skills": {"auth": {"score": 0.2, "attempts": 5}}, "sessions": []}


class TestPersonaMarketSafetyCrossConnect:
    """A decision touching a category that's both a persona weakness and
    poorly-calibrated in Decision Market auto-escalates for review — neither
    signal alone is enough, since every project has some weak category and
    some mediocre bet.
    """

    def test_no_persona_data_no_escalation(self, client, project, sample_decision_low_risk):
        # No skill data recorded for this project yet — should degrade
        # gracefully to zero escalations, not error.
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_low_risk)
        resp = client.get(f"/api/memory/{project}/reviews/pending")
        assert resp.status_code == 200
        assert resp.json()["total_pending"] == 0

    def test_weak_category_and_poor_calibration_escalates(self, client, project, monkeypatch):
        monkeypatch.setattr("core.agent_skills.AgentSkillGraph", _FakeSkillGraph)

        # Decision in the "auth" category — matches the fake persona's weakness.
        created = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Ship the new login flow",
            "context": "",
            "safety_metadata": {"affected_systems": ["auth"], "safety_category": "general"},
        }).json()
        decision_id = created["decision"]["id"]

        # Poor market calibration in "auth": 3 incorrect, 1 correct.
        for i, outcome in enumerate(["incorrect", "incorrect", "incorrect", "correct"]):
            placed = client.post(f"/api/memory/{project}/market/bet", json={
                "decision_id": decision_id, "agent_name": project,
                "confidence": 0.8, "category": "auth",
            }).json()
            bet_id = placed["bet"]["id"]
            resolved = client.post(f"/api/memory/{project}/market/resolve", json={
                "bet_id": bet_id, "outcome": outcome,
            })
            assert resolved.status_code == 200

        resp = client.get(f"/api/memory/{project}/reviews/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_pending"] == 1
        assert "auth" in data["pending_reviews"][0]["escalation_reason"]

    def test_approved_decision_does_not_re_escalate(self, client, project, monkeypatch):
        """Regression test: approving an auto-escalated decision must make it
        leave the pending queue for good. Previously, since the persona/market
        risk signal that triggered escalation doesn't go away just because a
        human approved the decision, the very next /reviews/pending call
        re-flagged it (requires_review=False -> True again), so it never
        actually left the queue no matter how many times it was approved."""
        monkeypatch.setattr("core.agent_skills.AgentSkillGraph", _FakeSkillGraph)

        created = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Ship the new login flow",
            "context": "",
            "safety_metadata": {"affected_systems": ["auth"], "safety_category": "general"},
        }).json()
        decision_id = created["decision"]["id"]

        for i, outcome in enumerate(["incorrect", "incorrect", "incorrect", "correct"]):
            placed = client.post(f"/api/memory/{project}/market/bet", json={
                "decision_id": decision_id, "agent_name": project,
                "confidence": 0.8, "category": "auth",
            }).json()
            client.post(f"/api/memory/{project}/market/resolve", json={
                "bet_id": placed["bet"]["id"], "outcome": outcome,
            })

        # Confirm it's actually in the queue before approving.
        assert client.get(f"/api/memory/{project}/reviews/pending").json()["total_pending"] == 1

        approved = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/approve",
            params={"reviewer": "shan"},
        )
        assert approved.status_code == 200

        # Call /reviews/pending twice — the bug only reproduced on the call
        # *after* the approval, since that's what re-runs the escalation check.
        for _ in range(2):
            resp = client.get(f"/api/memory/{project}/reviews/pending")
            assert resp.json()["total_pending"] == 0, "approved decision re-entered the pending queue"

    def test_weak_category_but_good_calibration_no_escalation(self, client, project, monkeypatch):
        # Persona weakness alone, without poor market calibration, is not
        # enough to auto-escalate — only the compounding signal should.
        monkeypatch.setattr("core.agent_skills.AgentSkillGraph", _FakeSkillGraph)
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Ship the new login flow",
            "context": "",
            "safety_metadata": {"affected_systems": ["auth"], "safety_category": "general"},
        })
        resp = client.get(f"/api/memory/{project}/reviews/pending")
        assert resp.json()["total_pending"] == 0


class TestSafetyTrendEndpoint:
    """Tests for GET /api/memory/{project}/safety-trend."""

    def test_trend_with_default_months(self, client, project):
        response = client.get(f"/api/memory/{project}/safety-trend")
        assert response.status_code == 200
        data = response.json()
        assert "time_series" in data
        assert data["period_months"] == 12

    def test_trend_with_custom_months(self, client, project):
        response = client.get(f"/api/memory/{project}/safety-trend?months=6")
        assert response.status_code == 200
        data = response.json()
        assert data["period_months"] == 6


class TestDecisionImpactEndpoint:
    """Tests for GET /api/memory/{project}/decision-impact."""

    def test_empty_impact(self, client, project):
        response = client.get(f"/api/memory/{project}/decision-impact")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0
        assert data["summary"]["total_systems"] == 0

    def test_impact_with_systems(self, client, project, sample_decision_with_safety):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)

        response = client.get(f"/api/memory/{project}/decision-impact")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_systems"] >= 1

    def test_impact_with_empty_affected_systems(self, client, project):
        """Regression: a decision with affected_systems=[] used to 500 with
        UnboundLocalError — three .append() calls meant to run once per system
        were mis-indented outside their own `for system in systems:` loop, so
        with an empty list `system` was never bound."""
        client.post(
            f"/api/memory/{project}/decisions",
            json={
                "decision": "Update internal docs",
                "context": "No systems affected",
                "safety_metadata": {"risk_level": "low", "affected_systems": [], "safety_category": "general"},
            },
        )

        response = client.get(f"/api/memory/{project}/decision-impact")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 1
        assert data["summary"]["total_systems"] == 0


class TestDecisionImpactDetailEndpoint:
    """Tests for GET /api/memory/{project}/decision-impact/{decision_id}."""

    def test_nonexistent_decision(self, client, project):
        response = client.get(f"/api/memory/{project}/decision-impact/nonexistent")
        assert response.status_code == 404

    def test_existing_decision(self, client, project, sample_decision_with_safety):
        # Add decision
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        decision_id = resp.json()["decision"]["id"]
        
        response = client.get(f"/api/memory/{project}/decision-impact/{decision_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["decision"]["id"] == decision_id


class TestSafetyReviewEndpoints:
    """Tests for safety review workflow endpoints."""

    def test_submit_review(self, client, project, sample_decision_with_safety):
        # Add decision requiring review
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        decision_id = resp.json()["decision"]["id"]
        
        # Submit review
        review = {
            "reviewer": "security_team",
            "status": "approved",
            "comments": "Reviewed and approved",
            "risk_assessment": "Acceptable with monitoring",
            "mitigation_suggestions": ["Add logging", "Create rollback plan"],
        }
        response = client.post(f"/api/memory/{project}/decisions/{decision_id}/review", json=review)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["review"]["status"] == "approved"

    def test_get_pending_reviews(self, client, project, sample_decision_with_safety):
        # Add decision requiring review
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        
        response = client.get(f"/api/memory/{project}/reviews/pending")
        assert response.status_code == 200
        data = response.json()
        assert data["total_pending"] >= 1

    def test_get_review_stats(self, client, project):
        response = client.get(f"/api/memory/{project}/reviews/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_reviews" in data
        assert "approval_rate" in data

    def test_get_review_history(self, client, project, sample_decision_with_safety):
        # Add decision and review it
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        decision_id = resp.json()["decision"]["id"]
        client.post(
            f"/api/memory/{project}/decisions/{decision_id}/review",
            json={"reviewer": "tester", "status": "approved"},
        )
        
        response = client.get(f"/api/memory/{project}/reviews/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total_reviews"] >= 1

    def test_approve_endpoint(self, client, project, sample_decision_with_safety):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        decision_id = resp.json()["decision"]["id"]
        
        response = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/approve",
            params={"reviewer": "admin", "comments": "Quick approve"},
        )
        assert response.status_code == 200
        assert response.json()["review"]["status"] == "approved"

    def test_reject_endpoint(self, client, project, sample_decision_with_safety):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        decision_id = resp.json()["decision"]["id"]
        
        response = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/reject",
            params={"reviewer": "admin", "comments": "Too risky", "risk_assessment": "High risk"},
        )
        assert response.status_code == 200
        assert response.json()["review"]["status"] == "rejected"


class TestErrorHandling:
    """Tests for error handling in safety endpoints."""

    def test_review_nonexistent_decision(self, client, project):
        response = client.post(
            f"/api/memory/{project}/decisions/fake_id/review",
            json={"reviewer": "test", "status": "approved"},
        )
        assert response.status_code == 404

    def test_invalid_status(self, client, project, sample_decision_with_safety):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_with_safety)
        decision_id = resp.json()["decision"]["id"]
        
        response = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/review",
            json={"reviewer": "test", "status": "invalid_status"},
        )
        assert response.status_code == 422  # Validation error
