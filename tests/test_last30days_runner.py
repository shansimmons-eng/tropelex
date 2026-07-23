"""Tests for core.last30days.runner — BRAVE key bridge and engine routing."""

import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestBRAVEKeyBridge:
    """Test that BRAVE_SEARCH_API_KEY is bridged to BRAVE_API_KEY."""

    def test_bridge_sets_bra_key_when_missing(self):
        """BRAVE_SEARCH_API_KEY is copied to BRAVE_API_KEY when BRAVE_API_KEY is absent."""
        from core.last30days.runner import run_query
        env = {"BRAVE_SEARCH_API_KEY": "test-brave-key"}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="<html>test</html>", stderr="")
            run_query("test", emit="html", env=env, timeout=10)
            call_env = mock_run.call_args[1]["env"] if "env" in mock_run.call_args[1] else mock_run.call_args[0][0]
            # Check the env passed to subprocess
            actual_env = mock_run.call_args.kwargs.get("env") or mock_run.call_args[1].get("env")
            assert actual_env.get("BRAVE_API_KEY") == "test-brave-key"

    def test_bridge_does_not_override_existing_key(self):
        """BRAVE_API_KEY is not overridden when already set."""
        from core.last30days.runner import run_query
        env = {
            "BRAVE_SEARCH_API_KEY": "search-key",
            "BRAVE_API_KEY": "existing-key",
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="<html>test</html>", stderr="")
            run_query("test", emit="html", env=env, timeout=10)
            actual_env = mock_run.call_args.kwargs.get("env") or mock_run.call_args[1].get("env")
            assert actual_env.get("BRAVE_API_KEY") == "existing-key"


class TestSynthEngineRouting:
    """Test that the synthesis driver is used for HTML emit."""

    def test_html_emit_uses_synth_engine(self):
        """When emit='html', the synthesis driver is preferred."""
        from core.last30days.runner import run_query, SYNTH_ENGINE
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="<html>test</html>", stderr="")
            run_query("test", emit="html", timeout=10)
            cmd = mock_run.call_args[0][0]
            assert str(SYNTH_ENGINE) in " ".join(cmd)

    def test_compact_emit_uses_plain_engine(self):
        """When emit='compact', the plain engine is used."""
        from core.last30days.runner import run_query, ENGINE
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="compact output", stderr="")
            run_query("test", emit="compact", timeout=10)
            cmd = mock_run.call_args[0][0]
            assert str(ENGINE) in " ".join(cmd)
            assert "--emit=compact" in cmd

    def test_nonzero_exit_raises_runtime_error(self):
        """Non-zero exit code raises RuntimeError."""
        from core.last30days.runner import run_query
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error message")
            with pytest.raises(RuntimeError, match="exited code 1"):
                run_query("test", emit="html", timeout=10)

    def test_timeout_raises_timeout_error(self):
        """Subprocess timeout raises TimeoutError."""
        import subprocess as sp
        from core.last30days.runner import run_query
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = sp.TimeoutExpired(cmd="test", timeout=10)
            with pytest.raises(TimeoutError):
                run_query("test", emit="html", timeout=10)


class TestExtractCitations:
    """Test run_query_and_extract_citations citation extraction."""

    def test_extracts_markdown_links(self):
        """Markdown links are extracted as citations."""
        from core.last30days.runner import run_query_and_extract_citations
        html = '<p>See <a href="https://example.com">Example</a> for details.</p>'
        with patch("core.last30days.runner.run_query", return_value=html):
            _, citations = run_query_and_extract_citations("test")
            urls = [c["url"] for c in citations]
            assert "https://example.com" in urls

    def test_empty_output_returns_empty_citations(self):
        """Empty output returns empty citations."""
        from core.last30days.runner import run_query_and_extract_citations
        with patch("core.last30days.runner.run_query", return_value=""):
            html, citations = run_query_and_extract_citations("test")
            assert html == ""
            assert citations == []
