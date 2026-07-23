"""
Last30Days research runner — wraps the last30days.py engine for in-process use.

Calls last30days.py as a subprocess (same pattern as the bridge server)
and returns the rendered HTML output. No external dependencies beyond
what last30days.py itself needs (stdlib + its own lib/ modules).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("tropelex.last30days")

# The last30days Python engine lives adjacent to this file
SCRIPT_DIR = Path(__file__).parent.resolve()
ENGINE = SCRIPT_DIR / "last30days.py"
# Driver that adds the LLM synthesis step (rich HTML like the WP portal shows)
SYNTH_ENGINE = SCRIPT_DIR / "synthesize_run.py"

ENGINE_TIMEOUT = int(os.environ.get("L30D_ENGINE_TIMEOUT", "300"))  # 5 min default (deep research is slow)


def run_query(
    query: str,
    *,
    timeout: int | None = None,
    emit: str = "html",
    env: dict[str, str] | None = None,
) -> str:
    """Run a last30days research query and return the rendered output.

    Args:
        query: The research query / topic.
        timeout: Seconds to wait before raising TimeoutError (default 180).
        emit: Output format — 'html' (default), 'md', or 'compact'.
        env: Extra environment variables (merged over os.environ).

    Returns:
        Rendered output string (HTML unless emit differs).

    Raises:
        FileNotFoundError: If the engine script isn't found.
        TimeoutError: If the engine doesn't finish within the timeout.
        RuntimeError: If the engine returns a non-zero exit code.
    """
    if not ENGINE.exists():
        raise FileNotFoundError(
            f"last30days engine not found at {ENGINE}. "
            "Ensure core/last30days/last30days.py is present."
        )

    # For HTML output, prefer the synthesis driver: it runs the pipeline once,
    # writes the research brief via an LLM, and renders HTML with the synthesis
    # embedded (the WP-portal shape). Falls back to the sparse engine output
    # when no LLM key is configured. Non-HTML emits use the plain engine.
    use_synth = emit == "html" and SYNTH_ENGINE.exists()
    if use_synth:
        cmd = [sys.executable, str(SYNTH_ENGINE), query]
    else:
        cmd = [
            sys.executable,
            str(ENGINE),
            query,
            f"--emit={emit}",
            "--agent",          # non-interactive mode
            "--no-format",      # raw output, no terminal formatting
        ]

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    # Tropelex stores Brave as BRAVE_SEARCH_API_KEY; the engine expects
    # BRAVE_API_KEY. Bridge it so Brave grounding works without double config.
    if not run_env.get("BRAVE_API_KEY") and run_env.get("BRAVE_SEARCH_API_KEY"):
        run_env["BRAVE_API_KEY"] = run_env["BRAVE_SEARCH_API_KEY"]

    timeout_s = timeout if timeout is not None else ENGINE_TIMEOUT

    logger.info("Running last30days engine: query='%s' timeout=%ss", query[:80], timeout_s)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(SCRIPT_DIR),
            env=run_env,
        )

        if result.returncode != 0:
            stderr_preview = result.stderr[-600:] if result.stderr else "(no stderr)"
            raise RuntimeError(
                f"last30days engine exited code {result.returncode}: {stderr_preview}"
            )

        output = result.stdout.strip()
        if not output:
            logger.warning("last30days engine returned empty output for query: %s", query[:80])
            return ""

        logger.info("last30days engine completed: %d bytes", len(output))
        return output

    except subprocess.TimeoutExpired:
        raise TimeoutError(
            f"last30days engine timed out after {timeout_s}s for query: {query[:80]}"
        )


def run_query_and_extract_citations(query: str, **kwargs) -> tuple[str, list[dict]]:
    """Run query and try to extract citation-like URLs from the result.

    Returns:
        (html_output, citations_list) where citations_list is a list of
        dicts with 'title' and 'url' keys, best-effort extracted.
    """
    html = run_query(query, **kwargs)

    citations: list[dict] = []
    if html:
        import re
        # Extract markdown links [text](url)
        for m in re.finditer(r'\[([^\]]+)\]\(https?://([^\)]+)\)', html):
            citations.append({"title": m.group(1), "url": f"https://{m.group(2)}"})
        # Also plain hrefs
        for m in re.finditer(r'href="(https?://[^"]+)"', html):
            url = m.group(1)
            if not any(c["url"] == url for c in citations):
                citations.append({"title": url, "url": url})

    return html, citations
