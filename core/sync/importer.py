"""
Tropelex Sync Importer
Import memory data from compressed or plain JSON files.
"""

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = {"projects"}


def _exporting_instance_id(import_data: dict) -> str | None:
    """The exporting install's id, accepting both the wrapped format
    ({"metadata": {"instance_id": ...}}) and a flat top-level
    "instance_id" -- same both-formats tolerance _validate_schema already
    has for "version"."""
    metadata = import_data.get("metadata")
    if isinstance(metadata, dict) and metadata.get("instance_id"):
        return metadata["instance_id"]
    return import_data.get("instance_id")


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

    # #provenance: stamp each written project with where it came from
    # (core/identity.py), same differs-from-own-id guard as account_import
    # -- re-importing your own earlier backup onto the same machine
    # shouldn't relabel your own native data as foreign.
    from core.identity import get_or_create_instance_id

    exporting_instance_id = _exporting_instance_id(import_data)
    this_instance_id = get_or_create_instance_id(Path(base_path))
    stamp_provenance = bool(exporting_instance_id) and exporting_instance_id != this_instance_id

    for project in import_data.get("projects", []):
        name = project.get("project_name", "")
        if not _is_safe_project_name(name):
            summary["errors"].append(f"Rejected unsafe project name: {name!r}")
            continue

        if stamp_provenance:
            project["_imported_from_instance_id"] = exporting_instance_id
            project["_imported_at"] = datetime.now(timezone.utc).isoformat()

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
