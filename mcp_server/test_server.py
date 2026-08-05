"""Tests for the Tropelex MCP tool wrappers.

Each @mcp.tool() function is still a plain async function under the
decorator, so these tests call them directly and monkeypatch _request to
capture the REST call it would have made, without needing a live server.
"""

from __future__ import annotations

import pytest

import server


class _Recorder:
    """Stand-in for _request that records its call and returns a fixed body."""

    def __init__(self, response: dict | None = None):
        self.response = response or {"ok": True}
        self.calls: list[tuple[str, str, dict | None]] = []

    async def __call__(self, method, path, json=None):
        self.calls.append((method, path, json))
        return self.response


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(server, "_request", rec)
    return rec


class TestEndSessionAgentAttribution:
    @pytest.mark.asyncio
    async def test_passes_agent_name_through_to_request_body(self, recorder):
        await server.end_session("proj", "did stuff", agent="Claude")

        method, path, body = recorder.calls[0]
        assert method == "POST"
        assert path == "/api/memory/proj/sessions/record"
        assert body["agent_name"] == "Claude"
        assert body["summary"] == "did stuff"

    @pytest.mark.asyncio
    async def test_defaults_to_unspecified_when_agent_omitted(self, recorder):
        await server.end_session("proj", "did stuff")

        _, _, body = recorder.calls[0]
        assert body["agent_name"] == "unspecified"


class TestFrictionScanAgentAttribution:
    @pytest.mark.asyncio
    async def test_passes_agent_name_through_to_request_body(self, recorder):
        await server.friction_scan("proj", "no thats wrong, try again", agent="Gemini")

        method, path, body = recorder.calls[0]
        assert method == "POST"
        assert path == "/api/memory/proj/friction/scan"
        assert body["agent_name"] == "Gemini"
        assert body["transcript"] == "no thats wrong, try again"

    @pytest.mark.asyncio
    async def test_defaults_to_unspecified_when_agent_omitted(self, recorder):
        await server.friction_scan("proj", "some transcript")

        _, _, body = recorder.calls[0]
        assert body["agent_name"] == "unspecified"


class TestRecordSkillOutcome:
    @pytest.mark.asyncio
    async def test_hits_agent_skills_record_endpoint_with_full_payload(self, recorder):
        await server.record_skill_outcome(
            "proj", "bugfix", ["ui", "testing"],
            outcome="success", details="fixed the thing", agent="Claude",
        )

        method, path, body = recorder.calls[0]
        assert method == "POST"
        assert path == "/api/memory/proj/agent-skills/record"
        assert body == {
            "session_type": "bugfix",
            "categories": ["ui", "testing"],
            "outcome": "success",
            "details": "fixed the thing",
            "agent_name": "Claude",
        }

    @pytest.mark.asyncio
    async def test_defaults_outcome_details_and_agent(self, recorder):
        await server.record_skill_outcome("proj", "refactor", ["backend"])

        _, _, body = recorder.calls[0]
        assert body["outcome"] == "success"
        assert body["details"] == ""
        assert body["agent_name"] == "unspecified"


class TestProjectNameUrlEscaping:
    @pytest.mark.asyncio
    async def test_end_session_quotes_project_with_special_characters(self, recorder):
        await server.end_session("my project/v2", "summary", agent="Claude")

        _, path, _ = recorder.calls[0]
        assert path == "/api/memory/my%20project%2Fv2/sessions/record"
