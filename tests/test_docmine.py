"""
Tests for Doc Mining — pure functions.
Covers: extract_claims, mine_markdown_files, combine_doc_and_ghost_findings.
"""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.docmine import DocFinding, DocMineReport
from core.docmine.combined import combine_doc_and_ghost_findings
from core.docmine.detector import mine_markdown_files
from core.docmine.extractor import extract_claims
from core.result import Ok


# ── extract_claims ──────────────────────────────────────────────────────────

class TestExtractClaims:
    def test_extracts_list_items(self):
        md = "- We use MySQL for the primary database\n- Chosen for wide hosting support\n"
        claims = extract_claims(md, "doc.md")
        texts = [c.text for c in claims]
        assert "We use MySQL for the primary database" in texts
        assert "Chosen for wide hosting support" in texts

    def test_skips_headers(self):
        md = "# Database\n## Setup\nWe use MySQL for the primary database here.\n"
        claims = extract_claims(md, "doc.md")
        assert all(not c.text.startswith("#") for c in claims)
        assert any("MySQL" in c.text for c in claims)

    def test_skips_code_fences(self):
        md = "Some intro text that is long enough to count as a claim.\n```python\nuse_mysql = True\n```\nMore text after the fence here.\n"
        claims = extract_claims(md, "doc.md")
        assert not any("use_mysql" in c.text for c in claims)

    def test_skips_short_fragments(self):
        md = "- ok\n- yes\n- a decision that is long enough to be a real claim\n"
        claims = extract_claims(md, "doc.md")
        assert all(len(c.text) >= 25 for c in claims)

    def test_joins_table_row_cells(self):
        md = "| Feature | Purpose |\n|---|---|\n| Auth | Requires JWT tokens for every API request |\n"
        claims = extract_claims(md, "doc.md")
        assert any("Auth" in c.text and "JWT" in c.text for c in claims)
        # Table separator row must not itself become a claim.
        assert not any(set(c.text) <= set("-| :") for c in claims)

    def test_splits_paragraph_into_sentences(self):
        md = "We use MySQL for storage. It has been reliable so far in production systems.\n"
        claims = extract_claims(md, "doc.md")
        assert len(claims) >= 2

    def test_line_numbers_are_1_indexed_and_accurate(self):
        md = "\n\n- Third line is this real decision statement here\n"
        claims = extract_claims(md, "doc.md")
        assert claims[0].line_number == 3

    def test_claim_ids_are_stable_for_same_input(self):
        md = "- A sufficiently long decision statement for testing\n"
        claims_a = extract_claims(md, "doc.md")
        claims_b = extract_claims(md, "doc.md")
        assert claims_a[0].id == claims_b[0].id

    def test_empty_input_returns_no_claims(self):
        assert extract_claims("", "doc.md") == []


# ── mine_markdown_files ──────────────────────────────────────────────────────

class TestMineMarkdownFiles:
    def test_finds_doc_vs_decision_contradiction(self):
        claims = extract_claims("- We use MySQL for the primary database\n", "doc.md")
        decisions = [{"id": "d1", "decision": "Use Postgres for the primary database"}]
        report = mine_markdown_files(claims, decisions)
        assert report.claims_extracted == 1
        kinds = [f.kind for f in report.findings]
        assert "doc_vs_decision" in kinds

    def test_finds_doc_vs_doc_contradiction_across_files(self):
        claims_a = extract_claims("- We use MySQL for the primary database\n", "a.md")
        claims_b = extract_claims("- We use Postgres for the primary database\n", "b.md")
        report = mine_markdown_files(claims_a + claims_b, [])
        cross_doc = [f for f in report.findings if f.kind == "doc_vs_doc"]
        assert len(cross_doc) >= 1

    def test_does_not_compare_claims_within_same_file(self):
        claims = extract_claims(
            "- We use MySQL for the primary database\n- We use Postgres for the primary database\n",
            "a.md",
        )
        report = mine_markdown_files(claims, [])
        assert all(f.kind != "doc_vs_doc" for f in report.findings)

    def test_flags_decision_like_claim_with_no_matching_decision_as_uncaptured(self):
        claims = extract_claims("- We must always require JWT tokens for every API request\n", "doc.md")
        report = mine_markdown_files(claims, [])
        assert len(report.uncaptured_claims) == 1
        assert "JWT" in report.uncaptured_claims[0].text

    def test_non_decision_like_claim_is_not_uncaptured(self):
        claims = extract_claims("- The sky was a pleasant shade of blue that afternoon\n", "doc.md")
        report = mine_markdown_files(claims, [])
        assert report.uncaptured_claims == []

    def test_matched_claim_is_not_flagged_as_uncaptured(self):
        claims = extract_claims("- We use Postgres for the primary database\n", "doc.md")
        decisions = [{"id": "d1", "decision": "Use Postgres for the primary database"}]
        report = mine_markdown_files(claims, decisions)
        assert report.uncaptured_claims == []

    def test_no_claims_returns_empty_report(self):
        report = mine_markdown_files([], [{"id": "d1", "decision": "Use Postgres"}])
        assert report.claims_extracted == 0
        assert report.findings == []
        assert report.uncaptured_claims == []

    def test_findings_sorted_by_severity(self):
        claims_a = extract_claims("- We use MySQL for the primary database in production\n", "a.md")
        claims_b = extract_claims("- We use Postgres for the primary database in production\n", "b.md")
        report = mine_markdown_files(claims_a + claims_b, [])
        severities = [f.severity for f in report.findings]
        rank = {"high": 0, "medium": 1, "low": 2}
        assert severities == sorted(severities, key=lambda s: rank.get(s, 3))


