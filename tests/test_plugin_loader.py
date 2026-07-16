"""Tests for core.plugins.loader — plugin discovery and manifest validation."""

import json
import pytest
from pathlib import Path

from core.plugins.loader import discover_plugins, validate_manifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plugins_root(tmp_path):
    """Create a temporary plugins directory structure."""
    return tmp_path / "plugins"


def _write_manifest(directory: Path, data: dict) -> None:
    """Write a plugin.json into *directory*, creating it if needed."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------

class TestDiscoverPlugins:
    def test_returns_empty_for_missing_dir(self, tmp_path):
        result = discover_plugins(str(tmp_path / "nope"))
        assert result == []

    def test_returns_empty_for_empty_dir(self, plugins_root):
        plugins_root.mkdir()
        assert discover_plugins(str(plugins_root)) == []

    def test_discovers_valid_plugin(self, plugins_root):
        _write_manifest(plugins_root / "alpha", {
            "name": "alpha",
            "version": "1.0.0",
            "hooks": ["on_start"],
            "entry_point": "alpha:register",
        })
        result = discover_plugins(str(plugins_root))
        assert len(result) == 1
        assert result[0]["name"] == "alpha"
        assert result[0]["version"] == "1.0.0"

    def test_discovers_multiple_plugins(self, plugins_root):
        for name in ("a", "b", "c"):
            _write_manifest(plugins_root / name, {
                "name": name,
                "version": "0.1.0",
                "hooks": [],
                "entry_point": f"{name}:main",
            })
        result = discover_plugins(str(plugins_root))
        names = [p["name"] for p in result]
        assert names == ["a", "b", "c"]

    def test_skips_subdirectory_without_manifest(self, plugins_root):
        (plugins_root / "empty-plugin").mkdir(parents=True)
        assert discover_plugins(str(plugins_root)) == []

    def test_skips_malformed_json(self, plugins_root, caplog):
        bad = plugins_root / "bad"
        bad.mkdir(parents=True)
        (bad / "plugin.json").write_text("{not valid json")
        result = discover_plugins(str(plugins_root))
        assert result == []
        assert "Skipping malformed manifest" in caplog.text

    def test_skips_invalid_schema(self, plugins_root, caplog):
        _write_manifest(plugins_root / "inv", {
            "name": "inv",
            # missing version, hooks, entry_point
        })
        result = discover_plugins(str(plugins_root))
        assert result == []
        assert "Missing required keys" in caplog.text

    def test_ignores_non_directory_entries(self, plugins_root):
        plugins_root.mkdir()
        (plugins_root / "stray-file.txt").write_text("hello")
        assert discover_plugins(str(plugins_root)) == []

    def test_returns_sorted_by_directory_name(self, plugins_root):
        for name in ("zeta", "alpha", "mu"):
            _write_manifest(plugins_root / name, {
                "name": name,
                "version": "1.0.0",
                "hooks": [],
                "entry_point": f"{name}:run",
            })
        result = discover_plugins(str(plugins_root))
        assert [p["name"] for p in result] == ["alpha", "mu", "zeta"]


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------

class TestValidateManifest:
    VALID = {
        "name": "test",
        "version": "1.0.0",
        "hooks": ["on_start"],
        "entry_point": "test:register",
    }
    PATH = Path("/tmp/plugin.json")

    def test_valid_manifest_passes(self):
        result = validate_manifest(self.VALID, self.PATH)
        assert result is not None
        assert result["name"] == "test"
        assert result["hooks"] == ["on_start"]

    def test_rejects_non_dict(self):
        assert validate_manifest("not a dict", self.PATH) is None

    def test_rejects_missing_keys(self):
        incomplete = {"name": "x"}
        assert validate_manifest(incomplete, self.PATH) is None

    def test_rejects_empty_name(self):
        data = {**self.VALID, "name": ""}
        assert validate_manifest(data, self.PATH) is None

    def test_rejects_non_string_name(self):
        data = {**self.VALID, "name": 123}
        assert validate_manifest(data, self.PATH) is None

    def test_rejects_non_list_hooks(self):
        data = {**self.VALID, "hooks": "on_start"}
        assert validate_manifest(data, self.PATH) is None

    def test_rejects_empty_entry_point(self):
        data = {**self.VALID, "entry_point": ""}
        assert validate_manifest(data, self.PATH) is None

    def test_hooks_list_is_copied(self):
        """Returned hooks should be a new list (immutability)."""
        original = ["hook_a"]
        data = {**self.VALID, "hooks": original}
        result = validate_manifest(data, self.PATH)
        assert result["hooks"] is not original
