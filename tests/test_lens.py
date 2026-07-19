"""
Tests for Memory Lens — annotator pure functions.
Covers: detect_drift, map_code_to_decisions, format_annotation,
        scan_file_for_decisions.
"""

import pytest
from core.lens.annotator import (
    detect_drift,
    format_annotation,
    map_code_to_decisions,
    scan_file_for_decisions,
)
from core.lens import Annotation, Ok, Err


# ── detect_drift ───────────────────────────────────────────────────────────

class TestDetectDrift:
    def test_drift_detected(self):
        code = "import os; not using FastAPI"
        decision = {"decision": "Use FastAPI for API layer"}
        assert detect_drift(code, decision) is True

    def test_no_drift_without_negation(self):
        code = "import FastAPI"
        decision = {"decision": "Use FastAPI for API layer"}
        assert detect_drift(code, decision) is False

    def test_no_drift_without_shared_keywords(self):
        code = "not using React"
        decision = {"decision": "Use FastAPI for backend"}
        assert detect_drift(code, decision) is False

    def test_empty_code(self):
        assert detect_drift("", {"decision": "Use FastAPI"}) is False

    def test_empty_decision(self):
        assert detect_drift("code", {}) is False


# ── map_code_to_decisions ─────────────────────────────────────────────────

class TestMapCodeToDecisions:
    def test_matches_by_keyword(self):
        code = "app = FastAPI()"
        decisions = [{"id": "d1", "decision": "Use FastAPI for backend"}]
        result = map_code_to_decisions(code, decisions)
        assert isinstance(result, Ok)
        assert len(result.value) == 1
        assert result.value[0].decision_id == "d1"
        assert result.value[0].confidence > 0

    def test_no_matches(self):
        code = "import os"
        decisions = [{"id": "d1", "decision": "Use FastAPI"}]
        result = map_code_to_decisions(code, decisions)
        assert isinstance(result, Ok)
        assert len(result.value) == 0

    def test_invalid_code_type(self):
        result = map_code_to_decisions(123, [])
        assert isinstance(result, Err)

    def test_invalid_decisions_type(self):
        result = map_code_to_decisions("code", "not a list")
        assert isinstance(result, Err)

    def test_drift_relationship(self):
        code = "not using FastAPI"
        decisions = [{"id": "d1", "decision": "Use FastAPI for backend"}]
        result = map_code_to_decisions(code, decisions)
        assert result.value[0].relationship == "drifted"

    def test_sorted_by_confidence(self):
        decisions = [
            {"id": "d1", "decision": "Use FastAPI for backend"},
            {"id": "d2", "decision": "Use Python and FastAPI and uvicorn"},
        ]
        code = "FastAPI"
        result = map_code_to_decisions(code, decisions)
        if len(result.value) > 1:
            assert result.value[0].confidence >= result.value[1].confidence


# ── format_annotation ─────────────────────────────────────────────────────

class TestFormatAnnotation:
    def test_referenced_format(self):
        ann = Annotation(
            decision_id="d1", decision_text="Use FastAPI",
            confidence=0.45, line_number=10, file_path="app.py",
            relationship="referenced", reference_count=3,
        )
        text = format_annotation(ann)
        assert "🔗" in text
        assert "[REFERENCED]" in text
        assert "45%" in text

    def test_drifted_format(self):
        ann = Annotation(
            decision_id="d1", decision_text="Use FastAPI",
            confidence=0.3, line_number=5, file_path="app.py",
            relationship="drifted", reference_count=2,
        )
        text = format_annotation(ann)
        assert "⚠️" in text
        assert "[DRIFTED]" in text

    def test_truncates_long_text(self):
        long_text = "A" * 100
        ann = Annotation(
            decision_id="d1", decision_text=long_text,
            confidence=0.5, line_number=1, file_path="",
            relationship="defined", reference_count=1,
        )
        text = format_annotation(ann)
        assert "…" in text


# ── scan_file_for_decisions ───────────────────────────────────────────────

class TestScanFileForDecisions:
    def test_scan_finds_match(self):
        file_content = "import os\napp = FastAPI()\nreturn response"
        decisions = [{"id": "d1", "decision": "Use FastAPI for backend"}]
        result = scan_file_for_decisions(file_content, decisions)
        assert isinstance(result, Ok)
        assert len(result.value) >= 1
        assert result.value[0].line_number == 2  # line 2 has FastAPI

    def test_scan_no_matches(self):
        file_content = "import os\nprint('hello')"
        decisions = [{"id": "d1", "decision": "Use FastAPI"}]
        result = scan_file_for_decisions(file_content, decisions)
        assert isinstance(result, Ok)
        assert len(result.value) == 0

    def test_scan_invalid_inputs(self):
        result = scan_file_for_decisions(123, [])
        assert isinstance(result, Err)

    def test_scan_multiple_lines(self):
        file_content = "FastAPI app\nFastAPI router\nFastAPI response"
        decisions = [{"id": "d1", "decision": "Use FastAPI"}]
        result = scan_file_for_decisions(file_content, decisions)
        assert len(result.value) >= 3  # match on each line
