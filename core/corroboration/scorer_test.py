"""Tests for core.corroboration.scorer — pure scoring functions."""

from datetime import datetime, timezone, timedelta

from core.corroboration.scorer import (
    CorroborationResult,
    ResearchFinding,
    compute_relevance,
    detect_contradiction_signals,
    detect_outdated_signals,
    score_corroboration,
)


# --- Fixtures ---

def _finding(desc: str, url: str = "https://example.com", score: float = 0.0, date: str | None = None) -> ResearchFinding:
    return ResearchFinding(title=desc[:40], url=url, description=desc, relevance_score=score, published_date=date)


def _old_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()


def _recent_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


# --- compute_relevance ---

class TestComputeRelevance:
    def test_identical_text(self):
        assert compute_relevance("fastapi web server", _finding("fastapi web server")) == 1.0

    def test_partial_overlap(self):
        assert 0.0 < compute_relevance("fastapi web server", _finding("fastapi rest api")) < 1.0

    def test_no_overlap(self):
        assert compute_relevance("postgresql database", _finding("react frontend")) == 0.0

    def test_empty_rationale(self):
        assert compute_relevance("", _finding("anything")) == 0.0

    def test_empty_description(self):
        score = compute_relevance("fastapi web", _finding(""))
        assert score >= 0.0  # no crash, returns 0 or more


# --- detect_contradiction_signals ---

class TestDetectContradictionSignals:
    def test_deprecated_keyword(self):
        findings = [_finding("fastapi is deprecated, use Flask instead")]
        signals = detect_contradiction_signals("use fastapi for web", findings)
        assert len(signals) == 1

    def test_no_match_unrelated(self):
        findings = [_finding("fastapi is great and not deprecated")]
        signals = detect_contradiction_signals("postgresql database", findings)
        assert signals == []

    def test_multiple_signals(self):
        findings = [
            _finding("fastapi deprecated no longer maintained"),
            _finding("fastapi replaced by flask recommended"),
        ]
        signals = detect_contradiction_signals("use fastapi for web", findings)
        assert len(signals) == 2

    def test_empty_findings(self):
        assert detect_contradiction_signals("anything", []) == []


# --- detect_outdated_signals ---

class TestDetectOutdatedSignals:
    def test_old_date(self):
        findings = [_finding("fastapi used", date=_old_date())]
        signals = detect_outdated_signals(findings)
        assert len(signals) == 1

    def test_recent_date(self):
        findings = [_finding("fastapi used", date=_recent_date())]
        signals = detect_outdated_signals(findings)
        assert signals == []

    def test_legacy_keyword(self):
        findings = [_finding("legacy fastapi setup")]
        signals = detect_outdated_signals(findings)
        assert len(signals) == 1

    def test_no_date_no_keyword(self):
        findings = [_finding("fastapi works well")]
        signals = detect_outdated_signals(findings)
        assert signals == []


# --- score_corroboration ---

class TestScoreCorroboration:
    def test_no_findings(self):
        result = score_corroboration("use fastapi", [])
        assert result.status == "unverifiable"
        assert result.confidence_adjustment == 0.0

    def test_low_relevance(self):
        findings = [_finding("completely unrelated topic about gardening")]
        result = score_corroboration("fastapi web server", findings)
        assert result.status == "unverifiable"

    def test_supported(self):
        findings = [
            _finding("fastapi is a great web framework for building APIs"),
            _finding("fastapi provides excellent performance for web servers"),
            _finding("fastapi widely adopted for REST APIs"),
        ]
        result = score_corroboration("use fastapi for web server", findings)
        assert result.status == "supported"
        assert result.confidence_adjustment > 0

    def test_contradicted(self):
        findings = [
            _finding("fastapi deprecated no longer supported"),
            _finding("fastapi not recommended for production use"),
        ]
        result = score_corroboration("use fastapi for web server", findings)
        assert result.status == "contradicted"
        assert result.confidence_adjustment < 0

    def test_outdated(self):
        findings = [
            _finding("fastapi was a popular choice", date=_old_date()),
            _finding("legacy fastapi setup guide"),
        ]
        result = score_corroboration("use fastapi for web server", findings)
        assert result.status == "outdated"
        assert result.confidence_adjustment < 0

    def test_evidence_urls_collected(self):
        findings = [
            _finding("fastapi is great for web servers", url="https://a.com"),
            _finding("fastapi excellent REST performance", url="https://b.com"),
            _finding("fastapi widely adopted web", url="https://c.com"),
        ]
        result = score_corroboration("use fastapi for web", findings)
        assert len(result.evidence_urls) > 0

    def test_result_is_frozen_dataclass(self):
        result = score_corroboration("test", [])
        assert isinstance(result, CorroborationResult)
        # frozen — immutable
        try:
            result.status = "supported"  # type: ignore[misc]
            assert False, "Should be frozen"
        except AttributeError:
            pass
