"""
Tests for Memory Compaction — epoch, compactor, and router.

Covers identify_compactable_chains, generate_epoch_summary,
merge_chain_to_epoch, apply_compaction, estimate_token_savings,
compact_memory, and router endpoints.

Uses pytest, AAA pattern, no shared state, all externals mocked.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.compaction import Err, Ok
from core.compaction.compactor import (
    CompactionResult,
    apply_compaction,
    archive_originals,
    build_compaction_report,
    compact_memory,
    estimate_token_savings,
)
from core.compaction.epoch import (
    CompactionChain,
    EpochRecord,
    EpochSummary,
    generate_epoch_summary,
    identify_compactable_chains,
    merge_chain_to_epoch,
)
from core.compaction.router import (
    MemoryNotFoundError,
    ValidationError,
    _compaction_status,
    _result_to_http,
    _validate_project,
    compaction_router,
)


# ---------------------------------------------------------------------------
#  Helpers — realistic mock data
# ---------------------------------------------------------------------------

def _ts(days_ago: int) -> str:
    """ISO timestamp N days ago — ensures stale decay scores."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def _decision(did: str, text: str, ts_days_ago: int = 30, **extra) -> dict:
    """Create a decision dict matching project memory schema."""
    return {
        "id": did,
        "decision": text,
        "timestamp": _ts(ts_days_ago),
        "context": extra.get("context", ""),
        "rationale": extra.get("rationale", ""),
        **{k: v for k, v in extra.items() if k not in ("context", "rationale")},
    }


def _make_chain(
    members: list[dict],
    topic: str = "auth",
    chain_id: str = "abc123",
) -> CompactionChain:
    """Build a CompactionChain from a list of member dicts."""
    return CompactionChain(members=members, topic=topic, chain_id=chain_id)


def _make_epoch_record(
    archived_ids: list[str] | None = None,
    epoch_id: str = "epoch_abc123",
    text: str = "auth churned 3x in 2026, settled on final auth",
) -> EpochRecord:
    """Build an EpochRecord for testing compactor functions."""
    summary = EpochSummary(
        text=text,
        topic="auth",
        count=len(archived_ids or []),
        resolution="final auth",
        date_range=("2025-06-01T00:00:00Z", "2025-12-01T00:00:00Z"),
        key_decision_id=archived_ids[-1] if archived_ids else "unknown",
    )
    return EpochRecord(
        summary=summary,
        archived_decision_ids=archived_ids or [],
        date_range=("2025-06-01T00:00:00Z", "2025-12-01T00:00:00Z"),
        confidence_range=(0.1, 0.4),
        epoch_id=epoch_id,
    )


# Decisions with supersedes relationships (topical keyword overlap + an
# explicit revert/removal marker word triggers chain detection --
# _find_supersedes, not caused_by: caused_by's own heuristic was removed
# entirely (wishlist testing round, 2026-08-25) after it was found live
# flagging one decision as "caused by" 139 of the project's ~306 others,
# so a fixture relying on it to form a chain no longer applies).
# All timestamps are old (2025) to ensure stale confidence scores.
_CHAIN_DECISIONS = [
    _decision(
        "d1",
        "Switched authentication to JWT tokens for API access",
        ts_days_ago=400,
        rationale="Need stateless authentication for microservices",
    ),
    _decision(
        "d2",
        "Replaced JWT tokens authentication with OAuth2 tokens for API access",
        ts_days_ago=350,
        rationale="JWT tokens had vulnerability issues",
    ),
    _decision(
        "d3",
        "Reverted API authentication back to JWT tokens with key rotation",
        ts_days_ago=300,
        rationale="OAuth2 added too much complexity",
    ),
]


# ---------------------------------------------------------------------------
#  1. identify_compactable_chains tests
# ===========================================================================


