"""
Tests for Contradiction Detector — pure functions.
Covers: compute_similarity, detect_direct_contradiction, classify_contradiction,
        suggest_resolution, detect_contradictions.
"""

import pytest
from core.contradictions.detector import (
    _cosine_similarity,
    classify_contradiction,
    compute_similarity,
    detect_contradictions,
    detect_direct_contradiction,
    hybrid_similarity,
    suggest_resolution,
)
from core.contradictions import Contradiction, ContradictionReport


# ── compute_similarity ─────────────────────────────────────────────────────

class TestComputeSimilarity:
    def test_identical_texts(self):
        assert compute_similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert compute_similarity("cat dog", "fish bird") == 0.0

    def test_partial_overlap(self):
        score = compute_similarity("use FastAPI for backend", "use FastAPI for API")
        assert 0.0 < score < 1.0

    def test_empty_strings(self):
        assert compute_similarity("", "hello") == 0.0
        assert compute_similarity("", "") == 0.0


# ── hybrid_similarity / _cosine_similarity (#57) ────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestHybridSimilarity:
    def test_no_embeddings_falls_back_to_keyword_similarity_exactly(self):
        """Bit-for-bit identical to compute_similarity when either
        embedding is missing — the common case pre-#57 and for any
        project without OPENAI_API_KEY configured."""
        text_a, text_b = "use FastAPI for backend", "use FastAPI for API"
        assert hybrid_similarity(text_a, text_b) == compute_similarity(text_a, text_b)
        assert hybrid_similarity(text_a, text_b, embedding_a=[1.0, 0.0]) == compute_similarity(text_a, text_b)
        assert hybrid_similarity(text_a, text_b, embedding_b=[1.0, 0.0]) == compute_similarity(text_a, text_b)

    def test_semantically_similar_low_keyword_overlap_scores_higher_than_keyword_alone(self):
        """The exact failure mode #57 exists to fix: two decisions that
        conflict but share almost no vocabulary score near-zero on
        keywords alone. With embeddings that are actually close (as real
        embeddings for paraphrased text would be), the hybrid score must
        end up higher than the keyword-only score."""
        text_a = "Use JWT for authentication"
        text_b = "Store sessions server-side with a session store"
        keyword_only = compute_similarity(text_a, text_b)
        # Simulate embeddings that are highly similar (as real ones would
        # be for semantically related text) — same vector direction.
        hybrid = hybrid_similarity(text_a, text_b, embedding_a=[1.0, 0.5], embedding_b=[0.9, 0.45])
        assert hybrid > keyword_only

    def test_result_is_bounded_0_to_1_for_similar_vectors(self):
        score = hybrid_similarity("a", "b", embedding_a=[1.0, 0.0], embedding_b=[1.0, 0.0])
        assert 0.0 <= score <= 1.0

    def test_negative_cosine_is_clamped_not_subtracted(self):
        """Opposed embeddings shouldn't be able to drag a hybrid score
        negative — semantic_score is clamped to >= 0 before blending."""
        score = hybrid_similarity("x", "y", embedding_a=[1.0, 0.0], embedding_b=[-1.0, 0.0])
        assert score >= 0.0


class TestDetectContradictionsWithEmbeddings:
    def test_embeddings_none_matches_pre_57_behavior(self):
        decisions = [
            {"id": "a", "decision": "Use MySQL for the primary database"},
            {"id": "b", "decision": "Use Postgres for the primary database"},
        ]
        without = detect_contradictions(decisions)
        with_none = detect_contradictions(decisions, embeddings=None)
        assert len(without.contradictions) == len(with_none.contradictions) == 1

    def test_missing_vector_for_one_decision_falls_back_to_keyword_for_that_pair(self):
        decisions = [
            {"id": "a", "decision": "Use MySQL for the primary database"},
            {"id": "b", "decision": "Use Postgres for the primary database"},
        ]
        # Only "a" has a cached vector — "b" doesn't (e.g. embedding call
        # failed partway through). That pair must still be evaluated, just
        # on keyword similarity alone, not skipped or crash.
        report = detect_contradictions(decisions, embeddings={"a": [1.0, 0.0]})
        assert len(report.contradictions) == 1


# ── detect_direct_contradiction ────────────────────────────────────────────

