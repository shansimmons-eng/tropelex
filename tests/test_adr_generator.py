"""
Tests for ADR Generator.
"""

from core.adr_generator import (
    generate_adr,
    generate_adrs_for_project,
    generate_adr_markdown_bundle,
    generate_madr_adr,
    generate_nygard_adr,
    generate_tropelex_adr,
    _slugify,
)


class TestSlugify:
    def test_basic(self):
        assert _slugify("Use FastAPI for backend") == "use-fastapi-for-backend"

    def test_special_chars(self):
        slug = _slugify("Switch from C++ to Rust!")
        assert "cpp" in slug or "c" in slug

    def test_long_text(self):
        slug = _slugify("A" * 100)
        assert len(slug) <= 60


class TestNygardADR:
    def test_basic_generation(self):
        decision = {
            "decision": "Use FastAPI for backend",
            "context": "Need a fast async framework",
            "timestamp": "2026-01-15T00:00:00Z",
            "source": "manual",
        }
        adr = generate_nygard_adr(decision, 1)
        assert "ADR-001" in adr
        assert "Use FastAPI for backend" in adr
        assert "Need a fast async framework" in adr
        assert "Accepted" in adr

    def test_with_rationale(self):
        decision = {
            "decision": "Use PostgreSQL",
            "rationale": "Better JSON support than MySQL",
            "timestamp": "2026-01-15T00:00:00Z",
        }
        adr = generate_nygard_adr(decision, 2)
        assert "Rationale" in adr
        assert "Better JSON support" in adr

    def test_with_categories(self):
        decision = {
            "decision": "Add caching layer",
            "categories": ["performance", "backend"],
            "timestamp": "2026-01-15T00:00:00Z",
        }
        adr = generate_nygard_adr(decision, 3)
        assert "performance" in adr
        assert "backend" in adr


class TestMADRADR:
    def test_basic_generation(self):
        decision = {
            "decision": "Use React for frontend",
            "context": "Team already knows React",
            "timestamp": "2026-01-15T00:00:00Z",
        }
        adr = generate_madr_adr(decision, 1)
        assert "Metadata" in adr
        assert "Considered Options" in adr
        assert "Decision Outcome" in adr


class TestTropelexADR:
    def test_basic_generation(self):
        decision = {
            "decision": "Use Docker for deployment",
            "context": "Consistent environments across dev and prod",
            "timestamp": "2026-01-15T00:00:00Z",
            "source": "git",
            "categories": ["devops"],
            "hash": "abc1234",
        }
        adr = generate_tropelex_adr(decision, 1)
        assert "Docker" in adr
        assert "devops" in adr
        assert "abc1234" in adr
        assert "Decision Lineage" not in adr  # no tree context


class TestGenerateADR:
    def test_format_selection(self):
        decision = {
            "decision": "Use Python",
            "timestamp": "2026-01-15T00:00:00Z",
        }
        adr = generate_adr(decision, 1, format="nygard")
        assert "ADR-001" in adr

        adr = generate_adr(decision, 1, format="madr")
        assert "Metadata" in adr


class TestGenerateADRsForProject:
    def test_generates_for_project(self):
        memory = {
            "project_name": "test-project",
            "decisions": [
                {
                    "decision": "Use FastAPI for the backend API server",
                    "context": "Need async support",
                    "timestamp": "2026-01-15T00:00:00Z",
                    "hash": "abc1234",
                },
                {
                    "decision": "Short",  # too short, should be filtered
                    "timestamp": "2026-01-16T00:00:00Z",
                },
            ],
        }
        adrs = generate_adrs_for_project(memory, "tropelex", only_significant=True)
        assert len(adrs) == 1
        assert adrs[0]["filename"].startswith("ADR-")

    def test_includes_all_when_not_significant_filter(self):
        memory = {
            "project_name": "test-project",
            "decisions": [
                {"decision": "Short", "timestamp": "2026-01-15T00:00:00Z"},
            ],
        }
        adrs = generate_adrs_for_project(memory, "tropelex", only_significant=False)
        assert len(adrs) == 1

    def test_empty_project(self):
        memory = {"project_name": "empty", "decisions": []}
        assert generate_adrs_for_project(memory) == []


class TestGenerateADRBundle:
    def test_bundle_generation(self):
        memory = {
            "project_name": "my-project",
            "decisions": [
                {
                    "decision": "Use FastAPI for backend server",
                    "context": "Async support needed",
                    "timestamp": "2026-01-15T00:00:00Z",
                },
            ],
        }
        bundle = generate_adr_markdown_bundle(memory)
        assert "my-project" in bundle
        assert "Table of Contents" in bundle
        assert "FastAPI" in bundle

    def test_empty_bundle(self):
        memory = {"project_name": "empty", "decisions": []}
        bundle = generate_adr_markdown_bundle(memory)
        assert "No decisions" in bundle