class TestIdentifyCompactableChains:
    def test_identify_compactable_chains_empty(self):
        """No decisions → returns empty list, never an error."""
        # Arrange
        decisions: list[dict] = []

        # Act
        result = identify_compactable_chains(decisions)

        # Assert
        assert result == []
        assert isinstance(result, list)

    def test_identify_compactable_chains_single(self):
        """Single chain with 3 caused_by decisions → one chain found."""
        # Arrange — _CHAIN_DECISIONS has 3 decisions linked via caused_by
        # All timestamps are 300-400 days old → stale confidence

        # Act
        chains = identify_compactable_chains(_CHAIN_DECISIONS)

        # Assert
        assert len(chains) >= 1
        chain = chains[0]
        assert len(chain.members) >= 2
        assert chain.topic is not None
        assert isinstance(chain.chain_id, str)
        assert len(chain.chain_id) == 12  # sha256 hex[:12]

    def test_identify_compactable_chains_multiple(self):
        """Two independent chains → both detected."""
        # Arrange — create a second independent chain
        chain_b = [
            _decision("b1", "Used PostgreSQL as the primary database", ts_days_ago=500),
            _decision(
                "b2",
                "Replaced PostgreSQL primary database with MySQL due to licensing",
                ts_days_ago=450,
                rationale="PostgreSQL licensing changed",
            ),
        ]
        all_decisions = _CHAIN_DECISIONS + chain_b

        # Act
        chains = identify_compactable_chains(all_decisions)

        # Assert
        # Should find at least 2 chains (one from auth, one from DB)
        assert len(chains) >= 2
        topics = {c.topic for c in chains}
        # Both chains should have distinct topics
        assert len(topics) >= 2

    def test_identify_compactable_chains_high_confidence_excluded(self):
        """Recent decisions (high confidence) → no chains found."""
        # Arrange — all decisions are very recent
        fresh = [
            _decision("f1", "Use React for frontend", ts_days_ago=1),
            _decision(
                "f2",
                "Switched frontend to Vue because of React",
                ts_days_ago=0,
                rationale="Due to React performance, switched frontend",
            ),
        ]

        # Act
        chains = identify_compactable_chains(fresh)

        # Assert — fresh decisions have high confidence, should be excluded
        assert len(chains) == 0

    def test_identify_compactable_chains_with_revert(self):
        """Two decisions with revert relationship → chain detected."""
        # Arrange — original decision + revert decision (old timestamps for stale)
        revert_decisions = [
            _decision("orig1", "Used dark mode for UI theme", ts_days_ago=400),
            _decision(
                "revert1",
                "Reverted dark mode back to light theme",
                ts_days_ago=350,
                is_revert=True,
                reverts="orig1",
            ),
        ]

        # Act
        chains = identify_compactable_chains(revert_decisions)

        # Assert — revert chain should be detected (pair of 2)
        assert len(chains) >= 1
        member_ids = [m.get("id") for m in chains[0].members]
        assert "orig1" in member_ids
        assert "revert1" in member_ids


# ---------------------------------------------------------------------------
#  2. generate_epoch_summary tests
# ===========================================================================


class TestGenerateEpochSummary:
    def test_generate_epoch_summary(self):
        """Chain with 3 members → summary with topic, count, resolution."""
        # Arrange
        chain = _make_chain(members=_CHAIN_DECISIONS, topic="auth")

        # Act
        result = generate_epoch_summary(chain)

        # Assert
        assert isinstance(result, Ok)
        summary = result.value
        assert isinstance(summary, EpochSummary)
        assert summary.topic == "auth"
        assert summary.count == 3
        assert len(summary.resolution) > 0
        assert summary.resolution == _CHAIN_DECISIONS[-1]["decision"][:80]
        assert len(summary.text) > 0
        assert "auth" in summary.text
        assert "3x" in summary.text

    def test_generate_epoch_summary_empty_members(self):
        """Empty chain members → Err with VALIDATION_ERROR."""
        # Arrange
        chain = _make_chain(members=[])

        # Act
        result = generate_epoch_summary(chain)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"
        assert "empty" in result.error.lower()


# ---------------------------------------------------------------------------
#  3. merge_chain_to_epoch tests
# ===========================================================================


