"""
Test Suite Status — runs `pytest --collect-only` to report a real test
count.

Replaces the "1455 Passed" string that was hardcoded directly in the
dashboard's Getting Started card and Run Diagnostics panel -- never wired
to anything real, in either the initial HTML or the "Re-test All Systems"
click handler, and stuck at that number long after the suite grew past it.

Collect-only, not a full run: fast (~1s for this suite), no execution
side effects, just an accurate count -- matching what a diagnostics check
should cost, not the price of running the whole suite on every click.
"""

from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger("tropelex.test_suite_status")

_COUNT_PATTERN = re.compile(r"(\d+)\s+tests?\s+collected")


def get_test_count(base_dir: str, timeout: int = 30) -> dict:
    """Run `pytest --collect-only -q` and parse the total test count.

    Returns {"ok": True, "count": N} on success, or
    {"ok": False, "error": "..."} if pytest isn't available, collection
    times out, or the output couldn't be parsed (e.g. a collection error
    from a broken import).
    """
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "--collect-only", "-q"],
            cwd=base_dir, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("pytest not found when counting tests")
        return {"ok": False, "error": "pytest not found"}
    except subprocess.TimeoutExpired:
        logger.error("test collection timed out after %ss", timeout)
        return {"ok": False, "error": f"collection timed out after {timeout}s"}
    except OSError as e:
        logger.error("test collection failed: %s", e)
        return {"ok": False, "error": str(e)}

    output = result.stdout + result.stderr
    match = _COUNT_PATTERN.search(output)
    if not match:
        tail = output.strip().splitlines()[-1] if output.strip() else "no output"
        logger.warning("could not parse pytest collect-only output: %s", tail)
        return {"ok": False, "error": f"could not parse test count: {tail}"}

    return {"ok": True, "count": int(match.group(1))}
