"""
Tropelex Sync Exporter
Pure functions for exporting memory data as compressed JSON.
"""

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

EXPORT_VERSION = "1.0.0"


def _collect_memory_files(memory_dir: Path) -> dict[str, dict]:
    """Read all JSON files in memory_dir, keyed by filename stem."""
    return {
        f.stem: json.loads(f.read_text())
        for f in memory_dir.glob("*.json")
        if f.is_file()
    }


def _build_export_payload(memory_files: dict[str, dict]) -> dict:
    """Assemble export payload with metadata and project list."""
    return {
        "metadata": {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "project_count": len(memory_files),
        },
        "projects": list(memory_files.values()),
    }


def export_memory_data(base_path: str) -> bytes:
    """Export all memory files as gzip-compressed JSON bytes.

    Args:
        base_path: Root path containing the memory/ directory.

    Returns:
        Gzip-compressed JSON bytes with metadata and project data.
    """
    memory_dir = Path(base_path) / "memory"
    memory_files = _collect_memory_files(memory_dir) if memory_dir.exists() else {}
    payload = _build_export_payload(memory_files)
    return gzip.compress(json.dumps(payload).encode())