class TestDetectDirectContradiction:
    def test_opposing_verbs(self):
        assert detect_direct_contradiction(
            "Use FastAPI for API layer",
            "Don't use FastAPI for API layer",
        ) is True

    def test_technology_opposition(self):
        assert detect_direct_contradiction(
            "Use React for frontend",
            "Use Vue for frontend",
        ) is True

    def test_no_contradiction(self):
        assert detect_direct_contradiction(
            "Use FastAPI for backend",
            "Use FastAPI for API layer",
        ) is False

    def test_reverse_opposing(self):
        assert detect_direct_contradiction(
            "Don't use React",
            "We should use React",
        ) is True


# ── Concealment / circumvention pairs ───────────────────────────────────────
# Added after a live gap check: the original opposing-pairs list only
# covered generic add/remove-style phrasing, missing the "quietly work
# around or hide a safety-relevant change" vocabulary this system exists to
# catch (Ghost Decisions, #52's audit trail, #53's override gate).

class TestConcealmentAndCircumventionPairs:
    def test_hide_vs_expose(self):
        assert detect_direct_contradiction(
            "Hide the debug panel from end users",
            "Expose the debug panel to end users",
        ) is True

    def test_obfuscate_vs_clarify(self):
        assert detect_direct_contradiction(
            "Obfuscate the error messages shown to the client",
            "Clarify the error messages shown to the client",
        ) is True

    def test_override_vs_respect(self):
        assert detect_direct_contradiction(
            "Override the reviewer's rejection on deploy",
            "Respect the reviewer's rejection on deploy",
        ) is True

    def test_bypass_vs_enforce(self):
        assert detect_direct_contradiction(
            "Bypass rate limiting for internal service calls",
            "Enforce rate limiting for internal service calls",
        ) is True

    def test_skip_vs_enforce(self):
        assert detect_direct_contradiction(
            "Skip input validation on the legacy import endpoint",
            "Enforce input validation on the legacy import endpoint",
        ) is True

    def test_authorize_vs_revoke(self):
        assert detect_direct_contradiction(
            "Authorize service accounts to read the audit log",
            "Revoke service accounts from reading the audit log",
        ) is True

    def test_inject_vs_validate(self):
        assert detect_direct_contradiction(
            "Inject unsanitized query params directly into SQL",
            "Validate query params before they reach SQL",
        ) is True

    def test_delete_vs_preserve(self):
        assert detect_direct_contradiction(
            "Delete session logs older than 7 days",
            "Preserve session logs older than 7 days",
        ) is True

    def test_unrelated_text_with_verb_but_no_shared_topic_is_not_flagged(self):
        """A pair verb matching on both sides isn't enough on its own —
        _share_subject still has to find a real shared topic, same
        safeguard that already applies to the original pairs."""
        assert detect_direct_contradiction(
            "Hide the sidebar toggle button on mobile",
            "Expose new pricing tiers to enterprise customers",
        ) is False


# ── _share_subject / _OPPOSING_PAIR_TOKENS derivation ───────────────────────

class TestOpposingPairTokensStayInSync:
    def test_every_opposing_pair_term_is_excluded_from_subject_matching(self):
        """The exclusion set used to be hand-maintained and silently fell
        out of sync with _OPPOSING_PAIRS (missing over half its terms).
        Deriving it from _OPPOSING_PAIRS means a pair verb can never
        itself count as the "shared subject" — verified here for a
        newly-added pair term ("override") that the old hand-written list
        never would have covered."""
        from core.contradictions.detector import _OPPOSING_PAIR_TOKENS
        assert "override" in _OPPOSING_PAIR_TOKENS
        assert "hide" in _OPPOSING_PAIR_TOKENS
        assert "bypass" in _OPPOSING_PAIR_TOKENS
        # A long-standing pair term the old hand-written set had already
        # forgotten (regression guard for the original bug, not just the
        # new pairs).
        assert "include" in _OPPOSING_PAIR_TOKENS
        assert "keep" in _OPPOSING_PAIR_TOKENS


