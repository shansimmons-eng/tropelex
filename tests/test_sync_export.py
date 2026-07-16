"""Tests for core.sync.exporter"""

import gzip
import json
import tempfile
from pathlib import Path

from core.sync.exporter import EXPORT_VERSION, export_memory_data


def _write_memory_file(tmp: Path, name: str, data: dict) -> None:
    """Helper: write a memory JSON file."""
    (tmp / "memory").mkdir(parents=True, exist_ok=True)
    (tmp / "memory" / f"{name}.json").write_text(json.dumps(data))


def _decompress_export(raw: bytes) -> dict:
    """Helper: decompress and parse export bytes."""
    return json.loads(gzip.decompress(raw))


# --- export_memory_data tests ---


class TestExportMemoryData:
    def test_empty_memory_directory(self, tmp_path: Path) -> None:
        """Graceful handling when memory dir is empty or absent."""
        (tmp_path / "memory").mkdir()
        result = export_memory_data(str(tmp_path))
        payload = _decompress_export(result)

        assert payload["metadata"]["project_count"] == 0
        assert payload["metadata"]["version"] == EXPORT_VERSION
        assert payload["projects"] == []

    def test_missing_memory_directory(self, tmp_path: Path) -> None:
        """No memory dir at all — still returns valid export."""
        result = export_memory_data(str(tmp_path))
        payload = _decompress_export(result)

        assert payload["metadata"]["project_count"] == 0
        assert payload["projects"] == []

    def test_single_project(self, tmp_path: Path) -> None:
        """Exports a single project's memory file."""
        project = {"project_name": "alpha", "decisions": [], "tech_stack": ["Python"]}
        _write_memory_file(tmp_path, "alpha", project)

        payload = _decompress_export(export_memory_data(str(tmp_path)))

        assert payload["metadata"]["project_count"] == 1
        assert len(payload["projects"]) == 1
        assert payload["projects"][0] == project

    def test_multiple_projects(self, tmp_path: Path) -> None:
        """Exports all projects found in memory directory."""
        _write_memory_file(tmp_path, "proj_a", {"project_name": "proj_a"})
        _write_memory_file(tmp_path, "proj_b", {"project_name": "proj_b"})

        payload = _decompress_export(export_memory_data(str(tmp_path)))

        assert payload["metadata"]["project_count"] == 2
        names = {p["project_name"] for p in payload["projects"]}
        assert names == {"proj_a", "proj_b"}

    def test_metadata_fields_present(self, tmp_path: Path) -> None:
        """Export metadata contains version, timestamp, and count."""
        payload = _decompress_export(export_memory_data(str(tmp_path)))
        meta = payload["metadata"]

        assert meta["version"] == "1.0.0"
        assert "exported_at" in meta
        assert isinstance(meta["project_count"], int)

    def test_output_is_gzip_bytes(self, tmp_path: Path) -> None:
        """Returned value is raw gzip-compressed bytes."""
        result = export_memory_data(str(tmp_path))

        assert isinstance(result, bytes)
        # Verify gzip magic bytes
        assert result[:2] == b"\x1f\x8b"

    def test_export_preserves_full_project_data(self, tmp_path: Path) -> None:
        """All project fields survive the export round-trip."""
        project = {
            "project_name": "full",
            "created": "2026-01-01T00:00:00Z",
            "decisions": [{"decision": "use gzip", "context": "small payloads"}],
            "preferences": {"verbose": True},
            "tech_stack": ["Python", "pytest"],
        }
        _write_memory_file(tmp_path, "full", project)

        payload = _decompress_export(export_memory_data(str(tmp_path)))

        assert len(payload["projects"]) == 1
        assert payload["projects"][0] == project
