"""
Plugin loader for Tropelex.

Discovers plugins via plugin.json manifests in a given directory.
Each manifest must conform to the schema:
    {name: str, version: str, hooks: list[str], entry_point: str}

All public functions are pure — no mutation, no side effects.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_MANIFEST_KEYS = {"name", "version", "hooks", "entry_point"}
MANIFEST_FILENAME = "plugin.json"


def _read_manifest(manifest_path: Path) -> dict | None:
    """Read and parse a single plugin.json file. Returns None on failure."""
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Skipping malformed manifest %s: %s", manifest_path, exc)
        return None


def _validate_manifest(data: dict, manifest_path: Path) -> str | None:
    """Validate manifest schema. Returns error message or None if valid."""
    if not isinstance(data, dict):
        return f"Manifest is not a JSON object: {manifest_path}"

    missing = REQUIRED_MANIFEST_KEYS - data.keys()
    if missing:
        return f"Missing required keys {missing} in {manifest_path}"

    if not isinstance(data["name"], str) or not data["name"]:
        return f"'name' must be a non-empty string in {manifest_path}"

    if not isinstance(data["version"], str) or not data["version"]:
        return f"'version' must be a non-empty string in {manifest_path}"

    if not isinstance(data["hooks"], list):
        return f"'hooks' must be a list in {manifest_path}"

    if not isinstance(data["entry_point"], str) or not data["entry_point"]:
        return f"'entry_point' must be a non-empty string in {manifest_path}"

    return None


def validate_manifest(data: dict, manifest_path: Path) -> dict | None:
    """Validate and normalize a manifest. Returns validated dict or None."""
    error = _validate_manifest(data, manifest_path)
    if error:
        logger.warning("Invalid manifest: %s", error)
        return None
    return {
        "name": data["name"],
        "version": data["version"],
        "hooks": list(data["hooks"]),
        "entry_point": data["entry_point"],
    }


def discover_plugins(plugins_dir: str) -> list[dict]:
    """Discover all valid plugins under *plugins_dir*.

    Walks immediate subdirectories looking for ``plugin.json`` files.
    Malformed or invalid manifests are skipped with a warning.

    Args:
        plugins_dir: Path to the directory containing plugin subdirectories.

    Returns:
        List of validated plugin manifest dicts, each containing
        ``name``, ``version``, ``hooks``, and ``entry_point`` keys.
    """
    base = Path(plugins_dir)
    if not base.is_dir():
        logger.warning("Plugins directory does not exist: %s", plugins_dir)
        return []

    plugins: list[dict] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.is_file():
            continue

        raw = _read_manifest(manifest_path)
        if raw is None:
            continue

        validated = validate_manifest(raw, manifest_path)
        if validated is not None:
            plugins.append(validated)

    return plugins
