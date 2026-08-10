"""Tests for the Tropelex MCP tool wrappers.

Each @mcp.tool() function is still a plain async function under the
decorator, so these tests call them directly and monkeypatch _request to
capture the REST call it would have made, without needing a live server.
"""

from __future__ import annotations

import httpx
import pytest

import server


class _Recorder:
    """Stand-in for _request that records its call and returns a fixed body.

    Replaces _request entirely, so it never runs the real function body --
    the session-shape capture logic inside _request (#45) is exercised
    separately by TestRealRequestCapture, which uses httpx.MockTransport
    instead of monkeypatching _request itself.
    """

    def __init__(self, response: dict | None = None):
        self.response = response or {"ok": True}
        self.calls: list[tuple[str, str, str, dict | None]] = []

    async def __call__(self, tool_name, method, path, json=None):
        self.calls.append((tool_name, method, path, json))
        return self.response


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(server, "_request", rec)
    return rec


@pytest.fixture(autouse=True)
def _clean_session_shape_state():
    """Session-shape capture is module-level state (mcp_server/server.py,
    #45) -- reset before and after every test so no test's tool-call count
    leaks into another's."""
    server._reset_session_shape()
    yield
    server._reset_session_shape()


class TestEndSessionAgentAttribution:
    @pytest.mark.asyncio
    async def test_passes_agent_name_through_to_request_body(self, recorder):
        await server.end_session("proj", "did stuff", agent="Claude")

        tool_name, method, path, body = recorder.calls[0]
        assert method == "POST"
        assert path == "/api/memory/proj/sessions/record"
        assert body["agent_name"] == "Claude"
        assert body["summary"] == "did stuff"

    @pytest.mark.asyncio
    async def test_defaults_to_unspecified_when_agent_omitted(self, recorder):
        await server.end_session("proj", "did stuff")

        _, _, _, body = recorder.calls[0]
        assert body["agent_name"] == "unspecified"


class TestFrictionScanAgentAttribution:
    @pytest.mark.asyncio
    async def test_passes_agent_name_through_to_request_body(self, recorder):
        await server.friction_scan("proj", "no thats wrong, try again", agent="Gemini")

        tool_name, method, path, body = recorder.calls[0]
        assert method == "POST"
        assert path == "/api/memory/proj/friction/scan"
        assert body["agent_name"] == "Gemini"
        assert body["transcript"] == "no thats wrong, try again"

    @pytest.mark.asyncio
    async def test_defaults_to_unspecified_when_agent_omitted(self, recorder):
        await server.friction_scan("proj", "some transcript")

        _, _, _, body = recorder.calls[0]
        assert body["agent_name"] == "unspecified"


class TestRecordSkillOutcome:
    @pytest.mark.asyncio
    async def test_hits_agent_skills_record_endpoint_with_full_payload(self, recorder):
        await server.record_skill_outcome(
            "proj", "bugfix", ["ui", "testing"],
            outcome="success", details="fixed the thing", agent="Claude",
        )

        tool_name, method, path, body = recorder.calls[0]
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

        _, _, _, body = recorder.calls[0]
        assert body["outcome"] == "success"
        assert body["details"] == ""
        assert body["agent_name"] == "unspecified"


class TestGetHandoffPacketAgentAttribution:
    @pytest.mark.asyncio
    async def test_passes_agent_name_through_to_request_body(self, recorder):
        await server.get_handoff_packet("proj", "reviewer", agent="Gemini")

        tool_name, method, path, body = recorder.calls[0]
        assert method == "POST"
        assert path == "/api/memory/proj/handoff"
        assert body["role"] == "reviewer"
        assert body["agent_name"] == "Gemini"

    @pytest.mark.asyncio
    async def test_defaults_to_unspecified_when_agent_omitted(self, recorder):
        await server.get_handoff_packet("proj", "reviewer")

        _, _, _, body = recorder.calls[0]
        assert body["agent_name"] == "unspecified"


