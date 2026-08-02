"""
Tests for Friction Mining — miner.py and router.py.

Detects implicit friction signals (rephrasing, retries, rapid edits,
escalation) from conversation transcripts. Uses pytest, AAA pattern,
no shared state, all external I/O mocked.
"""

import asyncio
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from core.friction.miner import (
    Err,
    FrictionSignal,
    FrictionZone,
    Ok,
    _build_zone,
    _detect_escalation,
    _detect_rapid_edits,
    _detect_retries,
    _detect_rephrasing,
    compute_friction_by_agent,
    compute_friction_score,
    detect_friction_signals,
    group_signals_by_zone,
)
from core.friction.router import friction_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sig(type_: str, line: int, severity: str = "medium", text: str = "sample text") -> FrictionSignal:
    """Create a FrictionSignal with sensible defaults."""
    return FrictionSignal(
        type=type_,
        severity=severity,
        line_number=line,
        text_snippet=text,
        recommendation="review",
    )


def _long_transcript(*lines: str) -> str:
    """Build a transcript with enough words (>10) to pass the short-input guard."""
    # Pad each line to ensure word count exceeds 10
    padded = [f"{line} word word word word" for line in lines]
    return "\n".join(padded)


def _app():
    """Create a FastAPI app with the friction router included."""
    app = FastAPI()
    app.include_router(friction_router)
    return app


# ===========================================================================
#  1. detect_friction_signals — rephrasing
# ===========================================================================


