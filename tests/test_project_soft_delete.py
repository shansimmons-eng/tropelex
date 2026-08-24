"""Tests for project soft-delete: DELETE /api/memory/{project} (new) and
DELETE /api/memory/reset (fixed to soft-delete instead of unlink()).

Motivated by a real incident this session: a test-cleanup `rm` on a
project's memory file was irreversible because no delete endpoint existed
at all -- the only path was a raw filesystem rm. Mirrors the retention
approach the global Claude Code soft-delete-guard hook uses (a dated
trash folder, 30-day retention, purged opportunistically on each call).

Uses the same isolated-MemoryManager fixture pattern as
tests/test_injection_sentinel_router.py's isolated_tropebook (server.py's
_state dict lazy singleton, tmp_path-scoped for the test).
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_softdel_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def isolated_memory_manager(tmp_path):
    from core.memory.manager import MemoryManager
    from core.tropebook.web import server as server_module

    mm = MemoryManager(str(tmp_path))
    original = server_module._state["memory_manager"]
    server_module._state["memory_manager"] = mm
    try:
        yield mm, tmp_path
    finally:
        server_module._state["memory_manager"] = original


class TestDeleteOneProject:
    def test_404_for_nonexistent_project(self, client, project, isolated_memory_manager):
        res = client.delete(f"/api/memory/{project}")
        assert res.status_code == 404

    def test_moves_project_file_to_trash_not_deleting_it(self, client, project, isolated_memory_manager):
        mm, tmp_path = isolated_memory_manager
        client.post("/api/memory", json={"project_name": project})
        memory_file = tmp_path / "memory" / f"{project}.json"
        assert memory_file.exists()

        res = client.delete(f"/api/memory/{project}")

        assert res.status_code == 200
        body = res.json()
        assert body["deleted"] is True
        assert len(body["trashed_to"]) == 1
        assert not memory_file.exists()  # gone from its original location

        # Confirm the content actually survived the move, not just vanished.
        import json as _json
        from pathlib import Path
        dest = Path(body["trashed_to"][0])
        assert dest.exists()
        data = _json.loads(dest.read_text())
        assert isinstance(data, dict)

    def test_project_no_longer_listed_after_soft_delete(self, client, project, isolated_memory_manager):
        client.post("/api/memory", json={"project_name": project})
        client.delete(f"/api/memory/{project}")

        names = [p["name"] for p in client.get("/api/memory").json()["projects"]]
        assert project not in names

    def test_replay_directory_also_moved_if_present(self, client, project, isolated_memory_manager):
        mm, tmp_path = isolated_memory_manager
        client.post("/api/memory", json={"project_name": project})
        replay_dir = tmp_path / "memory" / "replays" / project
        replay_dir.mkdir(parents=True)
        (replay_dir / "session1.json").write_text("{}")

        res = client.delete(f"/api/memory/{project}")

        assert res.status_code == 200
        assert len(res.json()["trashed_to"]) == 2
        assert not replay_dir.exists()

    def test_purges_trash_older_than_retention_window(self, client, project, isolated_memory_manager):
        mm, tmp_path = isolated_memory_manager
        # Seed an old, expired trash entry directly on disk.
        old_dir = tmp_path / "memory" / ".trash" / "2020-01-01"
        old_dir.mkdir(parents=True)
        (old_dir / "stale.json-123").write_text("{}")
        old_time = time.time() - 40 * 86400
        import os
        os.utime(old_dir, (old_time, old_time))

        client.post("/api/memory", json={"project_name": project})
        client.delete(f"/api/memory/{project}")  # any soft-delete call purges

        assert not old_dir.exists()


class TestResetAllMemory:
    def test_moves_every_project_to_trash_not_unlinking(self, client, isolated_memory_manager):
        mm, tmp_path = isolated_memory_manager
        names = [f"test_reset_{uuid.uuid4().hex[:6]}" for _ in range(3)]
        for n in names:
            client.post("/api/memory", json={"project_name": n})

        res = client.delete("/api/memory/reset")

        assert res.status_code == 200
        assert res.json()["reset"] is True
        assert res.json()["trashed_count"] == 3
        for n in names:
            assert not (tmp_path / "memory" / f"{n}.json").exists()

        trash_root = tmp_path / "memory" / ".trash"
        assert trash_root.is_dir()
        trashed_files = list(trash_root.rglob("*.json-*"))
        assert len(trashed_files) == 3

    def test_empty_memory_dir_is_a_clean_noop(self, client, isolated_memory_manager):
        res = client.delete("/api/memory/reset")
        assert res.status_code == 200
        assert res.json()["trashed_count"] == 0
