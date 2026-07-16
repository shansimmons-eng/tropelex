"""Tests for core.sync.importer"""

import gzip
import json

import pytest

from core.sync.importer import (
    _decompress_data,
    _is_safe_project_name,
    _merge_project,
    _validate_schema,
    import_memory_data,
)


def _make_export(*projects):
    return {"version": "1.0", "projects": list(projects)}


def _project(name="test-proj", decisions=None):
    return {
        "project_name": name,
        "description": "A test project",
        "decisions": decisions or [],
        "session_history": [],
        "preferences": {},
        "tech_stack": ["Python"],
    }


def _encode(obj, compress=True):
    raw = json.dumps(obj).encode("utf-8")
    return gzip.compress(raw) if compress else raw


class TestDecompression:
    def test_gzip_roundtrip(self):
        original = b"hello world"
        compressed = gzip.compress(original)
        assert _decompress_data(compressed) == "hello world"

    def test_plain_json_passthrough(self):
        raw = b'{"key": "value"}'
        assert json.loads(_decompress_data(raw)) == {"key": "value"}

    def test_invalid_gzip_falls_back_to_text(self):
        # Random bytes that aren't gzip but also not valid UTF-8
        with pytest.raises(UnicodeDecodeError):
            _decompress_data(b"\xff\xfe\xfd")


class TestSchemaValidation:
    def test_valid_schema(self):
        assert _validate_schema(_make_export()) == []

    def test_missing_version(self):
        errors = _validate_schema({"projects": []})
        assert any("version" in e for e in errors)

    def test_missing_projects(self):
        errors = _validate_schema({"version": "1.0"})
        assert any("projects" in e for e in errors)

    def test_projects_not_list(self):
        errors = _validate_schema({"version": "1.0", "projects": "oops"})
        assert any("'projects' must be a list" in e for e in errors)


class TestSafeProjectName:
    def test_valid_name(self):
        assert _is_safe_project_name("my-project_123") is True

    def test_empty_name(self):
        assert _is_safe_project_name("") is False

    def test_dotdot_rejected(self):
        assert _is_safe_project_name("../../etc") is False

    def test_slash_rejected(self):
        assert _is_safe_project_name("proj/sub") is False

    def test_backslash_rejected(self):
        assert _is_safe_project_name("proj\\sub") is False


class TestMergeProject:
    def test_empty_existing(self):
        incoming = _project(decisions=[{"timestamp": "t1", "decision": "d1"}])
        merged = _merge_project({}, incoming)
        assert merged["decisions"] == [{"timestamp": "t1", "decision": "d1"}]

    def test_dedup_decisions(self):
        existing = {"decisions": [{"timestamp": "t1", "decision": "d1"}]}
        incoming = _project(
            decisions=[
                {"timestamp": "t1", "decision": "d1"},
                {"timestamp": "t2", "decision": "d2"},
            ]
        )
        merged = _merge_project(existing, incoming)
        assert len(merged["decisions"]) == 2

    def test_incoming_overwrites_non_list_fields(self):
        existing = {"description": "old", "tech_stack": ["JS"]}
        incoming = _project()
        merged = _merge_project(existing, incoming)
        assert merged["description"] == "A test project"
        assert merged["tech_stack"] == ["Python"]


class TestImportMemoryData:
    def test_import_compressed(self, tmp_path):
        export = _make_export(_project("alpha-proj"))
        result = import_memory_data(_encode(export), str(tmp_path))
        assert result["projects_imported"] == 1
        assert result["errors"] == []
        assert (tmp_path / "memory" / "alpha-proj.json").exists()

    def test_import_plain_json(self, tmp_path):
        export = _make_export(_project("beta-proj"))
        result = import_memory_data(_encode(export, compress=False), str(tmp_path))
        assert result["projects_imported"] == 1

    def test_import_invalid_json(self, tmp_path):
        result = import_memory_data(b"not json at all", str(tmp_path))
        assert result["projects_imported"] == 0
        assert len(result["errors"]) == 1

    def test_import_missing_schema_fields(self, tmp_path):
        data = json.dumps({"nope": True}).encode()
        result = import_memory_data(data, str(tmp_path))
        assert result["projects_imported"] == 0
        assert len(result["errors"]) >= 1

    def test_import_rejects_unsafe_name(self, tmp_path):
        export = _make_export(_project("../../etc/passwd"))
        result = import_memory_data(_encode(export), str(tmp_path))
        assert result["projects_imported"] == 0
        assert any("unsafe" in e for e in result["errors"])

    def test_import_creates_memory_dir(self, tmp_path):
        export = _make_export(_project("new-proj"))
        result = import_memory_data(_encode(export), str(tmp_path))
        assert result["files_written"] == 1
        assert (tmp_path / "memory").is_dir()

    def test_import_merge_without_overwrite(self, tmp_path):
        # Pre-existing project
        (tmp_path / "memory").mkdir(parents=True)
        existing = _project("merge-proj", decisions=[{"timestamp": "t1", "decision": "old"}])
        (tmp_path / "memory" / "merge-proj.json").write_text(json.dumps(existing))

        incoming = _project("merge-proj", decisions=[{"timestamp": "t2", "decision": "new"}])
        result = import_memory_data(
            _encode(_make_export(incoming)), str(tmp_path), overwrite=False
        )
        assert result["projects_imported"] == 1
        content = json.loads((tmp_path / "memory" / "merge-proj.json").read_text())
        assert len(content["decisions"]) == 2

    def test_import_overwrite_replaces(self, tmp_path):
        (tmp_path / "memory").mkdir(parents=True)
        existing = _project("ow-proj", decisions=[{"timestamp": "t1", "decision": "old"}])
        (tmp_path / "memory" / "ow-proj.json").write_text(json.dumps(existing))

        incoming = _project("ow-proj", decisions=[{"timestamp": "t2", "decision": "new"}])
        result = import_memory_data(
            _encode(_make_export(incoming)), str(tmp_path), overwrite=True
        )
        assert result["projects_imported"] == 1
        content = json.loads((tmp_path / "memory" / "ow-proj.json").read_text())
        assert len(content["decisions"]) == 1
        assert content["decisions"][0]["decision"] == "new"

    def test_multiple_projects(self, tmp_path):
        export = _make_export(_project("p1"), _project("p2"), _project("p3"))
        result = import_memory_data(_encode(export), str(tmp_path))
        assert result["projects_imported"] == 3
        assert result["files_written"] == 3
