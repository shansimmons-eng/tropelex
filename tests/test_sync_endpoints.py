"""Integration tests for core.sync.router (sync API endpoints)."""

import base64
import gzip
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.sync.router import sync_router


# --- Helpers ---


def _make_export_payload(*projects: dict) -> dict:
    return {"version": "1.0", "projects": list(projects)}


def _project(name: str = "test-proj", **overrides) -> dict:
    base = {
        "project_name": name,
        "description": "A test project",
        "decisions": [],
        "session_history": [],
        "preferences": {},
        "tech_stack": ["Python"],
    }
    base.update(overrides)
    return base


def _encode(obj: dict, compress: bool = True) -> str:
    raw = json.dumps(obj).encode("utf-8")
    data = gzip.compress(raw) if compress else raw
    return base64.b64encode(data).decode("ascii")


def _make_client(tmp_path: Path) -> TestClient:
    """Build a TestClient whose BASE_DIR points at *tmp_path*."""
    app = FastAPI()
    app.include_router(sync_router)

    # Patch the router's BASE_DIR so tests are isolated
    import core.sync.router as router_mod

    original = router_mod.BASE_DIR
    router_mod.BASE_DIR = tmp_path

    client = TestClient(app, raise_server_exceptions=False)

    # Restore after each test via fixture teardown (done in the fixture)
    yield client

    router_mod.BASE_DIR = original


@pytest.fixture()
def client(tmp_path: Path):
    import core.sync.router as router_mod

    # Reset shared state so tests are independent
    router_mod._sync_state["last_export"] = None
    router_mod._sync_state["last_import"] = None
    yield from _make_client(tmp_path)


# --- GET /api/sync/export ---


class TestSyncExport:
    def test_returns_gzip_bytes(self, client: TestClient) -> None:
        resp = client.get("/api/sync/export")
        assert resp.status_code == 200
        assert resp.headers["content-encoding"] == "gzip"
        # TestClient auto-decompresses; validate structure from JSON
        payload = resp.json()
        assert "metadata" in payload
        assert "projects" in payload

    def test_empty_export(self, client: TestClient) -> None:
        resp = client.get("/api/sync/export")
        payload = resp.json()
        assert payload["metadata"]["project_count"] == 0
        assert payload["projects"] == []

    def test_export_with_project(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "alpha.json").write_text(
            json.dumps(_project("alpha"))
        )
        resp = client.get("/api/sync/export")
        payload = resp.json()
        assert payload["metadata"]["project_count"] == 1
        assert payload["projects"][0]["project_name"] == "alpha"

    def test_update_last_export_timestamp(self, client: TestClient) -> None:
        client.get("/api/sync/export")
        resp = client.get("/api/sync/status")
        assert resp.json()["last_export"] is not None


# --- POST /api/sync/import ---


