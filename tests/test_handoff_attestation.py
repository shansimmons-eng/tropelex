"""
Tests for #108 (Handoff Acknowledgment -> Constraint Attestation): the
handoff_created audit event now carries must_survive_decision_ids, and
acknowledge_handoff cross-checks a receiver's acknowledged_constraints
against it -- distinct from just recording that *some* packet was acked.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.handoff.packet_builder import build_handoff_packet


def _decision(text, ts=None, **extra):
    d = {
        "decision": text,
        "context": "",
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "categories": [],
    }
    d.update(extra)
    return d


def _app():
    from fastapi import FastAPI
    from core.handoff.router import handoff_router

    app = FastAPI()
    app.include_router(handoff_router)
    return app


class TestPacketBuilderMustSurviveIds:
    """core.handoff.packet_builder.build_handoff_packet: the new field."""

    def test_no_must_survive_decisions_gives_empty_list(self):
        memory = {"decisions": [_decision("Use FastAPI for REST endpoints")], "session_history": [], "goals": []}
        packet = build_handoff_packet(project="p", role="CoderAgent", memory=memory)
        assert packet.must_survive_decision_ids == []

    def test_explicit_must_survive_decision_id_included(self):
        memory = {
            "decisions": [_decision(
                "Never disable authentication checks in the payment flow",
                id="db-critical", must_survive=True,
            )],
            "session_history": [], "goals": [],
        }
        packet = build_handoff_packet(project="p", role="CoderAgent", memory=memory)
        assert packet.must_survive_decision_ids == ["db-critical"]

    def test_high_risk_metadata_derived_must_survive_included(self):
        memory = {
            "decisions": [_decision(
                "Never disable authentication checks in the payment flow",
                id="db-critical", safety_metadata={"risk_level": "critical"},
            )],
            "session_history": [], "goals": [],
        }
        packet = build_handoff_packet(project="p", role="CoderAgent", memory=memory)
        assert packet.must_survive_decision_ids == ["db-critical"]

    def test_decision_with_no_id_is_excluded_not_crashed(self):
        """A must-survive decision missing an id can't be attested against
        by id -- excluded defensively rather than including a falsy id
        that could never match a real acknowledged_constraints entry."""
        memory = {
            "decisions": [_decision(
                "Never disable authentication checks in the payment flow",
                must_survive=True,
            )],
            "session_history": [], "goals": [],
        }
        packet = build_handoff_packet(project="p", role="CoderAgent", memory=memory)
        assert packet.must_survive_decision_ids == []

    def test_non_must_survive_decision_excluded(self):
        memory = {
            "decisions": [_decision("Use FastAPI for REST endpoints", id="d1")],
            "session_history": [], "goals": [],
        }
        packet = build_handoff_packet(project="p", role="CoderAgent", memory=memory)
        assert packet.must_survive_decision_ids == []


class TestGenerateHandoffCarriesMustSurviveIds:
    """POST /{project}/handoff response + audit event now include it."""

    @contextmanager
    def _mock_load(self, memory):
        memory_copy = copy.deepcopy(memory)
        with patch("core.handoff.router._load_memory", return_value=memory_copy), \
             patch("core.handoff.router._mm.save_project_memory") as mock_save:
            yield mock_save, memory_copy

    async def test_response_includes_must_survive_decision_ids(self):
        from httpx import ASGITransport, AsyncClient

        memory = {
            "decisions": [_decision(
                "Never disable authentication checks in the payment flow",
                id="db-critical", must_survive=True,
            )],
            "session_history": [], "goals": [], "patterns": [],
        }
        with self._mock_load(memory):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff", json={"role": "CoderAgent", "token_budget": 4000},
                )

        assert resp.status_code == 200
        assert resp.json()["must_survive_decision_ids"] == ["db-critical"]

    async def test_handoff_created_audit_event_includes_must_survive_decision_ids(self):
        from httpx import ASGITransport, AsyncClient

        memory = {
            "decisions": [_decision(
                "Never disable authentication checks in the payment flow",
                id="db-critical", must_survive=True,
            )],
            "session_history": [], "goals": [], "patterns": [],
        }
        with self._mock_load(memory) as (_, memory_copy):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                await client.post(
                    "/api/memory/tropelex/handoff", json={"role": "CoderAgent", "token_budget": 4000},
                )

        created = next(e for e in memory_copy["audit_log"] if e["event_type"] == "handoff_created")
        assert created["must_survive_decision_ids"] == ["db-critical"]


class TestAcknowledgeAttestation:
    """POST /{project}/handoff/acknowledge's cross-check against the
    originating packet's must_survive_decision_ids."""

    @contextmanager
    def _mock_load(self, memory):
        memory_copy = copy.deepcopy(memory)
        with patch("core.handoff.router._load_memory", return_value=memory_copy), \
             patch("core.handoff.router._mm.save_project_memory") as mock_save:
            yield mock_save, memory_copy

    def _memory_with_handoff(self, packet_hash="abc123", must_survive_decision_ids=None):
        return {
            "decisions": [], "session_history": [], "goals": [], "patterns": [],
            "audit_log": [{
                "event_type": "handoff_created",
                "timestamp": "2026-08-10T00:00:00+00:00",
                "previous_hash": "genesis",
                "role": "CoderAgent",
                "agent_name": "Claude",
                "packet_hash": packet_hash,
                "must_survive_decision_ids": must_survive_decision_ids or [],
                "hash": "deadbeef",
            }],
        }

    async def test_all_constraints_acknowledged_is_fully_attested(self):
        from httpx import ASGITransport, AsyncClient

        memory = self._memory_with_handoff("abc123", ["db-critical", "db-other"])
        with self._mock_load(memory) as (_, memory_copy):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge",
                    json={"packet_hash": "abc123", "acknowledged_constraints": ["db-critical", "db-other"]},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["fully_attested"] is True
        assert body["missing_constraints"] == []
        event = next(e for e in memory_copy["audit_log"] if e["event_type"] == "handoff_acknowledged")
        assert event["fully_attested"] is True
        assert event["missing_constraints"] == []

    async def test_partial_acknowledgment_reports_missing_constraints(self):
        from httpx import ASGITransport, AsyncClient

        memory = self._memory_with_handoff("abc123", ["db-critical", "db-other"])
        with self._mock_load(memory) as (_, memory_copy):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge",
                    json={"packet_hash": "abc123", "acknowledged_constraints": ["db-critical"]},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["fully_attested"] is False
        assert body["missing_constraints"] == ["db-other"]
        event = next(e for e in memory_copy["audit_log"] if e["event_type"] == "handoff_acknowledged")
        assert event["fully_attested"] is False
        assert event["missing_constraints"] == ["db-other"]

    async def test_no_acknowledged_constraints_at_all_lists_everything_missing(self):
        from httpx import ASGITransport, AsyncClient

        memory = self._memory_with_handoff("abc123", ["db-critical"])
        with self._mock_load(memory):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge", json={"packet_hash": "abc123"},
                )

        body = resp.json()
        assert body["fully_attested"] is False
        assert body["missing_constraints"] == ["db-critical"]

    async def test_no_must_survive_decisions_is_trivially_fully_attested(self):
        from httpx import ASGITransport, AsyncClient

        memory = self._memory_with_handoff("abc123", [])
        with self._mock_load(memory):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge", json={"packet_hash": "abc123"},
                )

        assert resp.json()["fully_attested"] is True
        assert resp.json()["missing_constraints"] == []

    async def test_pre_108_event_with_no_must_survive_key_is_trivially_attested(self):
        """A handoff_created event from before this field existed has no
        must_survive_decision_ids key at all -- treated as an empty list
        (nothing to attest against), not an error."""
        from httpx import ASGITransport, AsyncClient

        memory = self._memory_with_handoff("abc123")
        del memory["audit_log"][0]["must_survive_decision_ids"]
        with self._mock_load(memory):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge", json={"packet_hash": "abc123"},
                )

        assert resp.status_code == 200
        assert resp.json()["fully_attested"] is True


