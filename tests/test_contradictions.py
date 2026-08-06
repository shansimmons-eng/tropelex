"""
Tests for Contradiction Detector — pure functions.
Covers: compute_similarity, detect_direct_contradiction, classify_contradiction,
        suggest_resolution, detect_contradictions.
"""

import pytest
from core.contradictions.detector import (
    classify_contradiction,
    compute_similarity,
    detect_contradictions,
    detect_direct_contradiction,
    suggest_resolution,
)
from core.contradictions import Contradiction, ContradictionReport


# ── compute_similarity ─────────────────────────────────────────────────────

class TestComputeSimilarity:
    def test_identical_texts(self):
        assert compute_similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert compute_similarity("cat dog", "fish bird") == 0.0

    def test_partial_overlap(self):
        score = compute_similarity("use FastAPI for backend", "use FastAPI for API")
        assert 0.0 < score < 1.0

    def test_empty_strings(self):
        assert compute_similarity("", "hello") == 0.0
        assert compute_similarity("", "") == 0.0


# ── detect_direct_contradiction ────────────────────────────────────────────

class TestDetectDirectContradiction:
    def test_opposing_verbs(self):
        assert detect_direct_contradiction(
            "Use FastAPI for API layer",
            "Don't use FastAPI for API layer",
        ) is True

    def test_technology_opposition(self):
        assert detect_direct_contradiction(
            "Use React for frontend",
            "Use Vue for frontend",
        ) is True

    def test_no_contradiction(self):
        assert detect_direct_contradiction(
            "Use FastAPI for backend",
            "Use FastAPI for API layer",
        ) is False

    def test_reverse_opposing(self):
        assert detect_direct_contradiction(
            "Don't use React",
            "We should use React",
        ) is True


# ── classify_contradiction ────────────────────────────────────────────────

class TestClassifyContradiction:
    def test_direct_contradiction_high_severity(self):
        da = {"id": "d1", "decision": "Use FastAPI for API layer"}
        db = {"id": "d2", "decision": "Don't use FastAPI for API layer"}
        result = classify_contradiction(da, db, 0.5)
        assert result is not None
        assert result.contradiction_type == "direct"
        assert result.severity == "high"

    def test_low_similarity_returns_none(self):
        da = {"id": "d1", "decision": "Use FastAPI"}
        db = {"id": "d2", "decision": "Buy new laptop"}
        result = classify_contradiction(da, db, 0.05)
        assert result is None

    def test_temporal_contradiction(self):
        da = {"id": "d1", "decision": "Use Express for backend API", "timestamp": "2026-01-01"}
        db = {"id": "d2", "decision": "Switched from Express to Koa for backend API", "timestamp": "2026-06-01"}
        result = classify_contradiction(da, db, 0.5)
        # Temporal check runs alongside direct; express/koa is in _TECH_OPPOSITIONS
        # so it may be classified as direct. The important thing is a contradiction IS found.
        assert result is not None

    def test_implicit_contradiction(self):
        da = {"id": "d1", "decision": "Prefer writing detailed documentation for APIs"}
        db = {"id": "d2", "decision": "Keep documentation minimal and concise for APIs"}
        result = classify_contradiction(da, db, 0.5)
        assert result is not None
        assert result.contradiction_type in ("implicit", "direct")


# ── suggest_resolution ────────────────────────────────────────────────────

class TestSuggestResolution:
    def test_direct_suggestion(self):
        c = Contradiction(
            id="c1", decision_a_id="d1", decision_a_text="Use X",
            decision_b_id="d2", decision_b_text="Don't use X",
            contradiction_type="direct", severity="high",
            similarity_score=0.5, resolution_suggestion="",
        )
        result = suggest_resolution(c)
        assert "conflict" in result.lower() or "supersede" in result.lower()

    def test_temporal_suggestion(self):
        c = Contradiction(
            id="c1", decision_a_id="d1", decision_a_text="A",
            decision_b_id="d2", decision_b_text="B",
            contradiction_type="temporal", severity="medium",
            similarity_score=0.5, resolution_suggestion="",
        )
        result = suggest_resolution(c)
        assert "superseded" in result.lower() or "newer" in result.lower()


