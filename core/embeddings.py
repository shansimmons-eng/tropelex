"""
Tropelex Embedding Store
Persists and queries OpenAI text-embedding-3-small vectors.
Uses cosine similarity for semantic search — no external vector DB needed.
"""

import json
import math
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("tropelex.embeddings")

EMBED_DIM = 1536  # text-embedding-3-small


def _cosine(a: List[float], b: List[float]) -> float:
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
        self._store: Dict[str, Dict[str, Any]] = {}  # id -> {text, vector, meta}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._store = json.loads(self.path.read_text())
            except Exception as e:
                logger.warning("Could not load embedding store: %s", e)
                self._store = {}

    def _save(self):
        self.path.write_text(json.dumps(self._store, separators=(",", ":")))

    def has(self, key: str) -> bool:
        return key in self._store

    def put(
        self, key: str, text: str, vector: List[float], meta: Optional[Dict] = None
    ):
        self._store[key] = {"text": text, "vector": vector, "meta": meta or {}}
        self._save()

    def delete(self, key: str):
        if key in self._store:
            del self._store[key]
            self._save()

    def search(
        self, query_vector: List[float], top_k: int = 10, min_score: float = 0.5
    ) -> List[Dict]:
        """Return top_k most similar items above min_score."""
        scored = []
        for key, entry in self._store.items():
            score = _cosine(query_vector, entry["vector"])
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
