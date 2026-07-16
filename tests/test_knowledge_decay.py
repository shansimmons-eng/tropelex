"""
Tests for Knowledge Decay & Confidence.
"""

from datetime import datetime, timezone, timedelta

from core.knowledge_decay import (
    _days_since,
    _parse_timestamp,
    apply_decay_to_memory,
    decay_score,
    get_confidence_summary,
    get_stale_decisions,
    score_citation,
    score_decision,
    score_decisions,
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
