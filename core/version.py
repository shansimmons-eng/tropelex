"""
Single source of truth for Tropelex's two independent version numbers.

Before this module existed, the app version was hardcoded in four separate
places (pyproject.toml, /api/health, and twice in the dashboard HTML),
free to silently drift out of sync with each other. Worse: Settings'
"Export Everything" flow wrote a version field into its export payload
that was never read back on import -- a mismatched-schema import could
silently overwrite project files with no warning at all.

Two different things are versioned here, not one:

- APP_VERSION: the release identifier (pyproject.toml's `version`,
  semver). Changes with every release, whether or not that release
  touches the on-disk/export data shape.
- MEMORY_SCHEMA_VERSION: bumped ONLY when the memory/export JSON *shape*
  changes in a way that could break cross-version import -- a field
  renamed, removed, or retyped. A release that doesn't touch data shape
  does not bump this. Mirrors how most databases separate "release
  version" from "file format version" (e.g. SQLite) -- a deliberate,
  documented policy, not an incidental number.

A future change to memory/export shape should bump MEMORY_SCHEMA_VERSION
here, in this same commit -- this is the one place that's supposed to
change when that happens.
"""

from __future__ import annotations

import re
from pathlib import Path

_PYPROJECT_PATH = Path(__file__).parent.parent / "pyproject.toml"
_VERSION_LINE_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _read_app_version() -> str:
    """Parse `version = "X.Y.Z"` out of pyproject.toml with a small regex
    rather than a TOML parser -- tomllib is 3.11+ stdlib only and this
    project supports 3.10 (pyproject.toml's own requires-python), so a
    regex on one simple key=value line avoids adding a parsing dependency
    for a single field. Never raises: this feeds /api/health, which must
    not break because a packaging file changed shape or went missing.
    """
    try:
        content = _PYPROJECT_PATH.read_text()
        match = _VERSION_LINE_RE.search(content)
        return match.group(1) if match else "unknown"
    except OSError:
        return "unknown"


APP_VERSION: str = _read_app_version()

MEMORY_SCHEMA_VERSION: int = 1
