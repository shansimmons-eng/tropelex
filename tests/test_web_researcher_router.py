"""Tests for core/tropebook/web_researcher_router.py's citation_ids field
(wishlist #82) -- added so the dashboard can hand real citation ids to
POST /research/promote-candidates instead of just a sources_imported count.

No prior test coverage existed for this router at all before this addition
(confirmed by grep) -- scope here is the new field, not a full router suite.
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
    return f"test_webresearch_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def isolated_tropebook(tmp_path):
    """web_researcher_router.py keeps its own module-level Tropebook
    singleton (_tropebook), entirely separate from server.py's _state
    dict -- both need isolating, or a test writes real citations into the
    live repo's memory/tropebook/ store. Confirmed the hard way: an
    earlier version of this fixture only patched server.py's singleton,
    and a real "A Source" citation + stale by_url index entry ended up in
    the actual store, cleaned up by hand afterward."""
    from core.tropebook.tropebook import Tropebook
    from core.tropebook.web import server as server_module
    from core.tropebook import web_researcher_router as wrr_module

    tb = Tropebook(storage_path=str(tmp_path / "tropebook"))
    original_server_tb = server_module._state["tropebook"]
    original_wrr_tb = wrr_module._tropebook
    server_module._state["tropebook"] = tb
    wrr_module._tropebook = tb
    try:
        yield
    finally:
        server_module._state["tropebook"] = original_server_tb
        wrr_module._tropebook = original_wrr_tb


_FAKE_REPORT = "Found [A Source](https://example.com/a) about the topic."


class TestWebResearchCitationIds:
    def test_citation_ids_resolve_to_the_imported_source(self, client, project, isolated_tropebook):
        fake_result = {"session_id": "s1", "steps": [{}], "report_markdown": _FAKE_REPORT}
        with patch(
            "core.tropebook.web_researcher_router.run_web_deep_research",
            new=AsyncMock(return_value=fake_result),
        ):
            res = client.post(
                f"/api/memory/{project}/deep-research/web-research",
                json={"topic": "test topic"},
            )

        assert res.status_code == 200
        body = res.json()
        assert body["sources_imported"] == 1
        assert len(body["citation_ids"]) == 1

        # The returned id must actually resolve to the imported citation.
        cid = body["citation_ids"][0]
        cite_res = client.get(f"/api/citations/{cid}")
        assert cite_res.status_code == 200
        assert cite_res.json()["url"] == "https://example.com/a"


class TestHybridResearchCitationIds:
    def test_citation_ids_resolve_when_web_leg_succeeds(self, client, project, isolated_tropebook):
        fake_web_result = {"session_id": "s1", "steps": [{}], "report_markdown": _FAKE_REPORT}
        with (
            patch(
                "core.tropebook.web_researcher_router.run_web_deep_research",
                new=AsyncMock(return_value=fake_web_result),
            ),
            patch(
                "core.last30days.runner.run_query_and_extract_citations",
                return_value=("Multi-source report.", []),
            ),
            patch(
                "core.tropebook.web_researcher_router._merge_reports",
                new=AsyncMock(return_value="Merged report."),
            ),
        ):
            res = client.post(
                f"/api/memory/{project}/deep-research/hybrid",
                json={"query": "test query"},
            )

        assert res.status_code == 200
        body = res.json()
        assert len(body["citation_ids"]) == 1

    def test_citation_ids_empty_when_web_leg_fails(self, client, project, isolated_tropebook):
        from core.tropebook.web_researcher_client import WebResearcherError

        with (
            patch(
                "core.tropebook.web_researcher_router.run_web_deep_research",
                new=AsyncMock(side_effect=WebResearcherError("unavailable")),
            ),
            patch(
                "core.last30days.runner.run_query_and_extract_citations",
                return_value=("Multi-source report.", []),
            ),
            patch(
                "core.tropebook.web_researcher_router._merge_reports",
                new=AsyncMock(return_value="Merged report."),
            ),
        ):
            res = client.post(
                f"/api/memory/{project}/deep-research/hybrid",
                json={"query": "test query"},
            )

        assert res.status_code == 200
        assert res.json()["citation_ids"] == []
