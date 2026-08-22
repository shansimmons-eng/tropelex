"""Tests for core.tropebook.feed_intelligence — Research Feed Intelligence."""

import pytest
from core.tropebook.feed_intelligence import (
    detect_trends,
    flag_anomalies,
    compute_feed_intelligence,
    score_feed_citation_health,
    _count_topics,
    _compute_velocity,
    _classify_overall_trend,
    _extract_trending,
    _find_peak_periods,
)


def _run(citations=None, ts="2026-01-01T00:00:00Z", status="ok", errors=None):
    r = {"citations": citations or [], "timestamp": ts, "status": status}
    if errors:
        r["errors"] = errors
    return r


def _cit(topic="AI"):
    return {"topic": topic, "title": f"About {topic}"}


class TestDetectTrends:
    def test_empty(self):
        result = detect_trends([])
        assert result["overall_trend"] == "stable"
        assert result["trending_topics"] == []

    def test_single_topic(self):
        runs = [_run([_cit("AI")]), _run([_cit("AI")])]
        result = detect_trends(runs)
        assert len(result["trending_topics"]) >= 1
        assert result["trending_topics"][0]["topic"] == "AI"

    def test_increasing_trend(self):
        runs = [_run([_cit("AI")]), _run([_cit("AI"), _cit("ML")]), _run([_cit("AI"), _cit("ML"), _cit("DL")])]
        result = detect_trends(runs)
        assert result["overall_trend"] in ("increasing", "stable")


class TestFlagAnomalies:
    def test_empty(self):
        assert flag_anomalies([]) == []

    def test_single_run(self):
        assert flag_anomalies([_run([_cit()])]) == []

    def test_spike_detection(self):
        runs = [_run([_cit()]) for _ in range(5)]
        runs.append(_run([_cit() for _ in range(20)]))
        anomalies = flag_anomalies(runs)
        assert any(a["anomaly_type"] == "spike" for a in anomalies)

    def test_drop_detection(self):
        runs = [_run([_cit() for _ in range(10)]) for _ in range(5)]
        runs.append(_run([]))
        anomalies = flag_anomalies(runs)
        assert any(a["anomaly_type"] == "drop" for a in anomalies)

    def test_error_cluster(self):
        runs = [_run(status="error", errors=["fail"]) for _ in range(4)]
        anomalies = flag_anomalies(runs)
        assert any(a["anomaly_type"] == "error_cluster" for a in anomalies)

    def test_stale_run(self):
        runs = [_run([_cit()]), _run([])]
        anomalies = flag_anomalies(runs)
        assert any(a["anomaly_type"] == "stale" for a in anomalies)


class TestComputeFeedIntelligence:
    def test_shape(self):
        runs = [_run([_cit()])]
        result = compute_feed_intelligence(runs)
        assert "trends" in result
        assert "anomalies" in result
        assert result["run_count"] == 1
        assert result["total_citations"] == 1


class TestHelpers:
    def test_count_topics(self):
        runs = [_run([_cit("AI"), _cit("ML")]), _run([_cit("AI")])]
        counts = _count_topics(runs)
        assert counts["AI"] == [0, 1]
        assert counts["ML"] == [0]

    def test_velocity_empty(self):
        assert _compute_velocity({}, 3) == {}

    def test_classify_empty(self):
        assert _classify_overall_trend({}) == "stable"

    def test_peak_periods(self):
        runs = [_run([_cit()]), _run([_cit()]), _run([_cit() for _ in range(10)])]
        peaks = _find_peak_periods(runs)
        assert len(peaks) == 1
        assert peaks[0]["run_index"] == 2


def _citation(title="Fresh", created_at=None, days_old=0):
    from datetime import datetime, timedelta, timezone
    ts = created_at or (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    return {"title": title, "url": f"https://example.com/{title}", "created_at": ts}


class TestScoreFeedCitationHealth:
    def test_empty_citations(self):
        result = score_feed_citation_health([])
        assert result == {"count": 0, "average_score": None, "aging_count": 0, "citations": []}

    def test_fresh_citation_is_not_aging(self):
        result = score_feed_citation_health([_citation("Fresh", days_old=0)])
        assert result["count"] == 1
        assert result["aging_count"] == 0
        assert result["citations"][0]["tier"] == "high"

    def test_old_citation_counts_as_aging(self):
        result = score_feed_citation_health([_citation("Old", days_old=365)])
        assert result["aging_count"] == 1
        assert result["citations"][0]["tier"] in ("low", "stale")

    def test_average_score_reflects_mix(self):
        result = score_feed_citation_health([
            _citation("Fresh", days_old=0),
            _citation("Old", days_old=365),
        ])
        assert result["count"] == 2
        assert result["aging_count"] == 1
        scores = [c["score"] for c in result["citations"]]
        assert result["average_score"] == round(sum(scores) / 2, 3)
