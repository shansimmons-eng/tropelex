"""
Append-only audit trail — the write-time-hashed event log backing the
Provenance Chain and Security Audit Log (see wishlist.md #52).

Before this module existed, both of those endpoints recomputed their
output from the current, mutable decisions list on every GET, with
chain_valid hardcoded True — editing historical data directly in the
memory JSON produced a perfectly clean-looking response, with no
persisted write-time hash to compare against. This module is the fix:
callers append an entry the moment an event actually happens, its hash
computed once, at write time, chained from the previous *stored* entry's
hash. Extracted out of core/tropebook/web/server.py once a second
consumer (the override endpoint in core/ghost/preventive_router.py, for
#53's enforceable gates) needed the same mechanism — a shared module
beats two independent copies, same reasoning as core/result.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def compute_hash(entry: dict[str, Any]) -> str:
    """Hash a dict for integrity verification (order-independent)."""
    content = json.dumps(entry, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()


def append_audit_event(memory: dict[str, Any], event_type: str, **fields: Any) -> dict[str, Any]:
    """Append a write-time, hash-chained entry to memory["audit_log"].

    Each entry's hash is computed once, here, from the previous *stored*
    entry's hash — not recomputed from current state on every read.
    Callers are responsible for persisting `memory` afterward.
    """
    log = memory.setdefault("audit_log", [])
    previous_hash = log[-1]["hash"] if log else "genesis"
    entry = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "previous_hash": previous_hash,
        **fields,
    }
    entry["hash"] = compute_hash(entry)
    log.append(entry)
    return entry


DECISION_HASH_VERSION = 1


def decision_content_hash(d: dict[str, Any]) -> str:
    """Hash of a decision's content-bearing fields (gap B: tamper-evidence).
    Detects any direct edit to a project's memory JSON that bypasses the
    API. Versioned so the covered-field list can evolve without
    invalidating hashes already stored on existing decisions.
    """
    safety_metadata = d.get("safety_metadata") or {}
    return compute_hash({
        "version": DECISION_HASH_VERSION,
        "decision": d.get("decision", ""),
        "context": d.get("context", ""),
        "risk_level": safety_metadata.get("risk_level", "low"),
        "safety_category": safety_metadata.get("safety_category", "general"),
        "safety_metadata": safety_metadata,
        "content_flags": d.get("content_flags", []),
        "timestamp": d.get("timestamp", ""),
        "id": d.get("id", ""),
    })


def resync_decision_hash(memory: dict[str, Any], d: dict[str, Any], changed_fields: list[str]) -> None:
    """Recompute and store a decision's content hash after legitimately
    mutating it in place, and record the change in the audit trail.

    Every code path that mutates a decision's hash-covered fields
    (decision/context/safety_metadata/content_flags) after creation must
    call this — otherwise verify_integrity flags the decision as tampered
    the next time it's checked, even though the change was legitimate.
    Callers are responsible for persisting `memory` afterward.
    """
    old_hash = d.get("decision_hash")
    new_hash = decision_content_hash(d)
    d["decision_hash"] = new_hash
    append_audit_event(
        memory, "decision_updated",
        decision_id=d.get("id"),
        old_hash=old_hash,
        new_hash=new_hash,
        changed_fields=changed_fields,
    )


def verify_audit_log_chain(audit_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare each audit_log entry's stored hash/previous_hash against a
    fresh recomputation. A mismatch means either the entry's own content
    was edited after being written, or a prior entry was deleted/reordered
    so previous_hash no longer lines up.
    """
    problems = []
    expected_previous = "genesis"
    for i, entry in enumerate(audit_log):
        stored_hash = entry.get("hash")
        recomputed = compute_hash({k: v for k, v in entry.items() if k != "hash"})
        if stored_hash != recomputed:
            problems.append({
                "type": "entry_hash_mismatch",
                "index": i,
                "severity": "high",
                "message": f"audit_log[{i}] ({entry.get('event_type')}) stored hash doesn't match its own content — edited after being written.",
            })
        if entry.get("previous_hash") != expected_previous:
            problems.append({
                "type": "chain_link_broken",
                "index": i,
                "severity": "high",
                "message": f"audit_log[{i}] previous_hash doesn't match the prior entry's hash — an entry was deleted, reordered, or inserted.",
            })
        expected_previous = stored_hash
    return problems