class TestMergeChainToEpoch:
    def test_merge_chain_to_epoch(self):
        """Chain + decisions → EpochRecord with archived IDs."""
        # Arrange
        chain = _make_chain(members=_CHAIN_DECISIONS, topic="auth")

        # Act
        result = merge_chain_to_epoch(chain, _CHAIN_DECISIONS)

        # Assert
        assert isinstance(result, Ok)
        record = result.value
        assert isinstance(record, EpochRecord)
        assert record.archived_decision_ids == ["d1", "d2", "d3"]
        assert record.epoch_id.startswith("epoch_")
        assert len(record.confidence_range) == 2
        assert record.confidence_range[0] <= record.confidence_range[1]
        assert record.summary.topic == "auth"

    def test_merge_chain_to_epoch_empty_members(self):
        """Empty chain → Err VALIDATION_ERROR."""
        # Arrange
        chain = _make_chain(members=[])

        # Act
        result = merge_chain_to_epoch(chain, _CHAIN_DECISIONS)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"

    def test_merge_chain_to_epoch_empty_decisions(self):
        """Chain but empty decisions list → Err VALIDATION_ERROR."""
        # Arrange
        chain = _make_chain(members=_CHAIN_DECISIONS, topic="auth")

        # Act
        result = merge_chain_to_epoch(chain, decisions=[])

        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
#  4. apply_compaction tests
# ===========================================================================


class TestApplyCompaction:
    def test_apply_compaction_pure(self):
        """Returns new dict — input memory is never mutated."""
        # Arrange
        memory = {
            "decisions": [
                {"id": "d1", "decision": "old auth"},
                {"id": "d2", "decision": "new auth"},
            ],
            "archived_decisions": [],
            "epochs": [],
        }
        original = copy.deepcopy(memory)
        epoch = _make_epoch_record(archived_ids=["d1"])

        # Act
        result = apply_compaction(memory, [epoch])

        # Assert — original untouched
        assert memory == original
        assert result is not memory
        assert result is not None

    def test_apply_compaction_archives_decisions(self):
        """Archived decisions have archived=True and epoch_id set."""
        # Arrange
        memory = {
            "decisions": [
                {"id": "d1", "decision": "old auth"},
                {"id": "d2", "decision": "new auth"},
            ],
            "archived_decisions": [],
        }
        epoch = _make_epoch_record(archived_ids=["d1"])

        # Act
        result = apply_compaction(memory, [epoch])

        # Assert
        archived = result["archived_decisions"]
        assert len(archived) == 1
        assert archived[0]["id"] == "d1"
        assert archived[0]["archived"] is True
        assert archived[0]["epoch_id"] == "epoch_abc123"
        # d2 should remain active
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["id"] == "d2"

    def test_apply_compaction_adds_epoch_record(self):
        """Epoch records are appended to memory['epochs']."""
        # Arrange
        memory = {"decisions": [{"id": "d1", "decision": "x"}], "epochs": []}
        epoch = _make_epoch_record(archived_ids=["d1"])

        # Act
        result = apply_compaction(memory, [epoch])

        # Assert
        assert len(result["epochs"]) == 1
        assert result["epochs"][0]["epoch_id"] == "epoch_abc123"
        assert "archived_decision_ids" in result["epochs"][0]

    def test_apply_compaction_preserves_existing_epochs(self):
        """Existing epochs are preserved when adding new ones."""
        # Arrange
        memory = {
            "decisions": [{"id": "d1", "decision": "x"}],
            "epochs": [{"epoch_id": "epoch_old", "summary": "old"}],
        }
        epoch = _make_epoch_record(archived_ids=["d1"])

        # Act
        result = apply_compaction(memory, [epoch])

        # Assert
        assert len(result["epochs"]) == 2
        assert result["epochs"][0]["epoch_id"] == "epoch_old"
        assert result["epochs"][1]["epoch_id"] == "epoch_abc123"


# ---------------------------------------------------------------------------
#  5. archive_originals tests
# ===========================================================================