# ── combine_doc_and_ghost_findings (#55) ────────────────────────────────────

def _doc_finding(decision_id="d1", severity="high", finding_id="f1", kind="doc_vs_decision"):
    return {
        "id": finding_id, "kind": kind,
        "claim_a_text": "doc claim", "claim_a_source": "doc.md:1",
        "claim_b_text": "decision text", "claim_b_source": decision_id,
        "contradiction_type": "direct", "severity": severity,
        "similarity_score": 0.8, "resolution_suggestion": "review",
    }


def _ghost_warning(decision_id="d1", severity="high", decision_text="Use Postgres"):
    return {
        "decision_id": decision_id, "decision_text": decision_text, "severity": severity,
        "severity_score": 0.7, "matched_keywords": [], "recommendation": "review this drift",
        "diff_file": "x.py", "diff_line": 1,
    }


class TestCombineDocAndGhostFindings:
    def test_no_overlap_returns_empty(self):
        result = combine_doc_and_ghost_findings(
            [_doc_finding(decision_id="d1")], [_ghost_warning(decision_id="d2")],
        )
        assert result == []

    def test_overlapping_decision_produces_combined_alert(self):
        result = combine_doc_and_ghost_findings(
            [_doc_finding(decision_id="d1", severity="medium")],
            [_ghost_warning(decision_id="d1", severity="high")],
        )
        assert len(result) == 1
        alert = result[0]
        assert alert.decision_id == "d1"
        assert alert.doc_severity == "medium"
        assert alert.ghost_severity == "high"
        assert alert.combined_severity == "critical"
        assert alert.doc_finding_ids == ["f1"]

    def test_doc_vs_doc_findings_are_ignored(self):
        result = combine_doc_and_ghost_findings(
            [_doc_finding(decision_id="doc.md:3", kind="doc_vs_doc")],
            [_ghost_warning(decision_id="doc.md:3")],
        )
        assert result == []

    def test_multiple_doc_findings_for_one_decision_keeps_worst_severity_and_all_ids(self):
        result = combine_doc_and_ghost_findings(
            [
                _doc_finding(decision_id="d1", severity="low", finding_id="f1"),
                _doc_finding(decision_id="d1", severity="high", finding_id="f2"),
            ],
            [_ghost_warning(decision_id="d1", severity="medium")],
        )
        assert result[0].doc_severity == "high"
        assert set(result[0].doc_finding_ids) == {"f1", "f2"}

    def test_multiple_ghost_warnings_for_one_decision_keeps_worst_severity(self):
        result = combine_doc_and_ghost_findings(
            [_doc_finding(decision_id="d1", severity="high")],
            [
                _ghost_warning(decision_id="d1", severity="low"),
                _ghost_warning(decision_id="d1", severity="high"),
            ],
        )
        assert result[0].ghost_severity == "high"


# ── POST /{project}/drift/combined-check (#55, router integration) ─────────

