"""
Tests for core.identity -- the public, non-secret per-install identifier
used to stamp provenance into exported data (account/benchmarks/sync
export-import). Distinct from core.auth.shared_secret's TROPEL_EX_SECRET,
which must never appear in exported data.
"""

from __future__ import annotations

from core.identity import INSTANCE_ID_ENV_VAR, get_or_create_instance_id


class TestGetOrCreateInstanceId:
    def test_generates_a_value_on_first_call(self, tmp_path, monkeypatch):
        monkeypatch.delenv(INSTANCE_ID_ENV_VAR, raising=False)
        instance_id = get_or_create_instance_id(tmp_path)
        assert instance_id
        assert isinstance(instance_id, str)

    def test_idempotent_across_repeated_calls(self, tmp_path, monkeypatch):
        monkeypatch.delenv(INSTANCE_ID_ENV_VAR, raising=False)
        first = get_or_create_instance_id(tmp_path)
        second = get_or_create_instance_id(tmp_path)
        assert first == second

    def test_persists_to_env_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv(INSTANCE_ID_ENV_VAR, raising=False)
        instance_id = get_or_create_instance_id(tmp_path)
        env_content = (tmp_path / ".env").read_text()
        assert f"{INSTANCE_ID_ENV_VAR}={instance_id}" in env_content

    def test_reads_existing_value_from_environment_without_regenerating(self, tmp_path, monkeypatch):
        monkeypatch.setenv(INSTANCE_ID_ENV_VAR, "already-set-value")
        instance_id = get_or_create_instance_id(tmp_path)
        assert instance_id == "already-set-value"
        # Nothing written -- the env var already satisfied the call.
        assert not (tmp_path / ".env").exists()

    def test_persist_failure_does_not_raise(self, tmp_path, monkeypatch):
        """An unwritable base_dir must not crash the caller -- same
        posture as get_or_create_secret's own persist-failure handling."""
        monkeypatch.delenv(INSTANCE_ID_ENV_VAR, raising=False)
        unwritable = tmp_path / "unwritable"
        unwritable.mkdir()
        unwritable.chmod(0o500)
        try:
            instance_id = get_or_create_instance_id(unwritable)
            assert instance_id
        finally:
            unwritable.chmod(0o700)

    def test_env_var_name_distinct_from_shared_secret(self):
        from core.auth.shared_secret import SECRET_ENV_VAR

        assert INSTANCE_ID_ENV_VAR != SECRET_ENV_VAR