class TestArchiveOriginals:
    def test_archive_originals_marks_archived(self):
        """Matching decisions get archived=True and epoch_id."""
        # Arrange
        decisions = [
            {"id": "d1", "decision": "old"},
            {"id": "d2", "decision": "new"},
        ]

        # Act
        result = archive_originals(decisions, ["d1"], "epoch_test")

        # Assert
        assert result[0]["archived"] is True
        assert result[0]["epoch_id"] == "epoch_test"
        assert "archived" not in result[1]  # d2 not archived

    def test_archive_originals_never_deletes(self):
        """Original decisions are never removed from the list."""
        # Arrange
        decisions = [
            {"id": "d1", "decision": "a"},
            {"id": "d2", "decision": "b"},
            {"id": "d3", "decision": "c"},
        ]

        # Act
        result = archive_originals(decisions, ["d1", "d3"], "epoch_x")

        # Assert — all 3 decisions still present
        assert len(result) == 3
        ids = [d["id"] for d in result]
        assert "d1" in ids
        assert "d2" in ids
        assert "d3" in ids

    def test_archive_originals_no_match(self):
        """No matching IDs → no changes to decisions."""
        # Arrange
        decisions = [{"id": "d1", "decision": "x"}]

        # Act
        result = archive_originals(decisions, ["d99"], "epoch_z")

        # Assert
        assert result == decisions
        assert "archived" not in result[0]


# ---------------------------------------------------------------------------
#  6. build_compaction_report tests
# ===========================================================================


class TestBuildCompactionReport:
    def test_build_compaction_report(self):
        """Report contains before_count, after_count, epoch_count."""
        # Arrange
        before, after, epochs = 10, 7, 2

        # Act
        report = build_compaction_report(before, after, epochs)

        # Assert
        assert report["decisions_before"] == 10
        assert report["decisions_after"] == 7
        assert report["decisions_archived"] == 3
        assert report["epochs_created"] == 2


# ---------------------------------------------------------------------------
#  7. estimate_token_savings tests
# ===========================================================================


class TestEstimateTokenSavings:
    def test_estimate_token_savings(self):
        """Calculates savings from archived decisions vs epoch summaries."""
        # Arrange
        decisions = [
            {"id": "d1", "decision": "A" * 200, "timestamp": "2025-01-01T00:00:00Z"},
            {"id": "d2", "decision": "B" * 200, "timestamp": "2025-02-01T00:00:00Z"},
            {"id": "d3", "decision": "C" * 200, "timestamp": "2025-03-01T00:00:00Z"},
        ]
        epoch = _make_epoch_record(archived_ids=["d1", "d2", "d3"])

        # Act
        savings = estimate_token_savings(decisions, [epoch])

        # Assert
        assert isinstance(savings, int)
        assert savings > 0  # should save tokens

    def test_estimate_token_savings_no_archived(self):
        """No archived IDs match → returns 0."""
        # Arrange
        decisions = [{"id": "d1", "decision": "x" * 100}]
        epoch = _make_epoch_record(archived_ids=["d99"])

        # Act
        savings = estimate_token_savings(decisions, [epoch])

        # Assert
        assert savings >= 0

    def test_estimate_token_savings_empty(self):
        """Empty inputs → 0."""
        # Arrange / Act
        savings = estimate_token_savings([], [])

        # Assert
        assert savings == 0


# ---------------------------------------------------------------------------
#  8. compact_memory tests
# ===========================================================================


