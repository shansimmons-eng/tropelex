"""Router-level tests for the two new Session Replay AI Analysis endpoints
(wishlist #19): POST .../timetravel/sessions/{id}/summarize and
GET .../timetravel/retrospective.

core/timetravel/router.py has no dependency-injection seam (MemoryManager()
and SessionReplay() are constructed fresh per-call, defaulting to the real
repo root -- matching the router's two pre-existing endpoints), so these
tests use a throwaway test_* project against the real memory/replays/
directory and clean up their own directory afterward (tests/conftest.py's
autouse cleanup only removes memory/test_*.json project files, not
memory/replays/ subdirectories).
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.memory.manager import MemoryManager
from core.session_replay import SessionReplay
from core.timetravel.router import timetravel_router

_REPLAYS_DIR = Path(MemoryManager().base_path) / "memory" / "replays"


@pytest.fixture
def project():
    name = f"test_tt_router_{uuid.uuid4().hex[:8]}"
    yield name
    shutil.rmtree(_REPLAYS_DIR / name, ignore_errors=True)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(timetravel_router)
    return TestClient(app)


def _seed_session(project: str, summary: str = "did something") -> str:
    replay = SessionReplay(str(Path(MemoryManager().base_path)))
    result = replay.record_session(project, {"decisions": []}, {"decisions": [{"decision": "x"}]}, summary=summary)
    return result["session_id"]


class TestSummarizeEndpoint:
    def test_generates_and_persists_ai_summary(self, client, project):
        session_id = _seed_session(project)
        with patch("core.llm.chat", new=AsyncMock(return_value="Added a decision.")):
            resp = client.post(f"/api/memory/{project}/timetravel/sessions/{session_id}/summarize")
        assert resp.status_code == 200
        assert resp.json()["ai_summary"] == "Added a decision."

        replay = SessionReplay(str(Path(MemoryManager().base_path)))
        assert replay.get_session(project, session_id)["ai_summary"] == "Added a decision."

    def test_unknown_session_404s(self, client, project):
        _seed_session(project)  # creates the project dir so this isn't a 404 for a different reason
        resp = client.post(f"/api/memory/{project}/timetravel/sessions/does-not-exist/summarize")
        assert resp.status_code == 404

    def test_no_llm_backend_returns_null_not_error(self, client, project):
        session_id = _seed_session(project)
        with patch("core.llm.chat", new=AsyncMock(return_value=None)):
            resp = client.post(f"/api/memory/{project}/timetravel/sessions/{session_id}/summarize")
        assert resp.status_code == 200
        assert resp.json()["ai_summary"] is None

    def test_does_not_overwrite_human_summary(self, client, project):
        session_id = _seed_session(project, summary="human-authored note")
        with patch("core.llm.chat", new=AsyncMock(return_value="AI take on it")):
            client.post(f"/api/memory/{project}/timetravel/sessions/{session_id}/summarize")

        replay = SessionReplay(str(Path(MemoryManager().base_path)))
        session = replay.get_session(project, session_id)
        assert session["summary"] == "human-authored note"
        assert session["ai_summary"] == "AI take on it"


class TestRetrospectiveEndpoint:
    def test_generates_retrospective_from_recent_sessions(self, client, project):
        _seed_session(project, summary="Shipped feature X")
        with patch("core.llm.chat", new=AsyncMock(return_value="You shipped feature X.")):
            resp = client.get(f"/api/memory/{project}/timetravel/retrospective?days=7")
        assert resp.status_code == 200
        body = resp.json()
        assert body["retrospective"] == "You shipped feature X."
        assert body["session_count"] == 1
        assert body["period_days"] == 7

    def test_no_sessions_returns_null_not_404(self, client, project):
        """No session history is a valid, common state -- a quiet period,
        not an error condition."""
        resp = client.get(f"/api/memory/{project}/timetravel/retrospective")
        assert resp.status_code == 200
        body = resp.json()
        assert body["retrospective"] is None
        assert body["session_count"] == 0

    def test_invalid_days_422s(self, client, project):
        resp = client.get(f"/api/memory/{project}/timetravel/retrospective?days=0")
        assert resp.status_code == 422
        resp = client.get(f"/api/memory/{project}/timetravel/retrospective?days=91")
        assert resp.status_code == 422
