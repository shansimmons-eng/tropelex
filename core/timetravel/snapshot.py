"""
Time-Travel Debugger — pure functions for snapshot reconstruction and diffing.

All functions are pure: same input → same output, no side effects.
Business logic returns Result; IO boundaries raise domain exceptions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.timetravel import (
    Err,
    MemoryError,
    MemorySnapshot,
    Ok,
    Result,
    SnapshotDiff,
    ValidationError,
)


# ── Date parsing ────────────────────────────────────────────────────────────


def _parse_date(date_str: str) -> datetime:
    """Parse an ISO 8601 or YYYY-MM-DD string into a timezone-aware datetime.

    Raises ValidationError on malformed input.
    """
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            # Assume UTC if no timezone info
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValidationError(
        f"Invalid date format: {date_str!r}. Use YYYY-MM-DD or ISO 8601.",
        details={"provided": date_str},
    )


def _parse_session_ts(session: dict[str, Any]) -> datetime:
    """Extract and parse a session's timestamp."""
    ts = session.get("timestamp")
    if not ts:
        raise ValidationError(
            "Session missing 'timestamp' field",
            details={"session_id": session.get("session_id")},
        )
    return _parse_date(str(ts))


# ── Core pure functions ─────────────────────────────────────────────────────


def reconstruct_memory_at_date(
    sessions: list[dict[str, Any]],
    target_date: str,
) -> Result[MemorySnapshot]:
    """Replay sessions up to ``target_date`` and return the resulting memory state.

    Sessions must each contain at least ``timestamp`` and ``snapshot_after``.

    Returns:
        Ok(MemorySnapshot) on success.
        Err if no sessions exist before the target date.
    """
    try:
        target_dt = _parse_date(target_date)
    except ValidationError as exc:
        return Err(error=str(exc), code="VALIDATION_ERROR", details=exc.details)

    # Filter and sort sessions chronologically
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    for s in sessions:
        try:
            sdt = _parse_session_ts(s)
        except ValidationError:
            continue  # skip malformed sessions
        if sdt <= target_dt:
            eligible.append((sdt, s))

    if not eligible:
        return Err(
            error=f"No sessions found before {target_date}",
            code="NOT_FOUND",
            details={"target_date": target_date},
        )

    eligible.sort(key=lambda pair: pair[0])
    _last_dt, last_session = eligible[-1]

    memory: dict[str, Any] = last_session.get("snapshot_after", {})
    decisions = memory.get("decisions", [])

    return Ok(
        MemorySnapshot(
            project_name=last_session.get("project", ""),
            snapshot_date=_last_dt.isoformat(),
            memory=memory,
            decision_count=len(decisions),
            session_count=len(eligible),
        )
    )


def diff_snapshots(
    snap_a: MemorySnapshot,
    snap_b: MemorySnapshot,
) -> SnapshotDiff:
    """Compute the difference between two memory snapshots.

    Compares decisions and session counts, producing a human-readable summary.
    """
    dec_a = set(snap_a.memory.get("decisions", []))
    dec_b = set(snap_b.memory.get("decisions", []))

    # Decisions may be dicts or strings — normalize to comparable keys
    def _decision_key(d: Any) -> str:
        if isinstance(d, dict):
            return str(d.get("id", d.get("decision", id(d))))
        return str(d)

    keys_a = {_decision_key(d) for d in dec_a}
    keys_b = {_decision_key(d) for d in dec_b}

    added = sorted(keys_b - keys_a)
    removed = sorted(keys_a - keys_b)

    sess_delta = snap_b.session_count - snap_a.session_count
    parts: list[str] = []
    if added:
        parts.append(f"{len(added)} decision(s) added")
    if removed:
        parts.append(f"{len(removed)} decision(s) removed")
    if sess_delta:
        parts.append(f"{sess_delta:+d} session(s)")
    summary = "; ".join(parts) if parts else "No changes detected"

    return SnapshotDiff(
        date_from=snap_a.snapshot_date,
        date_to=snap_b.snapshot_date,
        decisions_added=added,
        decisions_removed=removed,
        sessions_added=sess_delta,
        changes_summary=summary,
    )


def find_nearest_snapshot(
    sessions: list[dict[str, Any]],
    target_date: str,
) -> dict[str, Any] | None:
    """Find the session whose timestamp is closest to ``target_date``.

    Returns the session dict, or None if ``sessions`` is empty.
    """
    try:
        target_dt = _parse_date(target_date)
    except ValidationError:
        return None

    nearest: dict[str, Any] | None = None
    min_delta: float = float("inf")

    for s in sessions:
        try:
            sdt = _parse_session_ts(s)
        except ValidationError:
            continue
        delta = abs((sdt - target_dt).total_seconds())
        if delta < min_delta:
            min_delta = delta
            nearest = s

    return nearest
