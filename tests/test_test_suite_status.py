"""
Tests for core.test_suite_status.get_test_count.

subprocess.run is mocked throughout -- actually invoking a nested
`pytest --collect-only` from inside a pytest run would work, but is slow
and unnecessarily recursive for what's really a pure parsing function.
"""

import subprocess
from unittest.mock import MagicMock, patch

from core.test_suite_status import get_test_count


def _completed(stdout="", stderr="", returncode=0):
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


class TestGetTestCount:
    @patch("core.test_suite_status.subprocess.run")
    def test_parses_plural_count(self, mock_run):
        mock_run.return_value = _completed(stdout="collecting ...\n1789 tests collected in 1.12s\n")
        result = get_test_count("/repo")
        assert result == {"ok": True, "count": 1789}

    @patch("core.test_suite_status.subprocess.run")
    def test_parses_singular_count(self, mock_run):
        mock_run.return_value = _completed(stdout="1 test collected in 0.01s\n")
        result = get_test_count("/repo")
        assert result == {"ok": True, "count": 1}

    @patch("core.test_suite_status.subprocess.run")
    def test_runs_collect_only_not_a_full_run(self, mock_run):
        mock_run.return_value = _completed(stdout="1 test collected in 0.01s\n")
        get_test_count("/repo")
        args = mock_run.call_args[0][0]
        assert "--collect-only" in args

    @patch("core.test_suite_status.subprocess.run")
    def test_unparseable_output_returns_error(self, mock_run):
        mock_run.return_value = _completed(stdout="", stderr="ImportError: no module named foo\n", returncode=2)
        result = get_test_count("/repo")
        assert result["ok"] is False
        assert "ImportError" in result["error"]

    @patch("core.test_suite_status.subprocess.run")
    def test_timeout_returns_error_not_raises(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=30)
        result = get_test_count("/repo", timeout=30)
        assert result["ok"] is False
        assert "timed out" in result["error"]

    @patch("core.test_suite_status.subprocess.run")
    def test_pytest_not_found_returns_error_not_raises(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = get_test_count("/repo")
        assert result["ok"] is False
        assert "not found" in result["error"]


class TestTestCountEndpoint:
    """GET /api/tests/count -- the endpoint the dashboard's Run Diagnostics
    panel and Getting Started card now call, replacing the old hardcoded
    "1455 Passed" string."""

    def test_endpoint_returns_real_count(self):
        from fastapi.testclient import TestClient
        from core.tropebook.web.server import app

        with patch("core.test_suite_status.subprocess.run") as mock_run:
            mock_run.return_value = _completed(stdout="42 tests collected in 0.1s\n")
            resp = TestClient(app).get("/api/tests/count")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "count": 42}