class TestMoreConcealmentAndCircumventionPairs:
    """Second pass, prompted directly: more safety/security-relevant
    opposing vocabulary beyond the first batch."""

    def test_suppress_vs_surface(self):
        assert detect_direct_contradiction(
            "Suppress the deprecation warning in CI output",
            "Surface the deprecation warning in CI output",
        ) is True

    def test_mask_vs_reveal(self):
        assert detect_direct_contradiction(
            "Mask customer email addresses in support tickets",
            "Reveal customer email addresses in support tickets",
        ) is True

    def test_elevate_vs_restrict(self):
        assert detect_direct_contradiction(
            "Elevate the deploy bot's permissions to admin",
            "Restrict the deploy bot's permissions to admin",
        ) is True

    def test_relax_vs_tighten(self):
        assert detect_direct_contradiction(
            "Relax the password complexity policy for internal tools",
            "Tighten the password complexity policy for internal tools",
        ) is True

    def test_circumvent_vs_enforce(self):
        assert detect_direct_contradiction(
            "Circumvent the approval workflow for hotfixes",
            "Enforce the approval workflow for hotfixes",
        ) is True

    def test_grant_vs_deny(self):
        assert detect_direct_contradiction(
            "Grant contractors access to the production database",
            "Deny contractors access to the production database",
        ) is True

    def test_tamper_vs_preserve(self):
        assert detect_direct_contradiction(
            "Tamper with the audit log timestamps during migration",
            "Preserve the audit log timestamps during migration",
        ) is True

    def test_purge_vs_retain(self):
        assert detect_direct_contradiction(
            "Purge user activity logs after 30 days",
            "Retain user activity logs after 30 days",
        ) is True

    def test_inject_vs_sanitize(self):
        assert detect_direct_contradiction(
            "Inject raw user input into the shell command",
            "Sanitize raw user input into the shell command",
        ) is True


class TestThirdConcealmentPass:
    """Third pass. purge/retain was already covered by round 2 (not
    re-added); overload and stall were considered and left out — both
    describe a state something ends up in ("the server overloaded"), not
    an intentional decision verb the way "throttle"/"bypass"/"dismiss"
    are, so they don't fit the opposing-decision-pair shape."""

    def test_dismiss_vs_flag(self):
        assert detect_direct_contradiction(
            "Dismiss low-confidence ghost warnings automatically",
            "Flag low-confidence ghost warnings automatically",
        ) is True

    def test_destruct_vs_preserve(self):
        assert detect_direct_contradiction(
            "Destruct the temporary credentials after the session ends",
            "Preserve the temporary credentials after the session ends",
        ) is True

    def test_drain_vs_refill(self):
        assert detect_direct_contradiction(
            "Drain the connection pool before a rolling restart",
            "Refill the connection pool before a rolling restart",
        ) is True

    def test_decommission_vs_keep(self):
        assert detect_direct_contradiction(
            "Decommission the legacy auth service this quarter",
            "Keep the legacy auth service this quarter",
        ) is True

    def test_sidestep_vs_address(self):
        assert detect_direct_contradiction(
            "Sidestep the security review for the emergency patch",
            "Address the security review for the emergency patch",
        ) is True


class TestFourthConcealmentPass:
    """Fourth pass. conceal/disclose (round 2), block (round-1 original
    allow/block), reject (round-1 original adopt/reject), and deny (round
    2 grant/deny) were all already covered — not re-added. convert,
    construct, leave, format, swap, trade, and sweep were left out as too
    generic/high-false-positive-risk or not fitting the two-sided
    opposing-decision shape (swap/trade imply substitution, closer to
    _TECH_OPPOSITIONS' style than a generic verb pair). collide describes
    an outcome, not a decision, same reasoning as overload/stall in round
    3. constrain, defy, wipe, "let pass", "turn/switch off", and "make up"
    were left out as redundant with tighten, evade, purge, sidestep,
    disable, and spoof respectively.
    """

    def test_establish_vs_dismantle(self):
        assert detect_direct_contradiction(
            "Establish a formal incident review process",
            "Dismantle the formal incident review process",
        ) is True

    def test_connect_vs_isolate(self):
        assert detect_direct_contradiction(
            "Connect the staging database to the public internet",
            "Isolate the staging database to the public internet",
        ) is True

    def test_silence_vs_alert(self):
        assert detect_direct_contradiction(
            "Silence failed-login notifications during the migration",
            "Alert failed-login notifications during the migration",
        ) is True

    def test_brick_vs_restore(self):
        assert detect_direct_contradiction(
            "Brick the device on repeated failed unlock attempts",
            "Restore the device on repeated failed unlock attempts",
        ) is True

    def test_distort_vs_clarify(self):
        assert detect_direct_contradiction(
            "Distort the latency numbers shown on the public status page",
            "Clarify the latency numbers shown on the public status page",
        ) is True

    def test_guess_vs_verify(self):
        assert detect_direct_contradiction(
            "Guess the user's timezone from their IP address",
            "Verify the user's timezone from their IP address",
        ) is True

    def test_overwrite_vs_preserve(self):
        assert detect_direct_contradiction(
            "Overwrite historical decision records during the migration",
            "Preserve historical decision records during the migration",
        ) is True

    def test_forge_vs_verify(self):
        assert detect_direct_contradiction(
            "Forge the signing key used for release artifacts",
            "Verify the signing key used for release artifacts",
        ) is True

    def test_pause_vs_resume(self):
        assert detect_direct_contradiction(
            "Pause the background sync job during peak hours",
            "Resume the background sync job during peak hours",
        ) is True

    def test_freeze_vs_unfreeze(self):
        assert detect_direct_contradiction(
            "Freeze the pricing tier configuration for the quarter",
            "Unfreeze the pricing tier configuration for the quarter",
        ) is True


