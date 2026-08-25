"""Regression coverage for conftest.py's cleanup_test_artifacts(): a real
leak (2,992 files in memory/agent_skills/, found live during the Tropelex/
tropelex project-merge investigation) came from tests hitting
/agent-skills/record through the real app without patching AgentSkillGraph's
storage path -- the session-teardown sweep only ever cleaned
memory/test_*.json, never memory/agent_skills/test_*.json, so nothing was
cleaning that directory at all. This tests the sweep pattern directly rather
than only end-to-end via a full pytest session teardown.
"""

from __future__ import annotations

from tests.conftest import cleanup_test_artifacts


class TestCleanupTestArtifacts:
    def test_removes_top_level_test_project_files(self, tmp_path):
        (tmp_path / "test_abc123.json").write_text("{}")
        (tmp_path / "real_project.json").write_text("{}")

        removed = cleanup_test_artifacts(str(tmp_path))

        assert not (tmp_path / "test_abc123.json").exists()
        assert (tmp_path / "real_project.json").exists()
        assert len(removed) == 1

    def test_removes_agent_skills_sidecar_test_files(self, tmp_path):
        skills_dir = tmp_path / "agent_skills"
        skills_dir.mkdir()
        (skills_dir / "test_personas_deadbeef.json").write_text("{}")
        (skills_dir / "real_project.json").write_text("{}")

        removed = cleanup_test_artifacts(str(tmp_path))

        assert not (skills_dir / "test_personas_deadbeef.json").exists()
        assert (skills_dir / "real_project.json").exists()
        assert len(removed) == 1

    def test_sweeps_both_locations_in_one_call(self, tmp_path):
        skills_dir = tmp_path / "agent_skills"
        skills_dir.mkdir()
        (tmp_path / "test_top.json").write_text("{}")
        (skills_dir / "test_nested.json").write_text("{}")

        removed = cleanup_test_artifacts(str(tmp_path))

        assert len(removed) == 2

    def test_no_op_when_nothing_matches(self, tmp_path):
        (tmp_path / "real_project.json").write_text("{}")
        assert cleanup_test_artifacts(str(tmp_path)) == []

    def test_missing_agent_skills_dir_does_not_raise(self, tmp_path):
        (tmp_path / "test_x.json").write_text("{}")
        removed = cleanup_test_artifacts(str(tmp_path))
        assert len(removed) == 1
