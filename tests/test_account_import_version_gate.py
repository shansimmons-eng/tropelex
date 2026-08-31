"""
Tests for /api/account/import's schema_version gate (versioning policy,
core/version.py) -- an export whose schema_version doesn't match this
install's must 409 with the detected/current versions attached instead of
silently overwriting project files, unless the caller already confirmed.
Same gate-then-override shape as Ghost's gate_blocked (#53).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from core.memory.manager import MemoryManager
from core.tropebook.web.server import app
from core.version import MEMORY_SCHEMA_VERSION


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project_name():
    """A unique project name per test -- account_import writes directly
    to mm.memory_dir/{name}.json, so this must never collide with a real
    project. Cleaned up afterward so tests don't litter real memory/."""
    name = f"test_account_import_{uuid.uuid4().hex[:8]}"
    yield name
    mm = MemoryManager()
    (mm.memory_dir / f"{name}.json").unlink(missing_ok=True)


def _export_payload(project_name: str, schema_version) -> dict:
    payload = {
        "projects": {project_name: {"project_name": project_name, "decisions": []}},
        "tropebook": {"citations": {}, "graph": None},
        "feeds": [],
        "settings": {},
    }
    if schema_version is not None:
        payload["schema_version"] = schema_version
    return payload


class TestSchemaVersionGate:
    def test_matching_schema_version_imports_without_confirm(self, client, project_name):
        resp = client.post("/api/account/import", json={
            "data": _export_payload(project_name, MEMORY_SCHEMA_VERSION),
        })
        assert resp.status_code == 200
        assert resp.json()["imported"]["projects"] == 1

    def test_mismatched_schema_version_409s_without_confirm(self, client, project_name):
        resp = client.post("/api/account/import", json={
            "data": _export_payload(project_name, MEMORY_SCHEMA_VERSION + 1),
        })
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["detected_schema_version"] == MEMORY_SCHEMA_VERSION + 1
        assert detail["current_schema_version"] == MEMORY_SCHEMA_VERSION

        # The gate must not have written anything -- a 409 means nothing
        # was imported, not "imported anyway and also complained."
        mm = MemoryManager()
        assert not (mm.memory_dir / f"{project_name}.json").exists()

    def test_missing_schema_version_treated_as_mismatch(self, client, project_name):
        """An export predating this field entirely (schema_version key
        absent) must not be assumed compatible -- it 409s the same as an
        explicit mismatch, not silently imported."""
        resp = client.post("/api/account/import", json={
            "data": _export_payload(project_name, None),
        })
        assert resp.status_code == 409
        assert resp.json()["detail"]["detected_schema_version"] is None

    def test_mismatched_schema_version_imports_with_confirm(self, client, project_name):
        resp = client.post("/api/account/import", json={
            "data": _export_payload(project_name, MEMORY_SCHEMA_VERSION + 1),
            "confirm": True,
        })
        assert resp.status_code == 200
        assert resp.json()["imported"]["projects"] == 1

    def test_409_detail_includes_app_version_context(self, client, project_name):
        data = _export_payload(project_name, MEMORY_SCHEMA_VERSION + 1)
        data["app_version"] = "0.9.0"
        resp = client.post("/api/account/import", json={"data": data})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["app_version_exported_from"] == "0.9.0"
        assert "app_version_here" in detail


class TestDefensiveImportHandling:
    """Robust-error-handling hardening: malformed or hostile `projects`
    data must degrade gracefully (skip + report), never crash the whole
    import or write something unsafe to disk."""

    def test_projects_not_a_dict_imports_nothing_but_succeeds(self, client):
        data = {"schema_version": MEMORY_SCHEMA_VERSION, "projects": "not-a-dict"}
        resp = client.post("/api/account/import", json={"data": data})
        assert resp.status_code == 200
        assert resp.json()["imported"]["projects"] == 0

    def test_non_dict_project_entry_is_skipped_not_written(self, client, project_name):
        data = {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "projects": {project_name: "not-a-dict-either"},
        }
        resp = client.post("/api/account/import", json={"data": data})
        assert resp.status_code == 200
        assert resp.json()["imported"]["projects"] == 0
        assert project_name in resp.json()["skipped_projects"]

        mm = MemoryManager()
        assert not (mm.memory_dir / f"{project_name}.json").exists()

    def test_path_traversal_project_name_is_sanitised_not_rejected_wholesale(self, client):
        """_sanitise_project (already used elsewhere in server.py for the
        same purpose) reduces a traversal attempt to its basename rather
        than escaping mm.memory_dir -- confirms the import loop actually
        calls it now, matching the rest of this file's convention."""
        mm = MemoryManager()
        safe_name = f"test_traversal_{uuid.uuid4().hex[:8]}"
        traversal_key = f"../../../../tmp/{safe_name}"
        data = {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "projects": {traversal_key: {"project_name": safe_name, "decisions": []}},
        }
        try:
            resp = client.post("/api/account/import", json={"data": data})
            assert resp.status_code == 200
            assert resp.json()["imported"]["projects"] == 1
            # Landed inside memory_dir under the sanitised (basename-only)
            # name -- not outside it, not under the raw traversal path.
            assert (mm.memory_dir / f"{safe_name}.json").exists()
        finally:
            (mm.memory_dir / f"{safe_name}.json").unlink(missing_ok=True)


class TestExportDefensiveHandling:
    def test_corrupt_project_file_is_skipped_not_500(self, client):
        mm = MemoryManager()
        bad_name = f"test_export_corrupt_{uuid.uuid4().hex[:8]}"
        bad_file = mm.memory_dir / f"{bad_name}.json"
        bad_file.write_text("{not valid json")
        try:
            resp = client.get("/api/account/export")
            assert resp.status_code == 200
            body = resp.json()
            assert bad_name not in body["projects"]
            assert bad_name in body["skipped_projects"]
        finally:
            bad_file.unlink(missing_ok=True)
