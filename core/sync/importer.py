"""
Tropelex Sync Importer
Import memory data from compressed or plain JSON files.
"""

import gzip
import json
from pathlib import Path

REQUIRED_FIELDS = {"projects"}


def _decompress_data(data: bytes) -> str:
    """Decompress gzip data or return as-is if plain text."""
    try:
        return gzip.decompress(data).decode("utf-8")
    except (gzip.BadGzipFile, OSError):
        return data.decode("utf-8")


def _validate_schema(import_data: dict) -> list[str]:
    """Check required fields and return list of errors (empty = valid).

    Accepts both flat format ({"version": ..., "projects": ...})
    and wrapped format ({"metadata": {"version": ...}, "projects": ...}).
    """
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in import_data:
            errors.append(f"Missing required field: {field}")
    # version may be top-level or inside metadata
    if "version" not in import_data and "metadata" not in import_data:
        errors.append("Missing required field: version (or metadata)")
    if not isinstance(import_data.get("projects", []), list):
        errors.append("'projects' must be a list")
    return errors


def _is_safe_project_name(name: str) -> bool:
    """Reject directory traversal patterns in project names."""
    if not name or ".." in name or "/" in name or "\\" in name:
        return False
    return all(c.isalnum() or c in "-_" for c in name)


def _merge_project(existing: dict, incoming: dict) -> dict:
    """Merge incoming project data into existing, incoming wins on conflict."""
    merged = {**existing}
    for key, value in incoming.items():
        if key in ("decisions", "session_history") and key in merged:
            existing_ids = {
                (d.get("timestamp"), d.get("decision")) for d in merged[key]
            }
            for item in value:
                item_id = (item.get("timestamp"), item.get("decision"))
                if item_id not in existing_ids:
                    merged[key] = merged.get(key, []) + [item]
        else:
            merged[key] = value
    merged["last_updated"] = incoming.get("last_updated", merged.get("last_updated"))
    return merged


def _write_project_file(base_path: str, project_name: str, data: dict) -> None:
    """Write a single project JSON file to the memory directory."""
    memory_dir = Path(base_path) / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    target = memory_dir / f"{project_name}.json"
    with open(target, "w") as f:
        json.dump(data, f, indent=2)


def _load_existing_project(base_path: str, project_name: str) -> dict | None:
    """Load existing project file if present, else None."""
    path = Path(base_path) / "memory" / f"{project_name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def import_memory_data(
    data: bytes, base_path: str, overwrite: bool = False
) -> dict:
    """Import memory from gzip or plain JSON. Returns import summary."""
    summary = {"projects_imported": 0, "files_written": 0, "errors": []}

    try:
        raw = _decompress_data(data)
    except (UnicodeDecodeError, OSError) as exc:
        summary["errors"].append(f"Failed to decode import data: {exc}")
        return summary

    try:
        import_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        summary["errors"].append(f"Invalid JSON: {exc}")
        return summary

    errors = _validate_schema(import_data)
    if errors:
        summary["errors"].extend(errors)
        return summary

    for project in import_data.get("projects", []):
        name = project.get("project_name", "")
        if not _is_safe_project_name(name):
            summary["errors"].append(f"Rejected unsafe project name: {name!r}")
            continue

        try:
            if overwrite:
                _write_project_file(base_path, name, project)
            else:
                existing = _load_existing_project(base_path, name)
                merged = _merge_project(existing or {}, project)
                _write_project_file(base_path, name, merged)

            summary["projects_imported"] += 1
            summary["files_written"] += 1
        except OSError as exc:
            summary["errors"].append(f"Write failed for {name}: {exc}")

    return summary
