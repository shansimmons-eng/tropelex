"""
Tests for core.embeddings — EmbeddingStore and the shared
get_decision_embeddings cache (#57, extracted/shared in #67).

Most of get_decision_embeddings's behavior (caching, partial-cache reuse,
graceful no-key fallback) is already exercised indirectly via
tests/test_contradictions.py's TestGetDecisionEmbeddings (through the thin
core.contradictions.router._get_decision_embeddings wrapper). These tests
call the shared function directly, proving it's genuinely reusable and not
accidentally coupled to Contradiction Detection's own module.
"""

import asyncio
from unittest.mock import patch

import pytest

from core.embeddings import EmbeddingStore, cosine_similarity, get_decision_embeddings


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector_does_not_raise(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestGetDecisionEmbeddingsShared:
    """Calls core.embeddings.get_decision_embeddings directly (not through
    a detector-specific wrapper), with an explicit store_dir so it never
    touches a real project's cache on disk."""

    def _decisions(self):
        return [
            {"id": "x", "decision": "Use snake_case for module functions"},
            {"id": "y", "decision": "Never bypass authentication checks"},
        ]

    def test_no_api_key_returns_none(self, tmp_path):
        with patch("core.embeddings.embed", return_value=None) as mock_embed:
            result = asyncio.run(get_decision_embeddings("proj", self._decisions(), store_dir=tmp_path))
        assert result is None
        mock_embed.assert_called_once()

    def test_success_caches_and_returns_all_vectors(self, tmp_path):
        vectors = [[1.0, 0.0], [0.0, 1.0]]
        with patch("core.embeddings.embed", return_value=vectors):
            result = asyncio.run(get_decision_embeddings("proj", self._decisions(), store_dir=tmp_path))
        assert result == {"x": [1.0, 0.0], "y": [0.0, 1.0]}

    def test_second_call_uses_cache(self, tmp_path):
        vectors = [[1.0, 0.0], [0.0, 1.0]]
        with patch("core.embeddings.embed", return_value=vectors) as mock_embed:
            asyncio.run(get_decision_embeddings("proj", self._decisions(), store_dir=tmp_path))
            mock_embed.reset_mock()
            result = asyncio.run(get_decision_embeddings("proj", self._decisions(), store_dir=tmp_path))
        mock_embed.assert_not_called()
        assert result == {"x": [1.0, 0.0], "y": [0.0, 1.0]}

    def test_default_store_dir_matches_contradictions_convention(self, tmp_path, monkeypatch):
        """Not passing store_dir falls back to the module default -- proven
        by patching the default constant itself rather than asserting a
        hardcoded path, so this doesn't silently drift from the real
        constant's value."""
        monkeypatch.setattr("core.embeddings._DEFAULT_STORE_DIR", tmp_path)
        with patch("core.embeddings.embed", return_value=[[1.0, 0.0]]):
            result = asyncio.run(get_decision_embeddings("proj", [self._decisions()[0]]))
        assert result == {"x": [1.0, 0.0]}
        assert (tmp_path / "contradictions_proj.json").exists()

    def test_empty_decisions_returns_none(self, tmp_path):
        with patch("core.embeddings.embed", return_value=None) as mock_embed:
            result = asyncio.run(get_decision_embeddings("proj", [], store_dir=tmp_path))
        assert result is None
        mock_embed.assert_not_called()

    def test_store_failure_degrades_to_none_not_raise(self, tmp_path):
        """Disk/permission/corrupted-cache failures must never propagate as
        an unhandled exception -- same fallback contract as no-API-key."""
        with patch("core.embeddings.EmbeddingStore.put", side_effect=OSError("disk full")), \
             patch("core.embeddings.embed", return_value=[[1.0, 0.0]]):
            result = asyncio.run(get_decision_embeddings("proj", self._decisions(), store_dir=tmp_path))
        assert result is None


class TestEmbeddingStoreBasics:
    def test_put_then_get_roundtrips(self, tmp_path):
        store = EmbeddingStore(str(tmp_path / "s.json"))
        store.put("a", "text", [1.0, 2.0])
        assert store.get("a") == [1.0, 2.0]

    def test_has_false_for_unknown_key(self, tmp_path):
        store = EmbeddingStore(str(tmp_path / "s.json"))
        assert store.has("nope") is False

    def test_persists_across_instances(self, tmp_path):
        path = str(tmp_path / "s.json")
        EmbeddingStore(path).put("a", "text", [1.0, 2.0])
        reloaded = EmbeddingStore(path)
        assert reloaded.get("a") == [1.0, 2.0]