# ── _detect_temporal — shared _contains_phrase + _share_subject fix ────────

class TestDetectTemporal:
    def test_word_boundary_not_substring_for_reversal_keywords(self):
        """Found live: raw `'undo' in text` matched inside 'undocumented',
        misclassifying two unrelated "Added feature: ..." decisions as a
        temporal contradiction purely because one happened to mention
        undocumented decisions."""
        from core.contradictions.detector import _detect_temporal

        a = {
            "id": "a", "timestamp": "2026-01-01T00:00:00Z",
            "decision": "Added feature: mine markdown files for drift and undocumented decisions",
        }
        b = {
            "id": "b", "timestamp": "2026-01-02T00:00:00Z",
            "decision": "Added feature: add MCP server and terminal UI",
        }
        assert _detect_temporal(a, b) is False

    def test_genuine_reversal_with_shared_topic_still_detected(self):
        from core.contradictions.detector import _detect_temporal

        a = {
            "id": "a", "timestamp": "2026-01-01T00:00:00Z",
            "decision": "Use MySQL for the primary database",
        }
        b = {
            "id": "b", "timestamp": "2026-01-02T00:00:00Z",
            "decision": "Changed the primary database from MySQL to Postgres",
        }
        assert _detect_temporal(a, b) is True

    def test_missing_timestamp_returns_false(self):
        from core.contradictions.detector import _detect_temporal

        a = {"id": "a", "decision": "Changed the database"}
        b = {"id": "b", "timestamp": "2026-01-02T00:00:00Z", "decision": "Use Postgres for the database"}
        assert _detect_temporal(a, b) is False


# ── classify_contradiction ────────────────────────────────────────────────

class TestClassifyContradiction:
    def test_direct_contradiction_high_severity(self):
        da = {"id": "d1", "decision": "Use FastAPI for API layer"}
        db = {"id": "d2", "decision": "Don't use FastAPI for API layer"}
        result = classify_contradiction(da, db, 0.5)
        assert result is not None
        assert result.contradiction_type == "direct"
        assert result.severity == "high"

    def test_low_similarity_returns_none(self):
        da = {"id": "d1", "decision": "Use FastAPI"}
        db = {"id": "d2", "decision": "Buy new laptop"}
        result = classify_contradiction(da, db, 0.05)
        assert result is None

    def test_temporal_contradiction(self):
        da = {"id": "d1", "decision": "Use Express for backend API", "timestamp": "2026-01-01"}
        db = {"id": "d2", "decision": "Switched from Express to Koa for backend API", "timestamp": "2026-06-01"}
        result = classify_contradiction(da, db, 0.5)
        # Temporal check runs alongside direct; express/koa is in _TECH_OPPOSITIONS
        # so it may be classified as direct. The important thing is a contradiction IS found.
        assert result is not None

    def test_implicit_contradiction(self):
        da = {"id": "d1", "decision": "Prefer writing detailed documentation for APIs"}
        db = {"id": "d2", "decision": "Keep documentation minimal and concise for APIs"}
        result = classify_contradiction(da, db, 0.5)
        assert result is not None
        assert result.contradiction_type in ("implicit", "direct")


# ── suggest_resolution ────────────────────────────────────────────────────

class TestSuggestResolution:
    def test_direct_suggestion(self):
        c = Contradiction(
            id="c1", decision_a_id="d1", decision_a_text="Use X",
            decision_b_id="d2", decision_b_text="Don't use X",
            contradiction_type="direct", severity="high",
            similarity_score=0.5, resolution_suggestion="",
        )
        result = suggest_resolution(c)
        assert "conflict" in result.lower() or "supersede" in result.lower()

    def test_temporal_suggestion(self):
        c = Contradiction(
            id="c1", decision_a_id="d1", decision_a_text="A",
            decision_b_id="d2", decision_b_text="B",
            contradiction_type="temporal", severity="medium",
            similarity_score=0.5, resolution_suggestion="",
        )
        result = suggest_resolution(c)
        assert "superseded" in result.lower() or "newer" in result.lower()