class TestIncompletelyAttestedHandoffs:
    """Pure-function tests for _incompletely_attested_handoffs, and the
    GET /{project}/handoff/incomplete-attestations endpoint."""

    def test_no_audit_log_returns_empty(self):
        from core.handoff.router import _incompletely_attested_handoffs
        assert _incompletely_attested_handoffs({}) == []

    def test_fully_attested_ack_is_excluded(self):
        from core.handoff.router import _incompletely_attested_handoffs
        memory = {"audit_log": [
            {"event_type": "handoff_acknowledged", "packet_hash": "h1", "fully_attested": True, "missing_constraints": []},
        ]}
        assert _incompletely_attested_handoffs(memory) == []

    def test_partially_attested_ack_is_included(self):
        from core.handoff.router import _incompletely_attested_handoffs
        memory = {"audit_log": [
            {
                "event_type": "handoff_acknowledged", "packet_hash": "h1", "agent_name": "Claude",
                "fully_attested": False, "missing_constraints": ["db-critical"], "timestamp": "t1",
            },
        ]}
        result = _incompletely_attested_handoffs(memory)
        assert len(result) == 1
        assert result[0]["packet_hash"] == "h1"
        assert result[0]["missing_constraints"] == ["db-critical"]

    def test_pre_108_ack_with_no_fully_attested_key_is_excluded(self):
        """No fully_attested key at all (pre-#108 event) is neither
        "attested" nor "known-incomplete" -- excluded, not surfaced as a
        false alarm."""
        from core.handoff.router import _incompletely_attested_handoffs
        memory = {"audit_log": [
            {"event_type": "handoff_acknowledged", "packet_hash": "h1", "acknowledged_constraints": []},
        ]}
        assert _incompletely_attested_handoffs(memory) == []

    def test_malformed_entries_skipped_not_crashed(self):
        from core.handoff.router import _incompletely_attested_handoffs
        memory = {"audit_log": ["not a dict", None, 42, {"event_type": "handoff_acknowledged", "fully_attested": False}]}
        result = _incompletely_attested_handoffs(memory)
        assert len(result) == 1

    async def test_endpoint_returns_incomplete_attestations(self):
        from httpx import ASGITransport, AsyncClient

        memory = {"audit_log": [
            {
                "event_type": "handoff_acknowledged", "packet_hash": "h1", "agent_name": "Claude",
                "fully_attested": False, "missing_constraints": ["db-critical"], "timestamp": "t1",
            },
        ]}
        with patch("core.handoff.router._mm.get_project_memory", return_value=memory):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.get("/api/memory/tropelex/handoff/incomplete-attestations")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["incomplete_attestations"][0]["packet_hash"] == "h1"

    async def test_endpoint_nonexistent_project_returns_empty_not_404(self):
        """Same lenient get_project_memory posture as the sibling
        unacknowledged/completeness-violations endpoints -- Needs
        Attention calls this for every project unconditionally."""
        from httpx import ASGITransport, AsyncClient

        with patch("core.handoff.router._mm.get_project_memory", return_value={"audit_log": []}):
            async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
                resp = await client.get("/api/memory/does-not-exist/handoff/incomplete-attestations")

        assert resp.status_code == 200
        assert resp.json() == {"incomplete_attestations": [], "count": 0}