class TestSyncImport:
    def test_import_single_project(self, client: TestClient) -> None:
        payload = _make_export_payload(_project("gamma"))
        resp = client.post(
            "/api/sync/import",
            json={"data": _encode(payload), "overwrite": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["projects_imported"] == 1
        assert body["files_written"] == 1
        assert body["errors"] == []

    def test_import_creates_files(self, client: TestClient, tmp_path: Path) -> None:
        payload = _make_export_payload(_project("delta"))
        client.post(
            "/api/sync/import",
            json={"data": _encode(payload), "overwrite": True},
        )
        assert (tmp_path / "memory" / "delta.json").exists()

    def test_import_invalid_base64(self, client: TestClient) -> None:
        resp = client.post(
            "/api/sync/import",
            json={"data": "!!!not-base64!!!", "overwrite": False},
        )
        assert resp.status_code == 422

    def test_import_invalid_json_payload(self, client: TestClient) -> None:
        bad_data = base64.b64encode(b"this is not json").decode()
        resp = client.post(
            "/api/sync/import",
            json={"data": bad_data, "overwrite": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["projects_imported"] == 0
        assert len(body["errors"]) > 0

    def test_import_overwrite_flag(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        existing = _project(
            "overwrite-proj",
            decisions=[{"timestamp": "t1", "decision": "old"}],
        )
        (tmp_path / "memory" / "overwrite-proj.json").write_text(json.dumps(existing))

        incoming = _project(
            "overwrite-proj",
            decisions=[{"timestamp": "t2", "decision": "new"}],
        )
        resp = client.post(
            "/api/sync/import",
            json={"data": _encode(_make_export_payload(incoming)), "overwrite": True},
        )
        assert resp.status_code == 200
        content = json.loads((tmp_path / "memory" / "overwrite-proj.json").read_text())
        assert len(content["decisions"]) == 1
        assert content["decisions"][0]["decision"] == "new"

    def test_import_merge_without_overwrite(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        existing = _project(
            "merge-proj",
            decisions=[{"timestamp": "t1", "decision": "old"}],
        )
        (tmp_path / "memory" / "merge-proj.json").write_text(json.dumps(existing))

        incoming = _project(
            "merge-proj",
            decisions=[{"timestamp": "t2", "decision": "new"}],
        )
        resp = client.post(
            "/api/sync/import",
            json={"data": _encode(_make_export_payload(incoming)), "overwrite": False},
        )
        assert resp.status_code == 200
        content = json.loads((tmp_path / "memory" / "merge-proj.json").read_text())
        assert len(content["decisions"]) == 2

    def test_update_last_import_timestamp(self, client: TestClient) -> None:
        payload = _make_export_payload(_project("ts-proj"))
        client.post(
            "/api/sync/import",
            json={"data": _encode(payload), "overwrite": False},
        )
        resp = client.get("/api/sync/status")
        assert resp.json()["last_import"] is not None

    def test_missing_data_field(self, client: TestClient) -> None:
        resp = client.post("/api/sync/import", json={"overwrite": False})
        assert resp.status_code == 422


# --- GET /api/sync/status ---


class TestSyncStatus:
    def test_initial_status(self, client: TestClient) -> None:
        resp = client.get("/api/sync/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_export"] is None
        assert body["last_import"] is None
        assert body["memory_dir_exists"] is False
        assert body["project_count"] == 0

    def test_status_after_operations(self, client: TestClient, tmp_path: Path) -> None:
        # Create memory dir with a project
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "proj.json").write_text(json.dumps(_project("proj")))

        # Do an export
        client.get("/api/sync/export")

        resp = client.get("/api/sync/status")
        body = resp.json()
        assert body["last_export"] is not None
        assert body["memory_dir_exists"] is True
        assert body["project_count"] == 1

    def test_status_project_count(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "memory").mkdir()
        for name in ["a", "b", "c"]:
            (tmp_path / "memory" / f"{name}.json").write_text(json.dumps(_project(name)))

        resp = client.get("/api/sync/status")
        assert resp.json()["project_count"] == 3


# --- Round-trip test ---


class TestSyncRoundTrip:
    def test_export_then_import(self, client: TestClient, tmp_path: Path) -> None:
        """Full export → base64 → import round-trip preserves data."""
        (tmp_path / "memory").mkdir()
        original = _project("roundtrip", tech_stack=["Rust", "FastAPI"])
        (tmp_path / "memory" / "roundtrip.json").write_text(json.dumps(original))

        # Export
        export_resp = client.get("/api/sync/export")
        assert export_resp.status_code == 200

        # Import into a clean directory
        clean = tmp_path / "import_target"
        clean.mkdir()
        import core.sync.router as router_mod

        old_base = router_mod.BASE_DIR
        router_mod.BASE_DIR = clean
        try:
            # Re-compress the exported data for import (TestClient auto-decompressed)
            export_json = export_resp.json()
            export_bytes = gzip.compress(json.dumps(export_json).encode())
            b64 = base64.b64encode(export_bytes).decode()
            import_resp = client.post(
                "/api/sync/import",
                json={"data": b64, "overwrite": True},
            )
            assert import_resp.status_code == 200
            assert import_resp.json()["projects_imported"] == 1
        finally:
            router_mod.BASE_DIR = old_base
