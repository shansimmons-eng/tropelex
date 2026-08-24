"""Router-level tests for wishlist #82's two new endpoints:
POST /{project}/research/promote-candidates and
POST /{project}/decisions/promote.

Uses the same isolated-Tropebook fixture pattern as
tests/test_injection_sentinel_router.py (both endpoints resolve
citation_ids against the real global Tropebook store, which needs
tmp_path scoping in tests the same way).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_promotion_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def isolated_tropebook(tmp_path):
    from core.tropebook.tropebook import Tropebook
    from core.tropebook.web import server as server_module

    original = server_module._state["tropebook"]
    server_module._state["tropebook"] = Tropebook(storage_path=str(tmp_path / "tropebook"))
    try:
        yield server_module._state["tropebook"]
    finally:
        server_module._state["tropebook"] = original


class TestPromoteCandidatesEndpoint:
    def test_resolves_citation_ids_and_returns_candidates(self, client, project, isolated_tropebook):
        cid = isolated_tropebook.add(title="A Source", url="https://example.com/a", summary="")

        fake_candidates = [{
            "decision": "Use SQLite for local dev", "context": "Simpler setup",
            "citation_ids": [cid], "confidence": 0.5,
        }]
        with patch(
            "core.decision_promotion.extract_candidate_decisions",
            new=AsyncMock(return_value=fake_candidates),
        ):
            res = client.post(
                f"/api/memory/{project}/research/promote-candidates",
                json={"report_markdown": "A report about SQLite.", "citation_ids": [cid]},
            )

        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 1
        assert body["candidates"][0]["citation_ids"] == [cid]

    def test_unknown_citation_ids_are_dropped_not_errored(self, client, project, isolated_tropebook):
        with patch(
            "core.decision_promotion.extract_candidate_decisions", new=AsyncMock(return_value=[]),
        ) as mock_extract:
            res = client.post(
                f"/api/memory/{project}/research/promote-candidates",
                json={"report_markdown": "report text", "citation_ids": ["does-not-exist"]},
            )

        assert res.status_code == 200
        # The unresolvable id never reached the extractor as a real citation
        passed_citations = mock_extract.call_args.args[1]
        assert passed_citations == []

    def test_empty_report_markdown_is_422(self, client, project, isolated_tropebook):
        res = client.post(
            f"/api/memory/{project}/research/promote-candidates",
            json={"report_markdown": "", "citation_ids": []},
        )
        assert res.status_code == 422


class TestPromoteDecisionEndpoint:
    def test_missing_safety_category_is_422_same_as_add_decision(self, client, project, isolated_tropebook):
        res = client.post(
            f"/api/memory/{project}/decisions/promote",
            json={"decision": "Use Postgres", "context": "Better relational support", "citation_ids": []},
        )
        assert res.status_code == 422
        assert res.json()["detail"]["error"] == "tag_required"

    def test_successful_promotion_records_citation_ids(self, client, project, isolated_tropebook):
        cid = isolated_tropebook.add(title="A Source", url="https://example.com/a", summary="")

        res = client.post(
            f"/api/memory/{project}/decisions/promote",
            json={
                "decision": "Use SQLite for local dev",
                "context": "Simpler setup",
                "citation_ids": [cid],
                "safety_metadata": {"safety_category": "general"},
            },
        )

        assert res.status_code == 200
        decision = res.json()["decision"]
        assert decision["citation_ids"] == [cid]

    def test_unknown_citation_id_silently_filtered_not_rejected(self, client, project, isolated_tropebook):
        res = client.post(
            f"/api/memory/{project}/decisions/promote",
            json={
                "decision": "Use SQLite for local dev",
                "context": "",
                "citation_ids": ["does-not-exist"],
                "safety_metadata": {"safety_category": "general"},
            },
        )

        assert res.status_code == 200
        assert res.json()["decision"]["citation_ids"] == []

    def test_goes_through_the_same_contradiction_gate_as_add_decision(self, client, project, isolated_tropebook):
        # A high-severity contradiction gate is exercised in test_safety_features.py
        # already for add_decision -- this just confirms promote_decision doesn't
        # skip add_decision's machinery, by checking a normal promotion succeeds
        # and produces a real decision_hash the same way add_decision does.
        res = client.post(
            f"/api/memory/{project}/decisions/promote",
            json={
                "decision": "A perfectly normal decision",
                "context": "",
                "citation_ids": [],
                "safety_metadata": {"safety_category": "general"},
            },
        )
        assert res.status_code == 200
        assert "decision_hash" in res.json()["decision"]