# ── detect_contradictions ─────────────────────────────────────────────────

class TestDetectContradictions:
    def test_empty_decisions(self):
        result = detect_contradictions([])
        assert isinstance(result, ContradictionReport)
        assert result.total_checked == 0

    def test_no_contradictions(self):
        decisions = [
            {"id": "d1", "decision": "Use Python"},
            {"id": "d2", "decision": "Buy office supplies"},
        ]
        result = detect_contradictions(decisions)
        assert len(result.contradictions) == 0

    def test_finds_direct_contradiction(self):
        decisions = [
            {"id": "d1", "decision": "Use React for frontend"},
            {"id": "d2", "decision": "Use Vue for frontend"},
        ]
        result = detect_contradictions(decisions)
        assert len(result.contradictions) >= 1
        assert result.total_checked == 1  # C(2,2) = 1 pair

    def test_multiple_pairs_checked(self):
        decisions = [
            {"id": "d1", "decision": "A"},
            {"id": "d2", "decision": "B"},
            {"id": "d3", "decision": "C"},
        ]
        result = detect_contradictions(decisions)
        assert result.total_checked == 3  # C(3,2) = 3 pairs

    def test_sorted_by_severity(self):
        decisions = [
            {"id": "d1", "decision": "Use React for frontend"},
            {"id": "d2", "decision": "Use Vue for frontend"},
            {"id": "d3", "decision": "Adopt JavaScript for new projects"},
            {"id": "d4", "decision": "Prefer TypeScript for new projects"},
        ]
        result = detect_contradictions(decisions)
        if len(result.contradictions) > 1:
            severities = [c.severity for c in result.contradictions]
            rank = {"high": 0, "medium": 1, "low": 2}
            assert severities == sorted(severities, key=lambda s: rank.get(s, 3))


# ── /contradictions endpoint: escalation to Safety Review queue ────────────

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_real_embedding_calls():
    """#57 made GET /contradictions call core.llm.embed. Every test below
    uses the real app/MemoryManager (no isolated router fixture to hang
    this off), so without this autouse patch each one would silently make
    a real OpenAI network call — slow, flaky without network, and not
    free. return_value=None exercises the exact fallback path these tests
    already expect: pure keyword-based contradiction detection.
    """
    with patch("core.embeddings.embed", return_value=None):
        yield


@pytest.fixture
def project():
    return f"test_contradictions_{uuid.uuid4().hex[:8]}"


class TestContradictionEscalation:
    def _create_conflicting_pair(self, client, project):
        a = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Use React for frontend", "context": "",
            "safety_metadata": {"safety_category": "general"},
        }).json()["decision"]
        b = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Use Vue for frontend", "context": "",
            "safety_metadata": {"safety_category": "general"},
        }).json()["decision"]
        return a["id"], b["id"]

    def test_high_severity_contradiction_escalates_to_review(self, client, project):
        a_id, b_id = self._create_conflicting_pair(client, project)

        resp = client.get(f"/api/memory/{project}/contradictions")
        assert resp.status_code == 200

        pending = client.get(f"/api/memory/{project}/reviews/pending").json()
        pending_ids = {r["id"] for r in pending["pending_reviews"]}
        assert a_id in pending_ids
        assert b_id in pending_ids

    def test_escalation_writes_contradiction_escalated_audit_events(self, client, project):
        """#61: escalation previously only mutated requires_review in place
        -- gone the moment a review resolved it, no historical trace. Now
        each escalated decision gets its own append-only audit event."""
        a_id, b_id = self._create_conflicting_pair(client, project)

        resp = client.get(f"/api/memory/{project}/contradictions")
        assert resp.status_code == 200
        assert resp.json()["escalated_to_review"] == 2

        audit = client.get(f"/api/memory/{project}/security/audit-log").json()
        escalated_events = [e for e in audit["events"] if e["event_type"] == "contradiction_escalated"]
        assert len(escalated_events) == 2
        escalated_decision_ids = {e["decision_id"] for e in escalated_events}
        assert escalated_decision_ids == {a_id, b_id}
        assert all(e["severity_counts"] == {"high": 1} for e in escalated_events)

    def test_approved_decision_does_not_re_escalate_on_rescan(self, client, project):
        """Regression test: a contradiction doesn't structurally resolve just
        because one side gets approved -- the pair is still "unresolved" by
        detect_contradictions' own definition. Without a check for an
        existing review, every re-scan (e.g. re-opening the Contradictions
        tab) flips requires_review back to True, so an approved decision
        never actually leaves the pending queue. Same bug class already
        fixed once for the persona/market escalation path; this is the
        contradiction path's own copy of it."""
        a_id, b_id = self._create_conflicting_pair(client, project)

        client.get(f"/api/memory/{project}/contradictions")
        assert client.get(f"/api/memory/{project}/reviews/pending").json()["total_pending"] == 2

        approved = client.post(f"/api/memory/{project}/decisions/{a_id}/approve", params={"reviewer": "shan"})
        assert approved.status_code == 200

        # Re-scanning contradictions (e.g. revisiting the tab) must not
        # undo the approval.
        client.get(f"/api/memory/{project}/contradictions")
        pending = client.get(f"/api/memory/{project}/reviews/pending").json()
        pending_ids = {r["id"] for r in pending["pending_reviews"]}
        assert a_id not in pending_ids
        assert b_id in pending_ids  # the un-approved side is still correctly pending