class TestAcknowledgeHandoff:
    @pytest.mark.asyncio
    async def test_hits_acknowledge_endpoint_with_full_payload(self, recorder):
        await server.acknowledge_handoff(
            "proj", "abc123", agent="Claude",
            acknowledged_constraints=["do not touch prod"],
        )

        tool_name, method, path, body = recorder.calls[0]
        assert method == "POST"
        assert path == "/api/memory/proj/handoff/acknowledge"
        assert body == {
            "packet_hash": "abc123",
            "agent_name": "Claude",
            "acknowledged_constraints": ["do not touch prod"],
        }

    @pytest.mark.asyncio
    async def test_defaults_agent_and_constraints(self, recorder):
        await server.acknowledge_handoff("proj", "abc123")

        _, _, _, body = recorder.calls[0]
        assert body["agent_name"] == "unspecified"
        assert body["acknowledged_constraints"] == []


class TestProjectNameUrlEscaping:
    @pytest.mark.asyncio
    async def test_end_session_quotes_project_with_special_characters(self, recorder):
        await server.end_session("my project/v2", "summary", agent="Claude")

        _, _, path, _ = recorder.calls[0]
        assert path == "/api/memory/my%20project%2Fv2/sessions/record"


# ── Session-shape capture (#45) ──────────────────────────────────────────────
# _clean_session_shape_state (top of file) resets module state before/after
# every test in this file, so these don't need their own setup/teardown.


class TestSessionShapeCapture:
    """Pure tests on the capture state machine itself -- no I/O, no
    monkeypatching. _record_tool_call is what the real _request() calls in
    its `finally`; these test its aggregation logic directly."""

    def test_no_calls_yields_none_shape(self):
        assert server._build_session_shape() is None

    def test_single_call_shape(self):
        server._record_tool_call("capture_decision", 120.0, False, 50)

        shape = server._build_session_shape()

        assert shape == {
            "tool_call_count": 1,
            "unique_tools_used": 1,
            "avg_call_duration_ms": 120.0,
            "max_call_duration_ms": 120.0,
            "error_count": 0,
            "avg_output_bytes": 50.0,
            "total_duration_s": 0.0,  # a single call has no span to measure
        }

    def test_multiple_calls_aggregate_across_tools(self):
        server._record_tool_call("capture_decision", 100.0, False, 40)
        server._record_tool_call("capture_decision", 200.0, False, 60)
        server._record_tool_call("propose_goal", 50.0, True, 999)  # error call

        shape = server._build_session_shape()

        assert shape["tool_call_count"] == 3
        assert shape["unique_tools_used"] == 2
        assert shape["avg_call_duration_ms"] == pytest.approx((100.0 + 200.0 + 50.0) / 3)
        assert shape["max_call_duration_ms"] == 200.0
        assert shape["error_count"] == 1

    def test_error_calls_excluded_from_output_bytes(self):
        """A call recorded with error=True must not count toward
        avg_output_bytes, regardless of what output_bytes value is passed
        -- an error response body isn't "output size" in the sense this
        metric means."""
        server._record_tool_call("x", 10.0, True, 999)

        shape = server._build_session_shape()

        assert shape["error_count"] == 1
        assert shape["avg_output_bytes"] == 0.0  # no successful call to average

    def test_error_calls_still_counted_in_duration_and_hang_signal(self):
        """The wishlist purpose is explicit that hang duration is part of
        what this baselines -- an errored/timed-out call's duration must
        still be recorded, not discarded."""
        server._record_tool_call("x", 30000.0, True, 0)  # e.g. the 30s httpx timeout

        shape = server._build_session_shape()

        assert shape["max_call_duration_ms"] == 30000.0

    def test_reset_clears_everything(self):
        server._record_tool_call("x", 10.0, False, 5)

        server._reset_session_shape()

        assert server._build_session_shape() is None
        assert server._call_count == 0
        assert server._error_count == 0


