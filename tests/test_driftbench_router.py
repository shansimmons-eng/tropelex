"""
Tests for the Drift-Bench router (#60): GET /api/driftbench/latest and
POST /api/driftbench/run.

Not project-scoped (same shape as core/agent_audit/router.py's tests) --
uses a real TestClient against the real app, but redirects storage to a
tmp_path so these tests never touch the real memory/driftbench/latest.json.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path):
    """Every test in this file gets its own storage dir -- prevents test
    order from leaking a persisted report between tests, and guarantees
    the real project's memory/driftbench/latest.json is never touched."""
    with patch("core.driftbench.router.load_latest") as mock_load, \
         patch("core.driftbench.router.run_suite") as mock_run:
        yield mock_load, mock_run


class TestGetLatest:
    def test_404_when_never_run(self, client, _isolated_storage):
        mock_load, _ = _isolated_storage
        mock_load.return_value = None

        res = client.get("/api/driftbench/latest")

        assert res.status_code == 404

    def test_returns_persisted_report(self, client, _isolated_storage):
        mock_load, _ = _isolated_storage
        fake_report = {"generated_at": "2026-01-01T00:00:00+00:00", "detection_rate": 0.8, "scenario_count": 10}
        mock_load.return_value = fake_report

        res = client.get("/api/driftbench/latest")

        assert res.status_code == 200
        assert res.json() == fake_report

    def test_load_failure_returns_500_not_a_crash(self, client, _isolated_storage):
        mock_load, _ = _isolated_storage
        mock_load.side_effect = RuntimeError("disk error")

        res = client.get("/api/driftbench/latest")

        assert res.status_code == 500


class TestRunNow:
    def test_runs_and_returns_report(self, client, _isolated_storage):
        _, mock_run = _isolated_storage
        fake_report = {"generated_at": "2026-01-01T00:00:00+00:00", "detection_rate": 0.8, "scenario_count": 10}
        mock_run.return_value = fake_report

        res = client.post("/api/driftbench/run")

        assert res.status_code == 200
        assert res.json() == fake_report
        mock_run.assert_called_once()

    def test_run_failure_returns_500_not_a_crash(self, client, _isolated_storage):
        _, mock_run = _isolated_storage
        mock_run.side_effect = RuntimeError("scenario blew up")

        res = client.post("/api/driftbench/run")

        assert res.status_code == 500


class TestRealEndToEnd:
    """One real, unmocked pass -- confirms the actual corpus + real
    detectors + real persistence work together through the HTTP layer,
    not just through mocks. Storage redirected to tmp_path."""

    def test_run_then_latest_real_roundtrip(self, client, tmp_path):
        with patch("core.driftbench.router.run_suite") as mock_run, \
             patch("core.driftbench.router.load_latest") as mock_load:
            from core.driftbench.report import run_suite as real_run_suite
            from core.driftbench.report import load_latest as real_load_latest
            from core.driftbench.scenarios import build_corpus

            mock_run.side_effect = lambda corpus: real_run_suite(corpus, storage_dir=tmp_path)
            mock_load.side_effect = lambda: real_load_latest(storage_dir=tmp_path)

            run_res = client.post("/api/driftbench/run")
            assert run_res.status_code == 200
            body = run_res.json()
            assert body["scenario_count"] == 10
            assert body["detection_rate"] == 0.8
            assert body["false_positive_rate"] == 0.0

            latest_res = client.get("/api/driftbench/latest")
            assert latest_res.status_code == 200
            assert latest_res.json() == body