# ── _get_decision_embeddings (#57's caching layer) ──────────────────────────

import asyncio

from core.contradictions.router import _get_decision_embeddings


class TestGetDecisionEmbeddings:
    def _decisions(self):
        return [
            {"id": "a", "decision": "Use MySQL for the database"},
            {"id": "b", "decision": "Use Postgres for the database"},
        ]

    def test_embed_unavailable_with_empty_cache_returns_none(self, tmp_path):
        with patch("core.contradictions.router._EMBED_STORE_DIR", tmp_path), \
             patch("core.embeddings.embed", return_value=None) as mock_embed:
            result = asyncio.run(_get_decision_embeddings("proj", self._decisions()))
        assert result is None
        mock_embed.assert_called_once()

    def test_embed_success_caches_and_returns_all_vectors(self, tmp_path):
        vectors = [[1.0, 0.0], [0.9, 0.1]]
        with patch("core.contradictions.router._EMBED_STORE_DIR", tmp_path), \
             patch("core.embeddings.embed", return_value=vectors):
            result = asyncio.run(_get_decision_embeddings("proj", self._decisions()))
        assert result == {"a": [1.0, 0.0], "b": [0.9, 0.1]}

    def test_second_call_uses_cache_not_a_second_embed_call(self, tmp_path):
        vectors = [[1.0, 0.0], [0.9, 0.1]]
        with patch("core.contradictions.router._EMBED_STORE_DIR", tmp_path), \
             patch("core.embeddings.embed", return_value=vectors) as mock_embed:
            asyncio.run(_get_decision_embeddings("proj", self._decisions()))
            mock_embed.assert_called_once()

            # Second call, same decisions — everything's cached now, embed
            # must not be called again (this is the whole point of caching
            # through EmbeddingStore rather than re-embedding on every GET).
            mock_embed.reset_mock()
            result = asyncio.run(_get_decision_embeddings("proj", self._decisions()))
            mock_embed.assert_not_called()
        assert result == {"a": [1.0, 0.0], "b": [0.9, 0.1]}

    def test_only_uncached_decisions_are_sent_to_embed(self, tmp_path):
        with patch("core.contradictions.router._EMBED_STORE_DIR", tmp_path), \
             patch("core.embeddings.embed", return_value=[[1.0, 0.0]]):
            asyncio.run(_get_decision_embeddings("proj", [self._decisions()[0]]))

        new_decision = {"id": "c", "decision": "Use React for frontend"}
        with patch("core.contradictions.router._EMBED_STORE_DIR", tmp_path), \
             patch("core.embeddings.embed", return_value=[[0.5, 0.5]]) as mock_embed:
            result = asyncio.run(
                _get_decision_embeddings("proj", [self._decisions()[0], new_decision])
            )
        # Only "c" (uncached) gets sent to embed — "a" is already stored.
        texts_sent = mock_embed.call_args.args[0]
        assert texts_sent == ["Use React for frontend"]
        assert result == {"a": [1.0, 0.0], "c": [0.5, 0.5]}

    def test_decisions_without_ids_are_skipped(self, tmp_path):
        decisions = [{"decision": "no id here"}]
        with patch("core.contradictions.router._EMBED_STORE_DIR", tmp_path), \
             patch("core.embeddings.embed", return_value=None) as mock_embed:
            result = asyncio.run(_get_decision_embeddings("proj", decisions))
        assert result is None
        mock_embed.assert_not_called()
