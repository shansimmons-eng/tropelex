"""Integration tests for core.benchmarks.router — export/import bundle
mechanics and the memory/federation -> memory/benchmarks migration."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.benchmarks.router as router_mod
from core.benchmarks.router import benchmarks_router
from core.memory.manager import MemoryManager


def _point_router_at(tmp_path: Path) -> MemoryManager:
    mm = MemoryManager(base_path=str(tmp_path))
    router_mod._mm = mm
    router_mod._BENCHMARKS_DIR = Path(mm.memory_dir) / "benchmarks"
    router_mod._LEGACY_FEDERATION_DIR = Path(mm.memory_dir) / "federation"
    return mm


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """router_mod._mm/_BENCHMARKS_DIR/_LEGACY_FEDERATION_DIR are shared
    module-level singletons — core.tropebook.web.server mounts the same
    benchmarks_router instance, so leaving them pointed at a tmp dir after
    this fixture tears down would silently break the real app's benchmarks
    endpoints for any test that runs afterward. Always restore them.
    """
    app = FastAPI()
    app.include_router(benchmarks_router)

    original = (router_mod._mm, router_mod._BENCHMARKS_DIR, router_mod._LEGACY_FEDERATION_DIR)
    _point_router_at(tmp_path)

    yield TestClient(app, raise_server_exceptions=False)

    router_mod._mm, router_mod._BENCHMARKS_DIR, router_mod._LEGACY_FEDERATION_DIR = original


def _stat(hash_: str, decisions: int = 5) -> dict:
    return {
        "project_hash": hash_,
        "tech_stack": ["Python"],
        "decision_count": decisions,
        "reversal_rate": 0.1,
        "avg_confidence": 0.7,
        "category_distribution": {"backend": 2},
        "avg_safety_score": 0.9,
        "risk_level_distribution": {"low": 2},
    }


class TestExport:
    def test_empty_export(self, client: TestClient) -> None:
        resp = client.get("/api/memory/benchmarks/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["stats"] == []
        assert "exported_at" in body

    def test_export_reflects_shared_stats(self, client: TestClient) -> None:
        router_mod._save_shared_stats("abc123", _stat("abc123"))
        resp = client.get("/api/memory/benchmarks/export")
        body = resp.json()
        assert body["count"] == 1
        assert body["stats"][0]["project_hash"] == "abc123"


class TestImport:
    def test_import_new_entries(self, client: TestClient) -> None:
        resp = client.post("/api/memory/benchmarks/import", json={
            "stats": [_stat("h1"), _stat("h2")],
            "source_label": "laptop-b",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["imported"] == 2
        assert body["skipped_existing"] == 0
        assert body["skipped_invalid"] == 0
        assert body["total_local_after_import"] == 2

    def test_import_never_overwrites_existing_hash(self, client: TestClient) -> None:
        router_mod._save_shared_stats("h1", _stat("h1", decisions=999))
        resp = client.post("/api/memory/benchmarks/import", json={
            "stats": [_stat("h1", decisions=1)],
        })
        body = resp.json()
        assert body["imported"] == 0
        assert body["skipped_existing"] == 1
        # local copy untouched
        on_disk = json.loads((router_mod._BENCHMARKS_DIR / "h1.json").read_text())
        assert on_disk["decision_count"] == 999

    def test_import_skips_invalid_entries(self, client: TestClient) -> None:
        resp = client.post("/api/memory/benchmarks/import", json={
            "stats": [{"not_a_valid": "entry"}, _stat("valid1")],
        })
        body = resp.json()
        assert body["imported"] == 1
        assert body["skipped_invalid"] == 1

    def test_reimporting_same_bundle_is_idempotent(self, client: TestClient) -> None:
        bundle = {"stats": [_stat("h1"), _stat("h2")]}
        first = client.post("/api/memory/benchmarks/import", json=bundle).json()
        second = client.post("/api/memory/benchmarks/import", json=bundle).json()
        assert first["imported"] == 2
        assert second["imported"] == 0
        assert second["skipped_existing"] == 2

    def test_imported_entries_feed_aggregate(self, client: TestClient) -> None:
        client.post("/api/memory/benchmarks/import", json={"stats": [_stat("h1", decisions=10), _stat("h2", decisions=20)]})
        resp = client.get("/api/memory/benchmarks/aggregate")
        body = resp.json()
        assert body["total_projects"] == 2
        assert body["aggregate"]["decision_count"] == 30


class TestSchemaVersion:
    """Versioning policy (core/version.py): export echoes MEMORY_SCHEMA_
    VERSION; import surfaces a real diagnostic when a bundle's own
    schema_version doesn't match, instead of just an opaque skip count."""

    def test_export_includes_current_schema_version(self, client: TestClient) -> None:
        from core.version import MEMORY_SCHEMA_VERSION
        resp = client.get("/api/memory/benchmarks/export")
        assert resp.json()["schema_version"] == MEMORY_SCHEMA_VERSION

    def test_import_no_schema_version_no_warning(self, client: TestClient) -> None:
        """A bundle predating this field (no schema_version key at all)
        must still import normally -- optional, not required."""
        resp = client.post("/api/memory/benchmarks/import", json={"stats": [_stat("h1")]})
        body = resp.json()
        assert body["imported"] == 1
        assert body["warning"] is None

    def test_import_matching_schema_version_no_warning(self, client: TestClient) -> None:
        from core.version import MEMORY_SCHEMA_VERSION
        resp = client.post("/api/memory/benchmarks/import", json={
            "stats": [_stat("h1")], "schema_version": MEMORY_SCHEMA_VERSION,
        })
        assert resp.json()["warning"] is None

    def test_import_mismatched_schema_version_with_invalid_entries_warns(self, client: TestClient) -> None:
        from core.version import MEMORY_SCHEMA_VERSION
        resp = client.post("/api/memory/benchmarks/import", json={
            "stats": [{"not_a_valid": "entry"}],
            "schema_version": MEMORY_SCHEMA_VERSION + 1,
        })
        body = resp.json()
        assert body["skipped_invalid"] == 1
        assert body["bundle_schema_version"] == MEMORY_SCHEMA_VERSION + 1
        assert body["warning"] is not None
        assert "version mismatch" in body["warning"]

    def test_import_mismatched_schema_version_no_invalid_entries_no_warning(self, client: TestClient) -> None:
        """A version mismatch alone isn't grounds for a warning -- only
        when it's actually correlated with skipped entries."""
        from core.version import MEMORY_SCHEMA_VERSION
        resp = client.post("/api/memory/benchmarks/import", json={
            "stats": [_stat("h1")], "schema_version": MEMORY_SCHEMA_VERSION + 1,
        })
        body = resp.json()
        assert body["skipped_invalid"] == 0
        assert body["warning"] is None


class TestLegacyMigration:
    def test_migrates_old_federation_dir_on_first_access(self, client: TestClient, tmp_path: Path) -> None:
        # The `client` fixture already pointed router_mod at tmp_path; seed a
        # pre-migration federation/ dir under that same memory dir before
        # the first request triggers _ensure_benchmarks_dir()'s migration.
        legacy_dir = router_mod._LEGACY_FEDERATION_DIR
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "oldhash.json").write_text(json.dumps(_stat("oldhash")))

        resp = client.get("/api/memory/benchmarks/export")
        body = resp.json()
        assert body["count"] == 1
        assert body["stats"][0]["project_hash"] == "oldhash"
        assert not legacy_dir.exists()
        assert (router_mod._BENCHMARKS_DIR / "oldhash.json").exists()
