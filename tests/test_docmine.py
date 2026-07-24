"""
Tests for Doc Mining — pure functions.
Covers: extract_claims, mine_markdown_files.
"""

from core.docmine.detector import mine_markdown_files
from core.docmine.extractor import extract_claims


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
