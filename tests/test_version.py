"""
Tests for core.version -- the single source of truth for APP_VERSION
(pyproject.toml, semver, release identifier) and MEMORY_SCHEMA_VERSION
(a plain int, bumped only when the memory/export JSON shape changes).
"""

from __future__ import annotations

import core.version as version_mod
from core.version import _read_app_version


class TestReadAppVersion:
    def test_parses_a_real_pyproject_toml(self, tmp_path, monkeypatch):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\nversion = "9.9.9"\ndescription = "y"\n')
        monkeypatch.setattr(version_mod, "_PYPROJECT_PATH", pyproject)
        assert _read_app_version() == "9.9.9"

    def test_missing_file_falls_back_to_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version_mod, "_PYPROJECT_PATH", tmp_path / "does-not-exist.toml")
        assert _read_app_version() == "unknown"

    def test_malformed_file_with_no_version_line_falls_back_to_unknown(self, tmp_path, monkeypatch):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = \"x\"\n")
        monkeypatch.setattr(version_mod, "_PYPROJECT_PATH", pyproject)
        assert _read_app_version() == "unknown"

    def test_never_raises_on_unreadable_path(self, tmp_path, monkeypatch):
        # A directory, not a file -- read_text() raises IsADirectoryError,
        # a subclass of OSError, which _read_app_version must swallow.
        monkeypatch.setattr(version_mod, "_PYPROJECT_PATH", tmp_path)
        assert _read_app_version() == "unknown"


class TestModuleLevelConstants:
    def test_app_version_resolves_from_the_real_pyproject_toml(self):
        # The real repo's pyproject.toml always has a version line -- this
        # module is imported once at process start, so confirm it actually
        # found a real value, not silently "unknown".
        assert version_mod.APP_VERSION != "unknown"
        assert version_mod.APP_VERSION.count(".") == 2

    def test_memory_schema_version_is_a_positive_int(self):
        assert isinstance(version_mod.MEMORY_SCHEMA_VERSION, int)
        assert version_mod.MEMORY_SCHEMA_VERSION >= 1