class TestCompactMemory:
    @patch("core.compaction.compactor.MemoryManager")
    def test_compact_memory_success(self, MockMM):
        """Full orchestration — chains found, epochs created, memory saved."""
        # Arrange
        mock_mm = MagicMock()
        MockMM.return_value = mock_mm
        mock_mm.save_project_memory = MagicMock()

        memory = {"decisions": list(_CHAIN_DECISIONS)}

        # Act
        result = compact_memory("test-project", memory)

        # Assert
        assert isinstance(result, Ok)
        cr = result.value
        assert isinstance(cr, CompactionResult)
        assert cr.epochs_created >= 1
        assert cr.decisions_archived >= 2
        assert cr.token_savings_estimate >= 0
        assert len(cr.epoch_summaries) >= 1
        mock_mm.save_project_memory.assert_called_once()

    @patch("core.compaction.compactor.MemoryManager")
    def test_compact_memory_empty_decisions(self, MockMM):
        """No decisions → graceful Ok with zeroed stats."""
        # Arrange
        memory = {"decisions": []}

        # Act
        result = compact_memory("test-project", memory)

        # Assert
        assert isinstance(result, Ok)
        cr = result.value
        assert cr.epochs_created == 0
        assert cr.decisions_archived == 0
        assert cr.token_savings_estimate == 0
        assert cr.epoch_summaries == []

    @patch("core.compaction.compactor.MemoryManager")
    def test_compact_memory_no_stale_chains(self, MockMM):
        """Fresh decisions (high confidence) → Ok with zeroed stats."""
        # Arrange — all recent decisions
        fresh = [
            _decision("f1", "Use React for frontend UI", ts_days_ago=1),
            _decision(
                "f2",
                "Switched frontend to Vue because of React performance",
                ts_days_ago=0,
                rationale="Due to React performance, switched frontend",
            ),
        ]
        memory = {"decisions": fresh}

        # Act
        result = compact_memory("test-project", memory)

        # Assert
        assert isinstance(result, Ok)
        assert result.value.epochs_created == 0

    @patch("core.compaction.compactor.MemoryManager")
    def test_compact_memory_save_failure(self, MockMM):
        """MemoryManager.save raises → Err with IO_ERROR code."""
        # Arrange
        mock_mm = MagicMock()
        MockMM.return_value = mock_mm
        mock_mm.save_project_memory.side_effect = PermissionError("denied")

        memory = {"decisions": list(_CHAIN_DECISIONS)}

        # Act
        result = compact_memory("test-project", memory)

        # Assert
        assert isinstance(result, Err)
        assert result.code == "IO_ERROR"
        assert "Failed to save" in result.error

    @patch("core.compaction.compactor.MemoryManager")
    def test_compact_memory_preserves_originals(self, MockMM):
        """Compacted memory has archived_decisions field — originals never deleted."""
        # Arrange
        mock_mm = MagicMock()
        MockMM.return_value = mock_mm
        mock_mm.save_project_memory = MagicMock()

        memory = {"decisions": list(_CHAIN_DECISIONS)}

        # Act
        result = compact_memory("test-project", memory)

        # Assert — save_project_memory was called with a memory that has archived_decisions
        assert mock_mm.save_project_memory.called
        saved_memory = mock_mm.save_project_memory.call_args[0][1]
        assert "archived_decisions" in saved_memory
        assert len(saved_memory["archived_decisions"]) >= 1
        # Original decisions are moved, not removed
        for archived in saved_memory["archived_decisions"]:
            assert archived.get("archived") is True
            assert "epoch_id" in archived


# ---------------------------------------------------------------------------
#  9. Router pure helpers tests
# ===========================================================================


class TestRouterHelpers:
    def test_validate_project_valid(self):
        """Valid project names pass without error."""
        # Arrange / Act / Assert (no exception)
        _validate_project("my-project")
        _validate_project("project_123")
        _validate_project("simple")

    def test_validate_project_invalid(self):
        """Invalid project names raise ValidationError."""
        # Arrange / Act / Assert
        with pytest.raises(ValidationError):
            _validate_project("has spaces")
        with pytest.raises(ValidationError):
            _validate_project("path/traversal")
        with pytest.raises(ValidationError):
            _validate_project("special!@#chars")

    def test_compaction_status_pure(self):
        """_compaction_status returns correct stats from memory dict."""
        # Arrange
        memory = {
            "decisions": [{"id": "d1"}, {"id": "d2"}],
            "archived_decisions": [{"id": "d0", "archived": True}],
            "epochs": [
                {
                    "epoch_id": "e1",
                    "date_range": ["2025-01-01T00:00:00Z", "2025-06-01T00:00:00Z"],
                }
            ],
        }

        # Act
        status = _compaction_status(memory)

        # Assert
        assert status["total_decisions"] == 2
        assert status["archived_count"] == 1
        assert status["epoch_count"] == 1
        assert status["last_compaction"] == "2025-06-01T00:00:00Z"

    def test_compaction_status_empty_memory(self):
        """Empty memory → zeroed stats, no last_compaction."""
        # Arrange
        memory: dict = {}

        # Act
        status = _compaction_status(memory)

        # Assert
        assert status["total_decisions"] == 0
        assert status["archived_count"] == 0
        assert status["epoch_count"] == 0
        assert status["last_compaction"] is None

    def test_result_to_http_maps_codes(self):
        """Err codes map to correct HTTP status codes."""
        # Arrange / Act / Assert
        assert _result_to_http(Err("not found", code="NOT_FOUND")).status_code == 404
        assert _result_to_http(Err("bad input", code="VALIDATION_ERROR")).status_code == 422
        assert _result_to_http(Err("disk full", code="IO_ERROR")).status_code == 500
        assert _result_to_http(Err("mystery", code="OTHER")).status_code == 500

    def test_validate_project_rejects_empty(self):
        """Empty string raises ValidationError."""
        # Arrange / Act / Assert
        with pytest.raises(ValidationError):
            _validate_project("")


