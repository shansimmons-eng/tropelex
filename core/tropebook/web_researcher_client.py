"""Minimal, dependency-free MCP stdio client for the web-researcher-mcp binary.

Speaks MCP's JSON-RPC-over-stdio protocol directly via subprocess instead of
depending on the official web-researcher-mcp Python SDK. Tropelex runs on a
venv-less, externally-managed system Python (PEP 668) where installing new
pip packages isn't safe to do casually — but the web-researcher-mcp binary
is already on PATH (installed as an MCP server for this session), so talking
to it directly over stdio needs zero new dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("tropelex.web_researcher")


class WebResearcherError(RuntimeError):
    """Raised when the web-researcher-mcp process is unavailable or a call fails."""


def _build_env() -> dict[str, str]:
    """Environment for the subprocess: inherit ours, but prefer Brave over the
    free DuckDuckGo default when Tropelex already has a Brave key configured
    (DuckDuckGo's free tier rate-limits hard under repeated use).
    """
    env = dict(os.environ)
    brave_key = env.get("BRAVE_SEARCH_API_KEY", "").strip()
    if brave_key and not env.get("SEARCH_PROVIDER"):
        env["SEARCH_PROVIDER"] = "brave"
        env["BRAVE_API_KEY"] = brave_key
    return env


def _resolve_binary() -> str:
    found = shutil.which("web-researcher-mcp")
    if found:
        return found
    home_path = os.path.expanduser("~/.local/bin/web-researcher-mcp")
    if os.path.exists(home_path):
        return home_path
    raise WebResearcherError(
        "web-researcher-mcp binary not found on PATH or in ~/.local/bin. Install via: "
        "curl -fsSL https://raw.githubusercontent.com/zoharbabin/web-researcher-mcp/main/install.sh | sh"
    )


class WebResearcherMCPClient:
    """One MCP session per instance — spawns the binary, use as a context manager.

    Example:
        with WebResearcherMCPClient() as client:
            result = client.call_tool("web_search", {"query": "...", "num_results": 5})
    """

    def __init__(self, timeout: float = 30.0):
        self._binary = _resolve_binary()
        self._timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._next_id = 1

    def __enter__(self) -> WebResearcherMCPClient:
        self._proc = subprocess.Popen(
            [self._binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=_build_env(),
        )
        self._send({
            "jsonrpc": "2.0",
            "id": self._alloc_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "tropelex", "version": "1.0"},
            },
        })
        init_resp = self._recv()
        if init_resp is None or "error" in init_resp:
            self._teardown()
            raise WebResearcherError(f"MCP initialize failed: {init_resp}")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._teardown()

    def _teardown(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
        self._proc = None

    def _alloc_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def _send(self, msg: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise WebResearcherError("MCP process not started (use as a context manager)")
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _recv(self) -> dict[str, Any] | None:
        if not self._proc or not self._proc.stdout:
            raise WebResearcherError("MCP process not started (use as a context manager)")
        line = self._proc.stdout.readline()
        if not line.strip():
            return None
        return json.loads(line)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool by name and return its parsed JSON result.

        Raises WebResearcherError if the process errors out or the tool
        itself reports an error (isError=true).
        """
        req_id = self._alloc_id()
        self._send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        resp = self._recv()
        if resp is None:
            raise WebResearcherError(f"No response calling tool {name!r} (process may have exited)")
        if "error" in resp:
            raise WebResearcherError(f"{name} failed: {resp['error']}")

        result = resp.get("result", {})
        content = result.get("content", [])
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        raw_text = "\n".join(text_parts)

        if result.get("isError"):
            raise WebResearcherError(f"{name} returned an error: {raw_text or result}")

        try:
            return json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            return {"text": raw_text}