class TestDetectRephrasing:
    def test_detect_empty_transcript(self):
        """Empty string → Ok with empty list."""
        # Arrange
        transcript = ""

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []

    def test_detect_short_transcript(self):
        """Transcript with <10 words → Ok with empty list."""
        # Arrange
        transcript = "Hello world how are you"

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []

    def test_detect_rephrasing(self):
        """'no, that's wrong' pattern is detected as rephrasing."""
        # Arrange
        transcript = (
            "First I need you to build the module\n"
            "no, that's wrong, I need the other module\n"
            "Third line to keep word count up here"
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        signals = result.value
        assert len(signals) >= 1
        rephrase_signals = [s for s in signals if s.type == "rephrase"]
        assert len(rephrase_signals) >= 1
        assert rephrase_signals[0].severity == "medium"
        assert "no" in rephrase_signals[0].text_snippet.lower()

    def test_detect_rephrasing_actually_pattern(self):
        """'actually,' pattern is detected as rephrasing."""
        # Arrange
        transcript = _long_transcript(
            "Build the API endpoint",
            "actually, I meant the other endpoint",
            "Third line of text here",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        rephrase = [s for s in result.value if s.type == "rephrase"]
        assert len(rephrase) >= 1

    def test_detect_rephrasing_wait_pattern(self):
        """'wait,' pattern is detected as rephrasing."""
        # Arrange
        transcript = _long_transcript(
            "Start building the form",
            "wait, cancel that request please",
            "Third line to satisfy word count",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        rephrase = [s for s in result.value if s.type == "rephrase"]
        assert len(rephrase) >= 1

    def test_detect_rephrasing_i_meant_pattern(self):
        """'I meant' pattern is detected as rephrasing."""
        # Arrange
        transcript = _long_transcript(
            "Please update the database schema",
            "I meant the user table schema only",
            "Another line here for the word count",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        rephrase = [s for s in result.value if s.type == "rephrase"]
        assert len(rephrase) >= 1

    def test_detect_rephrasing_thats_wrong_pattern(self):
        """That's wrong pattern is detected as rephrasing."""
        # Arrange
        transcript = _long_transcript(
            "Deploy to staging environment first",
            "that's wrong deploy to production instead",
            "Third line here for more content",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        rephrase = [s for s in result.value if s.type == "rephrase"]
        assert len(rephrase) >= 1


# ===========================================================================
#  2. detect_friction_signals — retry loops
# ===========================================================================


class TestDetectRetries:
    def test_detect_retry_loop(self):
        """Same instruction appearing twice → retry signal."""
        # Arrange
        transcript = (
            "Please generate the API documentation now\n"
            "Generate the API documentation now please\n"
            "Generate the API documentation now thanks"
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        signals = result.value
        retry_signals = [s for s in signals if s.type == "retry"]
        assert len(retry_signals) >= 1
        assert retry_signals[0].severity == "high"

    def test_detect_retries_pattern_single(self):
        """Single occurrence of instruction → no retry signal."""
        # Arrange
        transcript = _long_transcript(
            "Please build the authentication module completely",
            "Second unique line with different content here",
            "Third unique line for the word count",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        retry = [s for s in result.value if s.type == "retry"]
        assert len(retry) == 0


# ===========================================================================
#  3. detect_friction_signals — rapid edits
# ===========================================================================


class TestDetectRapidEdits:
    def test_detect_rapid_edits(self):
        """Cluster of short lines → rapid_edit signal."""
        # Arrange
        transcript = (
            "Fix it\n"
            "No wait\n"
            "Try again\n"
            "One more thing\n"
            "And this"
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        signals = result.value
        rapid = [s for s in signals if s.type == "rapid_edit"]
        assert len(rapid) >= 1
        assert rapid[0].severity == "medium"

    def test_detect_rapid_edits_cluster(self):
        """Many short lines in a row → rapid edit signal detected."""
        # Arrange
        lines = [f"short line {i}" for i in range(10)]
        transcript = "\n".join(lines)

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        rapid = [s for s in result.value if s.type == "rapid_edit"]
        assert len(rapid) >= 1

    def test_no_rapid_edits_with_long_lines(self):
        """Long lines should not trigger rapid_edit signals."""
        # Arrange
        long_line = "x " * 40  # > 60 chars
        transcript = "\n".join([long_line] * 5)

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        rapid = [s for s in result.value if s.type == "rapid_edit"]
        assert len(rapid) == 0


# ===========================================================================
#  4. detect_friction_signals — escalation
# ===========================================================================


class TestDetectEscalation:
    def test_detect_escalation(self):
        """'as I said' is detected as escalation."""
        # Arrange
        transcript = _long_transcript(
            "Please set up the environment properly",
            "as I said this needs to be production ready",
            "Third line for the word count requirement",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        signals = result.value
        escalation = [s for s in signals if s.type == "escalation"]
        assert len(escalation) >= 1
        assert escalation[0].severity == "high"

    def test_detect_escalation_for_the_last_time(self):
        """'for the last time' pattern triggers escalation."""
        # Arrange
        transcript = _long_transcript(
            "Build the dashboard module please",
            "for the last time I need this done right",
            "Third line here for word count needs",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        escalation = [s for s in result.value if s.type == "escalation"]
        assert len(escalation) >= 1

    def test_detect_escalation_how_many_times(self):
        """'how many times' pattern triggers escalation."""
        # Arrange
        transcript = _long_transcript(
            "Create the user profile page",
            "how many times do I have to repeat myself",
            "Third line here for word count needs",
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        escalation = [s for s in result.value if s.type == "escalation"]
        assert len(escalation) >= 1

    def test_detect_escalation_bare_dammit(self):
        """'dammit'/'damnit'/'damn it' (no 'god' prefix) trigger escalation —
        previously only the 'goddamn(it)' family was covered."""
        transcript = _long_transcript(
            "Deploy the new build",
            "dammit, this broke again",
            "Third line here for word count needs",
        )

        result = detect_friction_signals(transcript)

        assert isinstance(result, Ok)
        escalation = [s for s in result.value if s.type == "escalation"]
        assert len(escalation) >= 1

    def test_detect_escalation_piss(self):
        """'piss'/'pissed' triggers escalation."""
        transcript = _long_transcript(
            "Run the deploy script",
            "pissed off that this keeps happening",
            "Third line here for word count needs",
        )

        result = detect_friction_signals(transcript)

        assert isinstance(result, Ok)
        escalation = [s for s in result.value if s.type == "escalation"]
        assert len(escalation) >= 1

    def test_dam_alone_does_not_trigger_escalation(self):
        """Bare 'dam' (e.g. discussing a real dam) must not false-positive."""
        transcript = _long_transcript(
            "Research hydroelectric dam levels",
            "the dam release schedule looks fine",
            "Third line here for word count needs",
        )

        result = detect_friction_signals(transcript)

        assert isinstance(result, Ok)
        escalation = [s for s in result.value if s.type == "escalation"]
        assert len(escalation) == 0


# ===========================================================================
#  5. detect_friction_signals — mixed signals
# ===========================================================================


class TestDetectMixedSignals:
    def test_detect_mixed_signals(self):
        """Transcript with multiple friction types → all detected."""
        # Arrange
        transcript = (
            "Please build the login page properly\n"
            "actually I meant the signup page instead\n"
            "Build the signup page\n"
            "Build the signup page\n"
            "as I said we need the signup page\n"
            "Fix it\n"
            "No wait\n"
            "Try again\n"
            "One more thing here\n"
            "And this final line too"
        )

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Ok)
        signals = result.value
        types = {s.type for s in signals}
        assert len(types) >= 3  # at least rephrase, retry, and one more


# ===========================================================================
#  6. detect_friction_signals — error paths
# ===========================================================================


class TestDetectFrictionSignalsError:
    def test_non_string_input_returns_err(self):
        """Non-string input → Err with TYPE_ERROR."""
        # Arrange
        transcript = 12345

        # Act
        result = detect_friction_signals(transcript)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "TYPE_ERROR"
        assert "string" in result.error.lower()

    def test_none_input_returns_err(self):
        """None input → Err with TYPE_ERROR."""
        # Arrange / Act
        result = detect_friction_signals(None)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "TYPE_ERROR"

    def test_list_input_returns_err(self):
        """List input → Err with TYPE_ERROR."""
        # Arrange / Act
        result = detect_friction_signals(["not", "a", "string"])

        # Assert
        assert isinstance(result, Err)
        assert result.code == "TYPE_ERROR"


# ===========================================================================
#  7. compute_friction_score
# ===========================================================================


class TestComputeFrictionScore:
    def test_compute_friction_score(self):
        """Weighted score from signals with known severities."""
        # Arrange
        signals = [
            _sig("rephrase", 1, severity="medium"),
            _sig("retry", 2, severity="high"),
            _sig("escalation", 3, severity="high"),
        ]

        # Act
        score = compute_friction_score(signals)

        # Assert
        assert isinstance(score, float)
        assert 0.0 < score <= 1.0
        # medium=0.6 + high=1.0 + high=1.0 = 2.6 / 10 = 0.26 + density bonus
        assert score > 0.25

    def test_compute_friction_score_empty(self):
        """No signals → 0.0."""
        # Arrange
        signals = []

        # Act
        score = compute_friction_score(signals)

        # Assert
        assert score == 0.0

    def test_compute_friction_score_range(self):
        """Score is always between 0.0 and 1.0 inclusive."""
        # Arrange
        signals = [_sig("rephrase", i, severity="high") for i in range(1, 20)]

        # Act
        score = compute_friction_score(signals)

        # Assert
        assert 0.0 <= score <= 1.0

    def test_compute_friction_score_single_signal(self):
        """Single signal produces a valid, non-zero score."""
        # Arrange
        signals = [_sig("rephrase", 1, severity="medium")]

        # Act
        score = compute_friction_score(signals)

        # Assert
        assert score > 0.0
        assert score <= 1.0

    def test_compute_friction_score_density_bonus(self):
        """Signals in tight cluster get density bonus."""
        # Arrange — 5 high-severity signals in 3 lines
        signals = [
            _sig("rephrase", 1, severity="high"),
            _sig("retry", 2, severity="high"),
            _sig("escalation", 3, severity="high"),
        ]

        # Act
        score = compute_friction_score(signals)

        # Assert
        assert score > 0.3  # density bonus pushes above raw

    def test_compute_friction_score_capped_at_one(self):
        """Very many high signals still capped at 1.0."""
        # Arrange
        signals = [_sig("high", i, severity="high") for i in range(1, 30)]

        # Act
        score = compute_friction_score(signals)

        # Assert
        assert score == 1.0


# ===========================================================================
#  8. group_signals_by_zone
# ===========================================================================


class TestGroupSignalsByZone:
    def test_group_signals_by_zone(self):
        """Nearby signals (within 5 lines) are grouped into one zone."""
        # Arrange
        signals = [
            _sig("rephrase", 1, severity="high"),
            _sig("retry", 3),
            _sig("escalation", 5),
        ]

        # Act
        zones = group_signals_by_zone(signals)

        # Assert
        assert len(zones) == 1
        assert zones[0].start_line == 1
        assert zones[0].end_line == 5
        assert len(zones[0].signals) == 3
        assert zones[0].zone_severity == "high"  # highest severity in zone

    def test_group_signals_distant(self):
        """Far-apart signals (beyond 5 lines) stay in separate zones."""
        # Arrange
        signals = [
            _sig("rephrase", 1),
            _sig("retry", 20),
            _sig("escalation", 50),
        ]

        # Act
        zones = group_signals_by_zone(signals)

        # Assert
        assert len(zones) == 3
        assert zones[0].start_line == 1
        assert zones[1].start_line == 20
        assert zones[2].start_line == 50

    def test_group_signals_empty(self):
        """Empty signal list → no zones."""
        # Arrange
        signals = []

        # Act
        zones = group_signals_by_zone(signals)

        # Assert
        assert zones == []

    def test_group_signals_multiple_zones(self):
        """Signals form two distinct clusters."""
        # Arrange
        signals = [
            _sig("rephrase", 1),
            _sig("retry", 3),
            # gap of 10 lines
            _sig("escalation", 13),
            _sig("rapid_edit", 15),
        ]

        # Act
        zones = group_signals_by_zone(signals)

        # Assert
        assert len(zones) == 2
        assert zones[0].start_line == 1
        assert zones[0].end_line == 3
        assert zones[1].start_line == 13
        assert zones[1].end_line == 15

    def test_zone_severity_derived_from_max_signal(self):
        """Zone severity is derived from the highest severity signal."""
        # Arrange
        signals = [
            _sig("rephrase", 1, severity="low"),
            _sig("retry", 2, severity="medium"),
        ]

        # Act
        zones = group_signals_by_zone(signals)

        # Assert
        assert len(zones) == 1
        assert zones[0].zone_severity == "medium"

    def test_zone_description_includes_signal_types(self):
        """Zone description lists the unique signal types."""
        # Arrange
        signals = [
            _sig("rephrase", 1),
            _sig("retry", 2),
            _sig("rephrase", 3),
        ]

        # Act
        zones = group_signals_by_zone(signals)

        # Assert
        assert len(zones) == 1
        desc = zones[0].description
        assert "rephrase" in desc
        assert "retry" in desc


# ===========================================================================
#  9. _build_zone helper
# ===========================================================================


class TestBuildZone:
    def test_build_zone_all_types(self):
        """Zone with all signal types lists them correctly."""
        # Arrange
        signals = [
            _sig("rephrase", 1, severity="low"),
            _sig("retry", 2, severity="medium"),
            _sig("escalation", 3, severity="high"),
            _sig("rapid_edit", 4, severity="medium"),
        ]

        # Act
        zone = _build_zone(signals)

        # Assert
        assert isinstance(zone, FrictionZone)
        assert zone.start_line == 1
        assert zone.end_line == 4
        assert zone.zone_severity == "high"

    def test_build_zone_low_only(self):
        """Zone with only low-severity signals → low zone severity."""
        # Arrange
        signals = [_sig("rephrase", 1, severity="low")]

        # Act
        zone = _build_zone(signals)

        # Assert
        assert zone.zone_severity == "low"


# ===========================================================================
#  9.5. compute_friction_by_agent — pure filter/aggregate over friction_history
# ===========================================================================


class TestComputeFrictionByAgent:
    def test_no_history_for_agent(self):
        result = compute_friction_by_agent([], "Claude")
        assert result == {
            "agent_name": "Claude",
            "total_scans": 0,
            "avg_friction_score": 0.0,
            "severity_totals": {},
        }

    def test_filters_to_one_agent_only(self):
        history = [
            {"friction_score": 0.5, "severity_distribution": {"medium": 1}, "agent_name": "Claude"},
            {"friction_score": 0.9, "severity_distribution": {"high": 2}, "agent_name": "Gemini"},
        ]
        result = compute_friction_by_agent(history, "Claude")
        assert result["total_scans"] == 1
        assert result["avg_friction_score"] == 0.5
        assert result["severity_totals"] == {"medium": 1}

    def test_averages_across_multiple_scans_for_same_agent(self):
        history = [
            {"friction_score": 0.2, "severity_distribution": {}, "agent_name": "Claude"},
            {"friction_score": 0.8, "severity_distribution": {}, "agent_name": "Claude"},
        ]
        result = compute_friction_by_agent(history, "Claude")
        assert result["total_scans"] == 2
        assert result["avg_friction_score"] == 0.5

    def test_severity_totals_summed_across_scans(self):
        history = [
            {"friction_score": 0.3, "severity_distribution": {"low": 1, "medium": 1}, "agent_name": "Claude"},
            {"friction_score": 0.3, "severity_distribution": {"medium": 2}, "agent_name": "Claude"},
        ]
        result = compute_friction_by_agent(history, "Claude")
        assert result["severity_totals"] == {"low": 1, "medium": 3}

    def test_entries_missing_agent_name_bucket_as_unspecified(self):
        """Pre-agent-identity history entries never had agent_name at all —
        must not crash, and must be treated as 'unspecified'."""
        history = [{"friction_score": 0.4, "severity_distribution": {}}]
        assert compute_friction_by_agent(history, "unspecified")["total_scans"] == 1
        assert compute_friction_by_agent(history, "Claude")["total_scans"] == 0

    def test_blank_agent_normalises_to_unspecified(self):
        history = [{"friction_score": 0.4, "severity_distribution": {}, "agent_name": "unspecified"}]
        assert compute_friction_by_agent(history, "  ")["total_scans"] == 1
        assert compute_friction_by_agent(history, "")["total_scans"] == 1


# ===========================================================================
#  10. Router — POST /api/memory/{project}/friction/scan
# ===========================================================================


class TestFrictionRouterScan:
    def test_router_scan_success(self):
        """POST with valid transcript and known project → 200 with signals."""
        # Arrange
        transcript = (
            "Please build the login page properly\n"
            "no, that's wrong, build the signup page\n"
            "Build the signup page\n"
            "Build the signup page\n"
        )
        mock_memory = {"decisions": [], "session_history": []}

        # Act — also patch save_project_memory: the scan endpoint now
        # persists friction_history (previously read-only), and without this
        # patch it writes mock_memory to a real memory/test-project.json in
        # the live repo via the real _mm instance.
        with patch("core.friction.router._load_memory", return_value=mock_memory), \
             patch("core.friction.router._mm.save_project_memory") as mock_save:
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/test-project/friction/scan",
                        json={"transcript": transcript},
                    )
            resp = asyncio.run(_call())

        assert mock_save.called

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert "signals" in body
        assert "friction_score" in body
        assert "zones" in body
        assert "total_signals" in body
        assert "severity_distribution" in body
        assert isinstance(body["signals"], list)
        assert isinstance(body["friction_score"], float)
        assert 0.0 <= body["friction_score"] <= 1.0
        assert isinstance(body["zones"], list)

    def test_router_scan_empty_transcript(self):
        """POST with empty transcript → 422 validation error."""
        # Arrange
        mock_memory = {"decisions": []}

        # Act
        with patch("core.friction.router._load_memory", return_value=mock_memory):
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/test-project/friction/scan",
                        json={"transcript": ""},
                    )
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_scan_404_missing_project(self):
        """POST with unknown project → 404."""
        # Arrange
        from fastapi import HTTPException

        def _raise_404(project):
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

        # Act
        with patch("core.friction.router._load_memory", side_effect=_raise_404):
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/nonexistent-project/friction/scan",
                        json={"transcript": "some transcript text here"},
                    )
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404
        body = resp.json()
        assert "not found" in body["detail"].lower()

    def test_router_scan_500_load_error(self):
        """POST where _load_memory raises non-HTTP error → 500."""
        # Arrange
        def _raise_generic(project):
            raise RuntimeError("disk I/O failure")

        # Act
        with patch("core.friction.router._load_memory", side_effect=_raise_generic):
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/test-project/friction/scan",
                        json={"transcript": "some transcript text here"},
                    )
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 500

    def test_router_scan_missing_body_field(self):
        """POST without transcript field → 422."""
        # Arrange
        mock_memory = {"decisions": []}

        # Act
        with patch("core.friction.router._load_memory", return_value=mock_memory):
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/test-project/friction/scan",
                        json={},
                    )
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_scan_persists_agent_name(self):
        """agent_name in the request body is normalised and stored on the
        friction_history entry the scan writes."""
        mock_memory = {"decisions": []}

        with patch("core.friction.router._load_memory", return_value=mock_memory), \
             patch("core.friction.router._mm.save_project_memory") as mock_save:
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/test-project/friction/scan",
                        json={"transcript": "no thats wrong, try again", "agent_name": "  Claude  "},
                    )
            resp = asyncio.run(_call())

        assert resp.status_code == 200
        saved_memory = mock_save.call_args[0][1]
        assert saved_memory["friction_history"][-1]["agent_name"] == "Claude"

    def test_router_scan_defaults_agent_name_to_unspecified(self):
        """No agent_name in the request body → stored as 'unspecified', not omitted."""
        mock_memory = {"decisions": []}

        with patch("core.friction.router._load_memory", return_value=mock_memory), \
             patch("core.friction.router._mm.save_project_memory") as mock_save:
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/test-project/friction/scan",
                        json={"transcript": "no thats wrong, try again"},
                    )
            resp = asyncio.run(_call())

        assert resp.status_code == 200
        saved_memory = mock_save.call_args[0][1]
        assert saved_memory["friction_history"][-1]["agent_name"] == "unspecified"

    def test_router_scan_empty_agent_name_falls_back_gracefully(self):
        """Explicit agent_name="" must default to 'unspecified' like an
        omitted field, not 422 — consistent with SkillRecordRequest and
        SessionRecordRequest, neither of which requires min_length."""
        mock_memory = {"decisions": []}

        with patch("core.friction.router._load_memory", return_value=mock_memory), \
             patch("core.friction.router._mm.save_project_memory") as mock_save:
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/memory/test-project/friction/scan",
                        json={"transcript": "no thats wrong, try again", "agent_name": ""},
                    )
            resp = asyncio.run(_call())

        assert resp.status_code == 200
        saved_memory = mock_save.call_args[0][1]
        assert saved_memory["friction_history"][-1]["agent_name"] == "unspecified"


# ===========================================================================
#  10.5. Router — GET /api/memory/{project}/friction/summary/{agent}
# ===========================================================================


class TestFrictionSummaryByAgentRouter:
    def test_summary_scoped_to_one_agent(self):
        mock_memory = {
            "friction_history": [
                {"friction_score": 0.5, "severity_distribution": {"medium": 1}, "agent_name": "Claude"},
                {"friction_score": 0.9, "severity_distribution": {"high": 1}, "agent_name": "Gemini"},
            ]
        }

        with patch("core.friction.router._load_memory", return_value=mock_memory):
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.get("/api/memory/test-project/friction/summary/Claude")
            resp = asyncio.run(_call())

        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_name"] == "Claude"
        assert body["total_scans"] == 1
        assert body["avg_friction_score"] == 0.5

    def test_summary_unknown_agent_returns_zeroed_result_not_404(self):
        mock_memory = {"friction_history": []}

        with patch("core.friction.router._load_memory", return_value=mock_memory):
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.get("/api/memory/test-project/friction/summary/NoSuchAgent")
            resp = asyncio.run(_call())

        assert resp.status_code == 200
        assert resp.json()["total_scans"] == 0

    def test_summary_404_missing_project(self):
        from fastapi import HTTPException

        def _raise_404(project):
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

        with patch("core.friction.router._load_memory", side_effect=_raise_404):
            async def _call():
                async with AsyncClient(
                    transport=ASGITransport(app=_app()), base_url="http://test"
                ) as client:
                    return await client.get("/api/memory/nonexistent/friction/summary/Claude")
            resp = asyncio.run(_call())

        assert resp.status_code == 404


# ===========================================================================
#  11. Integration — end-to-end miner flow
# ===========================================================================


class TestMinerIntegration:
    def test_full_pipeline_returns_zones_and_score(self):
        """Full pipeline: detect → score → group produces coherent output."""
        # Arrange
        transcript = (
            "Please build the login page\n"
            "actually I meant the signup page\n"
            "Build the signup page\n"
            "Build the signup page\n"
            "as I said the signup page\n"
            "Fix it\n"
            "No wait\n"
            "Try again\n"
            "One more thing\n"
            "And this last one too"
        )

        # Act
        result = detect_friction_signals(transcript)
        assert isinstance(result, Ok)
        signals = result.value
        score = compute_friction_score(signals)
        zones = group_signals_by_zone(signals)

        # Assert
        assert len(signals) > 0
        assert 0.0 < score <= 1.0
        assert len(zones) >= 1
        for zone in zones:
            assert zone.start_line <= zone.end_line
            assert zone.zone_severity in ("low", "medium", "high")

    def test_clean_transcript_no_signals(self):
        """Transcript with no friction patterns → no signals, score 0.0."""
        # Arrange
        transcript = _long_transcript(
            "Please build the authentication module completely",
            "I have built the authentication module with JWT support",
            "The module includes login, logout and refresh token endpoints",
        )

        # Act
        result = detect_friction_signals(transcript)
        assert isinstance(result, Ok)
        signals = result.value
        score = compute_friction_score(signals)
        zones = group_signals_by_zone(signals)

        # Assert
        assert len(signals) == 0
        assert score == 0.0
        assert zones == []