class TestEndSessionFlushesAndResets:
    @pytest.mark.asyncio
    async def test_session_shape_attached_when_calls_were_made(self, recorder):
        server._record_tool_call("capture_decision", 100.0, False, 40)
        server._record_tool_call("propose_goal", 50.0, False, 20)

        await server.end_session("proj", "did stuff", agent="Claude")

        _, _, _, body = recorder.calls[0]
        assert body["session_shape"]["tool_call_count"] == 2
        assert body["session_shape"]["unique_tools_used"] == 2

    @pytest.mark.asyncio
    async def test_no_session_shape_key_when_no_calls_made(self, recorder):
        await server.end_session("proj", "did stuff")

        _, _, _, body = recorder.calls[0]
        assert "session_shape" not in body

    @pytest.mark.asyncio
    async def test_state_reset_after_end_session_success(self, recorder):
        server._record_tool_call("capture_decision", 100.0, False, 40)

        await server.end_session("proj", "did stuff")

        assert server._call_count == 0
        assert server._build_session_shape() is None

    @pytest.mark.asyncio
    async def test_state_reset_after_end_session_failure(self, monkeypatch):
        server._record_tool_call("capture_decision", 100.0, False, 40)

        async def failing_request(tool_name, method, path, json=None):
            raise RuntimeError("network down")

        monkeypatch.setattr(server, "_request", failing_request)

        with pytest.raises(RuntimeError, match="network down"):
            await server.end_session("proj", "did stuff")

        assert server._call_count == 0  # reset happened despite the raise

    @pytest.mark.asyncio
    async def test_a_second_session_after_end_session_does_not_include_the_first(self, recorder):
        """Regression: a session that ends and then makes more calls (agent
        resumes) must not have its new calls silently merged with the
        already-flushed prior session's totals."""
        server._record_tool_call("capture_decision", 100.0, False, 40)
        await server.end_session("proj", "first session")

        server._record_tool_call("propose_goal", 50.0, False, 20)
        await server.end_session("proj", "second session")

        _, _, _, second_body = recorder.calls[1]
        assert second_body["session_shape"]["tool_call_count"] == 1


class TestRealRequestCapture:
    """_Recorder (used throughout this file) replaces _request() entirely,
    so it never exercises the real function body -- including the
    session-shape capture that lives inside it. These tests use
    httpx.MockTransport (a supported httpx testing feature) to run the
    actual _request() code against a fake HTTP layer instead."""

    def _patch_transport(self, monkeypatch, handler):
        transport = httpx.MockTransport(handler)
        real_async_client = server.httpx.AsyncClient

        def fake_client(*args, **kwargs):
            kwargs["transport"] = transport
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(server.httpx, "AsyncClient", fake_client)

    @pytest.mark.asyncio
    async def test_successful_call_records_duration_no_error(self, monkeypatch):
        self._patch_transport(monkeypatch, lambda req: httpx.Response(200, json={"ok": True}))

        result = await server._request("test_tool", "GET", "/api/memory")

        assert result == {"ok": True}
        shape = server._build_session_shape()
        assert shape["tool_call_count"] == 1
        assert shape["error_count"] == 0
        assert shape["avg_call_duration_ms"] >= 0
        assert shape["avg_output_bytes"] > 0

    @pytest.mark.asyncio
    async def test_error_response_recorded_as_error_and_still_raises(self, monkeypatch):
        self._patch_transport(monkeypatch, lambda req: httpx.Response(500, json={"detail": "boom"}))

        with pytest.raises(RuntimeError, match="Tropelex API error 500"):
            await server._request("test_tool", "GET", "/api/memory")

        shape = server._build_session_shape()
        assert shape["tool_call_count"] == 1
        assert shape["error_count"] == 1
        assert shape["avg_output_bytes"] == 0.0  # error call's body isn't counted as output

    @pytest.mark.asyncio
    async def test_multiple_real_calls_accumulate(self, monkeypatch):
        self._patch_transport(monkeypatch, lambda req: httpx.Response(200, json={"ok": True}))

        await server._request("tool_a", "GET", "/api/memory")
        await server._request("tool_b", "GET", "/api/memory")

        shape = server._build_session_shape()
        assert shape["tool_call_count"] == 2
        assert shape["unique_tools_used"] == 2

    @pytest.mark.asyncio
    async def test_capture_failure_never_breaks_a_successful_call(self, monkeypatch):
        """#45's explicit robustness requirement: a bug in the metrics
        bookkeeping must never take down the real tool call it's wrapping."""
        self._patch_transport(monkeypatch, lambda req: httpx.Response(200, json={"ok": True}))
        monkeypatch.setattr(
            server, "_record_tool_call",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("instrumentation bug")),
        )

        result = await server._request("test_tool", "GET", "/api/memory")

        assert result == {"ok": True}  # real result still returned despite the broken instrumentation
