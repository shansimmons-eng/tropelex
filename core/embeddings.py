"""
Tropelex Embedding Store
Persists and queries OpenAI text-embedding-3-small vectors.
Uses cosine similarity for semantic search — no external vector DB needed.
"""

import fcntl
import json
import logging
import math
from pathlib import Path
from typing import Any

from core.llm import embed

logger = logging.getLogger("tropelex.embeddings")

EMBED_DIM = 1536  # text-embedding-3-small

_DEFAULT_STORE_DIR = Path(__file__).resolve().parent.parent / "memory" / "embeddings"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors. Public so other
    detectors (Ghost's semantic rescue, #67) can share this instead of each
    keeping its own private copy."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingStore:
    """
    Flat vector store backed by a JSON file.
    Keys are arbitrary string IDs (citation IDs, project names, etc.)
    """

    def __init__(self, storage_path: str):
        self.path = Path(storage_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._store: dict[str, dict[str, Any]] = {}  # id -> {text, vector, meta}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._store = json.loads(self.path.read_text())
            except Exception as e:
                logger.warning("Could not load embedding store: %s", e)
                self._store = {}

    def _save(self):
        """Write store to disk with exclusive lock for concurrent safety."""
        fd = None
        try:
            fd = open(self.path, "w")
            fcntl.flock(fd, fcntl.LOCK_EX)
            fd.write(json.dumps(self._store, separators=(",", ":")))
        finally:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                fd.close()

    def has(self, key: str) -> bool:
        return key in self._store

    def get(self, key: str) -> list[float] | None:
        """Return the stored vector for `key`, or None if absent."""
        entry = self._store.get(key)
        return entry["vector"] if entry else None

    def put(
        self, key: str, text: str, vector: list[float], meta: dict | None = None
    ):
        self._store[key] = {"text": text, "vector": vector, "meta": meta or {}}
        self._save()

    def delete(self, key: str):
        if key in self._store:
            del self._store[key]
            self._save()

    def search(
        self, query_vector: list[float], top_k: int = 10, min_score: float = 0.5
    ) -> list[dict]:
        """Return top_k most similar items above min_score."""
        scored = []
        for key, entry in self._store.items():
            score = cosine_similarity(query_vector, entry["vector"])
            if score >= min_score:
                scored.append(
                    {
                        "id": key,
                        "score": round(score, 4),
                        "text": entry["text"],
                        "meta": entry["meta"],
                    }
                )
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._store)

    def clear(self):
        self._store = {}
        self._save()


async def get_decision_embeddings(
    project: str,
    decisions: list[dict[str, Any]],
    store_dir: Path | None = None,
) -> dict[str, list[float]] | None:
    """Best-effort {decision_id: vector} lookup, shared by every detector
    that wants #57's hybrid keyword/semantic similarity (Contradiction
    Detection, and #67's Ghost Preventive semantic rescue). Decision
    embeddings are derived purely from decision text, not detector-specific
    — one cache correctly serves all callers, so this was extracted out of
    core/contradictions/router.py's original private copy rather than
    duplicated a second time for Ghost.

    Cached per-project via EmbeddingStore, keyed by decision id, so a
    decision is only ever sent to OpenAI once. Defaults to the exact store
    path #57 already established (memory/embeddings/contradictions_{project}.json)
    so existing caches are reused as-is, zero migration.

    Returns None (not a partial dict) whenever embeddings aren't usable at
    all — no OPENAI_API_KEY configured, the API call itself fails, or the
    on-disk cache is unreadable/unwritable (permissions, disk full,
    corrupted state) — so callers' fallback to pure keyword matching is a
    clean, explicit branch rather than a dict silently missing some entries
    or an unhandled exception reaching an HTTP endpoint as a 500.
    """
    base_dir = store_dir if store_dir is not None else _DEFAULT_STORE_DIR
    try:
        store = EmbeddingStore(str(base_dir / f"contradictions_{project}.json"))
        to_embed = [d for d in decisions if d.get("id") and not store.has(d["id"])]

        if to_embed:
            texts = [d.get("decision", "") for d in to_embed]
            vectors = await embed(texts, project=project)
            if vectors is None:
                logger.info("decision embeddings unavailable for %s, falling back to keyword-only", project)
            else:
                for d, vec in zip(to_embed, vectors):
                    store.put(d["id"], d.get("decision", ""), vec)

        result = {d["id"]: store.get(d["id"]) for d in decisions if d.get("id") and store.has(d["id"])}
        return result or None
    except Exception as exc:
        logger.warning("decision embeddings cache failed for %s (%s), falling back to keyword-only", project, exc)
        return None