# ---------------------------------------------------------------------------
#  10. Router endpoint tests
# ===========================================================================


class TestRouterCompactEndpoint:
    @patch("core.compaction.router._load_memory")
    @patch("core.compaction.router.compact_memory")
    def test_router_compact_success(self, mock_compact, mock_load):
        """POST /compact with valid project → 200 with report."""
        # Arrange
        mock_load.return_value = {"decisions": list(_CHAIN_DECISIONS)}
        mock_compact.return_value = Ok(CompactionResult(
            epochs_created=1,
            decisions_archived=3,
            token_savings_estimate=50,
            epoch_summaries=[_make_epoch_record(archived_ids=["d1", "d2", "d3"])],
        ))
        app = MagicMock()
        app.include_router = MagicMock()
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(compaction_router)
        client = TestClient(test_app)

        # Act
        response = client.post("/api/memory/my-project/compact")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["epochs_created"] == 1
        assert data["decisions_archived"] == 3
        assert data["token_savings_estimate"] == 50
        assert len(data["epoch_summaries"]) == 1

    @patch("core.compaction.router._load_memory")
    @patch("core.compaction.router.compact_memory")
    def test_router_compact_empty(self, mock_compact, mock_load):
        """POST /compact with nothing to compact → 200 with empty report."""
        # Arrange
        mock_load.return_value = {"decisions": []}
        mock_compact.return_value = Ok(CompactionResult(
            epochs_created=0,
            decisions_archived=0,
            token_savings_estimate=0,
            epoch_summaries=[],
        ))
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(compaction_router)
        client = TestClient(test_app)

        # Act
        response = client.post("/api/memory/my-project/compact")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["epochs_created"] == 0

    def test_router_compact_404(self):
        """POST /compact with missing project → 404."""
        # Arrange
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(compaction_router)
        client = TestClient(test_app)

        # Patch _load_memory to raise MemoryNotFoundError
        with patch(
            "core.compaction.router._load_memory",
            side_effect=MemoryNotFoundError("ghost-project"),
        ):
            # Act
            response = client.post("/api/memory/ghost-project/compact")

        # Assert
        assert response.status_code == 404

    def test_router_compact_422_invalid_project(self):
        """POST /compact with invalid project name → 422."""
        # Arrange
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(compaction_router)
        client = TestClient(test_app)

        # Act
        response = client.post("/api/memory/bad project!/compact")

        # Assert
        assert response.status_code == 422


class TestRouterStatusEndpoint:
    @patch("core.compaction.router._load_memory")
    def test_router_status_success(self, mock_load):
        """GET /compaction/status → 200 with stats."""
        # Arrange
        mock_load.return_value = {
            "decisions": [{"id": "d1"}, {"id": "d2"}],
            "archived_decisions": [],
            "epochs": [],
        }
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(compaction_router)
        client = TestClient(test_app)

        # Act
        response = client.get("/api/memory/my-project/compaction/status")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["total_decisions"] == 2
        assert data["archived_count"] == 0
        assert data["epoch_count"] == 0

    def test_router_status_404(self):
        """GET /compaction/status with missing project → 404."""
        # Arrange
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(compaction_router)
        client = TestClient(test_app)

        with patch(
            "core.compaction.router._load_memory",
            side_effect=MemoryNotFoundError("nope"),
        ):
            # Act
            response = client.get("/api/memory/nope/compaction/status")

        # Assert
        assert response.status_code == 404

    def test_router_status_422_invalid_project(self):
        """GET /compaction/status with invalid project → 422."""
        # Arrange
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(compaction_router)
        client = TestClient(test_app)

        # Act
        response = client.get("/api/memory/bad name/compaction/status")

        # Assert
        assert response.status_code == 422