def _app():
    from core.docmine.router import docmine_router
    app = FastAPI()
    app.include_router(docmine_router)
    return app


class TestCombinedDriftCheckRouter:
    def test_combined_alert_surfaces_when_both_detectors_flag_same_decision(self):
        doc_report = DocMineReport(
            files_scanned=["doc.md"], claims_extracted=1,
            findings=[DocFinding(
                id="f1", kind="doc_vs_decision", claim_a_text="doc claim", claim_a_source="doc.md:1",
                claim_b_text="decision text", claim_b_source="d1", contradiction_type="direct",
                severity="high", similarity_score=0.8, resolution_suggestion="review",
            )],
            uncaptured_claims=[],
        )
        with patch("core.docmine.router._load_memory", return_value={"decisions": []}), \
             patch("core.docmine.router._run_docmine", return_value=doc_report), \
             patch("core.docmine.router.check_diff_for_warnings",
                   return_value=Ok(value=[_ghost_warning(decision_id="d1", severity="high")])):
            resp = TestClient(_app()).post(
                "/api/memory/demo/drift/combined-check",
                json={"diff": "--- a/x.py\n+++ b/x.py\n+x = 1\n"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_combined"] == 1
        assert data["combined_alerts"][0]["decision_id"] == "d1"
        assert data["combined_alerts"][0]["combined_severity"] == "critical"
        assert data["doc_findings_total"] == 1
        assert data["ghost_warnings_total"] == 1

    def test_no_overlap_returns_empty_combined_alerts(self):
        doc_report = DocMineReport(files_scanned=["doc.md"], claims_extracted=0, findings=[], uncaptured_claims=[])
        with patch("core.docmine.router._load_memory", return_value={"decisions": []}), \
             patch("core.docmine.router._run_docmine", return_value=doc_report), \
             patch("core.docmine.router.check_diff_for_warnings", return_value=Ok(value=[])):
            resp = TestClient(_app()).post(
                "/api/memory/demo/drift/combined-check",
                json={"diff": "--- a/x.py\n+++ b/x.py\n+x = 1\n"},
            )

        assert resp.status_code == 200
        assert resp.json()["combined_alerts"] == []

    def test_unknown_project_404s(self):
        from fastapi import HTTPException

        def _mock_load(project):
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

        with patch("core.docmine.router._load_memory", side_effect=_mock_load):
            resp = TestClient(_app()).post(
                "/api/memory/nonexistent/drift/combined-check",
                json={"diff": "+x = 1\n"},
            )
        assert resp.status_code == 404


# ── _escalate_to_review — Safety Review re-entry regression ─────────────────
#
# Doc Mining's own copy of the escalation function had the exact bug already
# fixed once in Contradiction Detection's _escalate_to_review and in
# _apply_persona_market_escalation (core/tropebook/web/server.py): it
# checked requires_review before re-flagging, but never checked whether the
# decision had already been through a real review. Confirmed live against
# the tropelex project: 4 decisions previously approved were still matched
# by current high-severity doc_vs_decision findings, meaning the very next
# approval would have been silently undone by the next scan.

from core.docmine.router import _escalate_to_review


class TestEscalateToReview:
    def _decision(self, did, requires_review=False, safety_reviews=None, risk_level="low"):
        d = {"id": did, "safety_metadata": {"requires_review": requires_review, "risk_level": risk_level}}
        if safety_reviews is not None:
            d["safety_reviews"] = safety_reviews
        return d

    def test_new_decision_gets_escalated(self):
        memory = {"decisions": [self._decision("d1")]}

        count = _escalate_to_review(memory, {"d1"})

        assert count == 1
        assert memory["decisions"][0]["safety_metadata"]["requires_review"] is True
        assert memory["decisions"][0]["safety_metadata"]["risk_level"] == "medium"

    def test_already_flagged_decision_not_double_counted(self):
        memory = {"decisions": [self._decision("d1", requires_review=True)]}

        count = _escalate_to_review(memory, {"d1"})

        assert count == 0

    def test_previously_approved_decision_is_not_re_escalated(self):
        """The regression: a decision with an existing safety_reviews entry
        (already went through the review workflow at least once) must not
        get requires_review flipped back to True just because the same
        doc-vs-decision mismatch is still unresolved on a re-scan."""
        memory = {"decisions": [self._decision(
            "d1", requires_review=False, safety_reviews=[{"reviewer": "shan", "status": "approved"}],
        )]}

        count = _escalate_to_review(memory, {"d1"})

        assert count == 0
        assert memory["decisions"][0]["safety_metadata"]["requires_review"] is False

    def test_decision_not_in_finding_set_is_untouched(self):
        memory = {"decisions": [self._decision("d1")]}

        count = _escalate_to_review(memory, {"some-other-decision"})

        assert count == 0
        assert memory["decisions"][0]["safety_metadata"]["requires_review"] is False


class TestScanMarkdownEscalationRouter:
    def _report_with_high_finding(self, decision_id):
        return DocMineReport(
            files_scanned=["doc.md"], claims_extracted=1,
            findings=[DocFinding(
                id="f1", kind="doc_vs_decision", claim_a_text="doc claim", claim_a_source="doc.md:1",
                claim_b_text="decision text", claim_b_source=decision_id, contradiction_type="direct",
                severity="high", similarity_score=0.8, resolution_suggestion="review",
            )],
            uncaptured_claims=[],
        )

    def test_scan_escalates_unreviewed_decision(self):
        memory = {"decisions": [{"id": "d1", "safety_metadata": {"requires_review": False, "risk_level": "low"}}]}
        with patch("core.docmine.router._load_memory", return_value=memory), \
             patch("core.docmine.router._run_docmine", return_value=self._report_with_high_finding("d1")), \
             patch("core.docmine.router._mm.save_project_memory"):
            resp = TestClient(_app()).post("/api/memory/demo/docmine/scan", json={})

        assert resp.status_code == 200
        assert resp.json()["escalated_to_review"] == 1
        assert memory["decisions"][0]["safety_metadata"]["requires_review"] is True

    def test_scan_does_not_re_escalate_previously_approved_decision(self):
        memory = {"decisions": [{
            "id": "d1",
            "safety_metadata": {"requires_review": False, "risk_level": "low"},
            "safety_reviews": [{"reviewer": "shan", "status": "approved"}],
        }]}
        with patch("core.docmine.router._load_memory", return_value=memory), \
             patch("core.docmine.router._run_docmine", return_value=self._report_with_high_finding("d1")), \
             patch("core.docmine.router._mm.save_project_memory") as mock_save:
            resp = TestClient(_app()).post("/api/memory/demo/docmine/scan", json={})

        assert resp.status_code == 200
        assert resp.json()["escalated_to_review"] == 0
        assert memory["decisions"][0]["safety_metadata"]["requires_review"] is False
        # Nothing changed, so the router must not even write to disk.
        mock_save.assert_not_called()


# ── scan root resolution (project's own repo vs. this Tropelex install) ────

class TestScanRootFor:
    """A project with no synced repo previously got Doc Mining findings
    sourced from Tropelex's own markdown files with no indication that's
    what happened -- _scan_root_for is the fix, and the source label lets
    the frontend disclose it."""

    def test_falls_back_to_base_dir_with_no_repo_path(self):
        from core.docmine.router import _scan_root_for, BASE_DIR

        scan_root, source = _scan_root_for({})
        assert scan_root == BASE_DIR
        assert source == "tropelex_repo_fallback"

    def test_uses_project_repo_path_when_present(self, tmp_path):
        from core.docmine.router import _scan_root_for

        scan_root, source = _scan_root_for({"repo_path": str(tmp_path)})
        assert scan_root == tmp_path
        assert source == "project_repo"

    def test_nonexistent_repo_path_falls_back(self):
        from core.docmine.router import _scan_root_for, BASE_DIR

        scan_root, source = _scan_root_for({"repo_path": "/nonexistent/xyz"})
        assert scan_root == BASE_DIR
        assert source == "tropelex_repo_fallback"

    def test_scan_endpoint_surfaces_scan_root_source(self):
        memory = {"decisions": []}
        report = DocMineReport(files_scanned=[], claims_extracted=0, findings=[], uncaptured_claims=[])
        with patch("core.docmine.router._load_memory", return_value=memory), \
             patch("core.docmine.router._run_docmine", return_value=report):
            resp = TestClient(_app()).post("/api/memory/demo/docmine/scan", json={})

        assert resp.status_code == 200
        assert resp.json()["scan_root_source"] == "tropelex_repo_fallback"
