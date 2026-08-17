"""
Tropelex Decision Tree
Tracks decision evolution, rationale chains, and relationships between decisions.
Turns flat decision lists into an explorable graph.
"""

import re
from datetime import datetime, timezone
from typing import Any


# Relationship types between decisions
REL_SUPERSEDES = "supersedes"      # A replaces/overrides B
REL_CAUSED_BY = "caused_by"        # A happened because of B
REL_RELATED = "related_to"         # A and B are thematically related
REL_REVERTS = "reverts"            # A reverts B
REL_DEPENDS = "depends_on"         # A requires B to be valid
REL_EVOLVES = "evolves"            # A is a refinement of B


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from a decision text."""
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "not", "so", "if", "then", "that", "this", "it", "its", "we", "our",
        "i", "my", "you", "your", "he", "she", "they", "them", "their",
        "added", "changed", "fixed", "refactored", "removed", "updated",
        "switched", "migrated", "replaced", "reverted", "optimised",
    }
    words = re.findall(r"[a-z][a-z0-9+#_]{2,}", text.lower())
    return {w for w in words if w not in stop}


def _similarity(kw1: set[str], kw2: set[str]) -> float:
    """Jaccard similarity between two keyword sets."""
    if not kw1 or not kw2:
        return 0.0
    return len(kw1 & kw2) / len(kw1 | kw2)


def _is_revert(decision_text: str) -> bool:
    """Check if a decision text indicates a revert."""
    lower = decision_text.lower()
    return any(kw in lower for kw in ["revert", "undo", "roll back", "switch back"])


def _is_removal(decision_text: str) -> bool:
    """Check if a decision removes something."""
    lower = decision_text.lower()
    return any(kw in lower for kw in ["removed", "dropped", "deprecated", "replaced"])


def _find_supersedes(new: dict, existing: list[dict]) -> list[str]:
    """
    Find decisions that the new decision supersedes.
    A decision supersedes another if it targets the same topic but with
    an opposite or updated action.
    """
    new_kw = _extract_keywords(new.get("decision", ""))
    superseded = []

    for d in existing:
        old_kw = _extract_keywords(d.get("decision", ""))
        sim = _similarity(new_kw, old_kw)

        # High similarity + one is a removal/revert = supersedes
        if sim > 0.3:
            if _is_revert(new.get("decision", "")) or _is_removal(new.get("decision", "")):
                superseded.append(d.get("id", ""))
            elif _is_removal(d.get("decision", "")):
                # New decision re-adds something that was removed
                superseded.append(d.get("id", ""))

    return superseded


def _find_caused_by(new: dict, existing: list[dict]) -> list[str]:
    """
    Find decisions that caused the new decision.
    Looks for rationale signals in the new decision referencing existing ones.
    """
    rationale = new.get("rationale", "")
    context = new.get("context", "")
    text = f"{rationale} {context}".lower()

    if not text.strip():
        return []

    caused = []
    signals = ["because", "due to", "caused by", "following", "after", "in response to"]

    for d in existing:
        old_decision = d.get("decision", "").lower()
        old_kw = _extract_keywords(old_decision)

        # Check if rationale explicitly references the old decision
        for word in old_kw:
            if word in text and any(s in text for s in signals):
                caused.append(d.get("id", ""))
                break

    return caused


def _find_related(new: dict, existing: list[dict], threshold: float = 0.25) -> list[str]:
    """Find thematically related decisions via keyword overlap."""
    new_kw = _extract_keywords(new.get("decision", ""))
    related = []

    for d in existing:
        old_kw = _extract_keywords(d.get("decision", ""))
        if _similarity(new_kw, old_kw) >= threshold:
            related.append(d.get("id", ""))

    return related


class DecisionTree:
    """
    Manages a graph of decisions with relationships.

    Each decision node has:
    - id: the decision's real, persisted id (git hash or generated only as
      a fallback when no id is present yet)
    - decision: the decision text
    - context: why it was made
    - rationale: explicit reasoning (optional)
    - timestamp: when it was made
    - source: where it came from (git, manual, git_deep)
    - edges: list of {target_id, relationship, created_at}

    Edge types:
    - supersedes: this decision replaces the target
    - caused_by: this decision was caused by the target
    - related_to: thematically similar
    - reverts: this decision reverts the target
    - depends_on: this decision depends on the target
    - evolves: this decision refines the target
    """

    def __init__(self):
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, str]] = []

    def add_decision(self, decision: dict[str, Any]) -> str:
        """
        Add a decision and auto-detect relationships.
        Returns the decision ID.
        """
        # id must win over hash: every other decision-lookup endpoint
        # (interpretability, versions, safety review, tag, approve...)
        # matches by the decision's real, persisted id. MemoryManager
        # backfills that onto every decision on load, so it's always
        # present by the time this runs -- preferring hash here made the
        # timeline/detail views return a value none of those endpoints
        # recognized for git-imported decisions (id != hash), 404ing on
        # Inspect for every one of them.
        did = decision.get("id") or decision.get("hash") or _gen_id(decision)
        decision["id"] = did

        # Auto-detect relationships before adding
        existing = list(self.nodes.values())
        relationships = self._detect_relationships(decision, existing)

        # Store the node
        self.nodes[did] = {
            "id": did,
            "hash": decision.get("hash", ""),
            "decision": decision.get("decision", ""),
            "context": decision.get("context", ""),
            "rationale": decision.get("rationale", ""),
            "timestamp": decision.get("timestamp", _now()),
            "source": decision.get("source", "manual"),
            "categories": decision.get("categories", []),
            "is_revert": decision.get("is_revert", False),
            "reverts": decision.get("reverts"),
            "edges": [],
        }

        # Add edges
        for rel_type, targets in relationships.items():
            for target_id in targets:
                edge = {
                    "source": did,
                    "target": target_id,
                    "relationship": rel_type,
                    "created_at": _now(),
                }
                self.edges.append(edge)
                self.nodes[did]["edges"].append(edge)

        return did

    def _detect_relationships(
        self, new_decision: dict, existing: list[dict]
    ) -> dict[str, list[str]]:
        """Auto-detect all relationships for a new decision."""
        rels: dict[str, list[str]] = {}

        # Supersedes
        supersedes = _find_supersedes(new_decision, existing)
        if supersedes:
            rels["supersedes"] = supersedes

        # Caused by
        caused_by = _find_caused_by(new_decision, existing)
        if caused_by:
            rels["caused_by"] = caused_by

        # Related
        related = _find_related(new_decision, existing)
        if related:
            rels["related_to"] = related

        # Explicit revert
        if new_decision.get("is_revert"):
            reverts_target = new_decision.get("reverts")
            if reverts_target:
                # Find by partial hash match -- explicitly against the git
                # hash, not node id now that id no longer *is* the hash.
                for d in existing:
                    if (d.get("hash") or d.get("id", "")).startswith(reverts_target[:7]):
                        rels.setdefault("reverts", []).append(d["id"])
                        break

        return rels

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        """Get a decision by ID."""
        return self.nodes.get(decision_id)

    def get_ancestors(self, decision_id: str, max_depth: int = 5) -> list[dict]:
        """Walk backwards through caused_by/supersedes edges to find decision chain."""
        visited = set()
        result = []

        def _walk(did: str, depth: int):
            if depth >= max_depth or did in visited:
                return
            visited.add(did)
            node = self.nodes.get(did)
            if not node:
                return
            for edge in self.edges:
                if edge["source"] == did and edge["relationship"] in ("caused_by", "supersedes", "reverts"):
                    target = self.nodes.get(edge["target"])
                    if target:
                        result.append({
                            "decision": target,
                            "relationship": edge["relationship"],
                            "depth": depth + 1,
                        })
                        _walk(edge["target"], depth + 1)

        _walk(decision_id, 0)
        return result

    def get_descendants(self, decision_id: str, max_depth: int = 5) -> list[dict]:
        """Walk forwards through edges to find what this decision led to."""
        visited = set()
        result = []

        def _walk(did: str, depth: int):
            if depth >= max_depth or did in visited:
                return
            visited.add(did)
            for edge in self.edges:
                if edge["target"] == did:
                    source = self.nodes.get(edge["source"])
                    if source:
                        result.append({
                            "decision": source,
                            "relationship": edge["relationship"],
                            "depth": depth + 1,
                        })
                        _walk(edge["source"], depth + 1)

        _walk(decision_id, 0)
        return result

    def get_timeline(self) -> list[dict]:
        """Get all decisions sorted by timestamp, with relationship info."""
        sorted_nodes = sorted(
            self.nodes.values(), key=lambda x: x.get("timestamp", "")
        )
        timeline = []
        for node in sorted_nodes:
            incoming = [
                e for e in self.edges if e["target"] == node["id"]
            ]
            outgoing = [
                e for e in self.edges if e["source"] == node["id"]
            ]
            timeline.append({
                **node,
                "incoming_relationships": [
                    {"from": e["source"], "type": e["relationship"]} for e in incoming
                ],
                "outgoing_relationships": [
                    {"to": e["target"], "type": e["relationship"]} for e in outgoing
                ],
            })
        return timeline

    def get_chains(self) -> list[list[dict]]:
        """
        Find decision chains: sequences where A caused B caused C.
        Returns list of chains, each a list of decisions in order.
        """
        # Find chain roots (nodes with no incoming caused_by edges)
        caused_targets = {
            e["target"] for e in self.edges if e["relationship"] == "caused_by"
        }
        roots = [
            did for did in self.nodes if did not in caused_targets
        ]

        chains = []
        for root in roots:
            chain = self._build_chain(root)
            if len(chain) > 1:
                chains.append(chain)

        # Also find revert chains
        revert_chains = self._find_revert_chains()
        chains.extend(revert_chains)

        return chains

    def _build_chain(self, start_id: str, max_depth: int = 10) -> list[dict]:
        """Build a chain starting from a decision following caused_by edges."""
        chain = []
        visited = set()
        current = start_id

        while current and current not in visited and len(chain) < max_depth:
            visited.add(current)
            node = self.nodes.get(current)
            if not node:
                break
            chain.append(node)

            # Find next in chain (caused_by edges pointing FROM current)
            next_id = None
            for edge in self.edges:
                if edge["source"] == current and edge["relationship"] == "caused_by":
                    if edge["target"] not in visited:
                        next_id = edge["target"]
                        break
            current = next_id

        return chain

    def _find_revert_chains(self) -> list[list[dict]]:
        """Find chains of decisions that revert each other."""
        chains = []
        revert_edges = [e for e in self.edges if e["relationship"] == "reverts"]

        for edge in revert_edges:
            chain = []
            source = self.nodes.get(edge["source"])
            target = self.nodes.get(edge["target"])
            if source and target:
                chain = [target, source]  # original, then revert
                chains.append(chain)

        return chains

    def to_dict(self) -> dict[str, Any]:
        """Serialize the tree to a dict for JSON storage."""
        return {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionTree":
        """Deserialize from a dict."""
        tree = cls()
        for node in data.get("nodes", []):
            tree.nodes[node["id"]] = node
        tree.edges = data.get("edges", [])
        return tree

    @classmethod
    def from_decisions(cls, decisions: list[dict]) -> "DecisionTree":
        """Build a tree from a flat list of decisions."""
        tree = cls()
        for d in decisions:
            tree.add_decision(d)
        return tree

    def stats(self) -> dict[str, Any]:
        """Return summary statistics."""
        rel_counts: dict[str, int] = {}
        for e in self.edges:
            rel_counts[e["relationship"]] = rel_counts.get(e["relationship"], 0) + 1

        return {
            "total_decisions": len(self.nodes),
            "total_edges": len(self.edges),
            "relationship_counts": rel_counts,
            "chains": len(self.get_chains()),
        }


def _gen_id(decision: dict) -> str:
    """Generate a deterministic ID from decision content."""
    import hashlib

    text = decision.get("decision", "") + decision.get("timestamp", "")
    return hashlib.sha256(text.encode()).hexdigest()[:12]