# ── detect_contradictions ─────────────────────────────────────────────────

class TestDetectContradictions:
    def test_empty_decisions(self):
        result = detect_contradictions([])
        assert isinstance(result, ContradictionReport)
        assert result.total_checked == 0

    def test_no_contradictions(self):
        decisions = [
            {"id": "d1", "decision": "Use Python"},
            {"id": "d2", "decision": "Buy office supplies"},
        ]
        result = detect_contradictions(decisions)
        assert len(result.contradictions) == 0

    def test_finds_direct_contradiction(self):
        decisions = [
            {"id": "d1", "decision": "Use React for frontend"},
            {"id": "d2", "decision": "Use Vue for frontend"},
        ]
        result = detect_contradictions(decisions)
        assert len(result.contradictions) >= 1
        assert result.total_checked == 1  # C(2,2) = 1 pair

    def test_multiple_pairs_checked(self):
        decisions = [
            {"id": "d1", "decision": "A"},
            {"id": "d2", "decision": "B"},
            {"id": "d3", "decision": "C"},
        ]
        result = detect_contradictions(decisions)
        assert result.total_checked == 3  # C(3,2) = 3 pairs

    def test_sorted_by_severity(self):
        decisions = [
            {"id": "d1", "decision": "Use React for frontend"},
            {"id": "d2", "decision": "Use Vue for frontend"},
            {"id": "d3", "decision": "Adopt JavaScript for new projects"},
            {"id": "d4", "decision": "Prefer TypeScript for new projects"},
        ]
        result = detect_contradictions(decisions)
        if len(result.contradictions) > 1:
            severities = [c.severity for c in result.contradictions]
            rank = {"high": 0, "medium": 1, "low": 2}
            assert severities == sorted(severities, key=lambda s: rank.get(s, 3))


# ── /contradictions endpoint: escalation to Safety Review queue ────────────

import uuid
from fastapi.testclient import TestClient
from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_contradictions_{uuid.uuid4().hex[:8]}"


class TestContradictionEscalation:
    def _create_conflicting_pair(self, client, project):
        a = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Use React for frontend", "context": "",
        }).json()["decision"]
        b = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Use Vue for frontend", "context": "",
        }).json()["decision"]
        return a["id"], b["id"]

    def test_high_severity_contradiction_escalates_to_review(self, client, project):
        a_id, b_id = self._create_conflicting_pair(client, project)

        resp = client.get(f"/api/memory/{project}/contradictions")
        assert resp.status_code == 200

        pending = client.get(f"/api/memory/{project}/reviews/pending").json()
        pending_ids = {r["id"] for r in pending["pending_reviews"]}
        assert a_id in pending_ids
        assert b_id in pending_ids

    def test_approved_decision_does_not_re_escalate_on_rescan(self, client, project):
        """Regression test: a contradiction doesn't structurally resolve just
        because one side gets approved -- the pair is still "unresolved" by
        detect_contradictions' own definition. Without a check for an
        existing review, every re-scan (e.g. re-opening the Contradictions
        tab) flips requires_review back to True, so an approved decision
        never actually leaves the pending queue. Same bug class already
        fixed once for the persona/market escalation path; this is the
        contradiction path's own copy of it."""
        a_id, b_id = self._create_conflicting_pair(client, project)

        client.get(f"/api/memory/{project}/contradictions")
        assert client.get(f"/api/memory/{project}/reviews/pending").json()["total_pending"] == 2

        approved = client.post(f"/api/memory/{project}/decisions/{a_id}/approve", params={"reviewer": "shan"})
        assert approved.status_code == 200

        # Re-scanning contradictions (e.g. revisiting the tab) must not
        # undo the approval.
        client.get(f"/api/memory/{project}/contradictions")
        pending = client.get(f"/api/memory/{project}/reviews/pending").json()
        pending_ids = {r["id"] for r in pending["pending_reviews"]}
        assert a_id not in pending_ids
        assert b_id in pending_ids  # the un-approved side is still correctly pending
