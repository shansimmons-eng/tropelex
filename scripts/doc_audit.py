#!/usr/bin/env python3
"""
Doc Audit — scan markdown files against the codebase for discrepancies.

Finds:
- Features documented but not implemented
- Features implemented but not documented
- Stale API endpoints referenced in docs
- Missing test coverage hints

Usage:
    python3 scripts/doc_audit.py                    # full audit
    python3 scripts/doc_audit.py --summary          # just the summary
    python3 scripts/doc_audit.py --check-readme     # only README.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "design.md", ROOT / "wishlist.md"]


def extract_md_sections(text: str) -> list[str]:
    """Extract ### heading lines from markdown."""
    return [line.strip() for line in text.splitlines() if line.strip().startswith("###")]


def extract_api_endpoints(text: str) -> list[str]:
    """Extract /api/... endpoint paths from markdown."""
    return list(set(re.findall(r'/api/[\w/{}\-]+', text)))


def extract_module_names(text: str) -> list[str]:
    """Extract core/module references from markdown."""
    return list(set(re.findall(r'core/[\w/]+\.py', text)))


def find_python_modules(root: Path) -> set[str]:
    """Find all Python modules in core/."""
    modules = set()
    for p in (root / "core").rglob("*.py"):
        rel = str(p.relative_to(root)).replace("\\", "/")
        modules.add(rel)
    return modules


def find_test_files(root: Path) -> set[str]:
    """Find all test files in tests/."""
    tests = set()
    for p in (root / "tests").rglob("test_*.py"):
        tests.add(p.stem.replace("test_", ""))
    return tests


def find_api_routes(root: Path) -> set[str]:
    """Extract API routes from server.py and routers."""
    routes = set()
    for py_file in (root / "core").rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in re.findall(r'@app\.(get|post|put|delete|patch)\("([^"]+)"', text):
            routes.add(match[1])
        for match in re.findall(r'@(?:app|router)\.(get|post|put|delete|patch)\("([^"]+)"', text):
            routes.add(match[1])
    return routes


def audit_readme(root: Path) -> list[dict]:
    """Audit README.md against codebase."""
    issues = []
    readme = (root / "README.md").read_text(encoding="utf-8")

    # Check API endpoints mentioned in README exist in code
    doc_endpoints = extract_api_endpoints(readme)
    code_routes = find_api_routes(root)

    for ep in doc_endpoints:
        # Normalize: strip query params, trailing slashes
        ep_clean = ep.split("?")[0].rstrip("/")
        # Skip parameterized routes for now
        if "{" in ep_clean:
            continue
        if ep_clean and ep_clean not in code_routes:
            # Check if it's a documented but not-yet-implemented endpoint
            issues.append({
                "file": "README.md",
                "type": "stale_endpoint",
                "detail": f"Documented endpoint {ep} not found in codebase",
            })

    # Check test count
    test_count_match = re.search(r'(\d+)\s*tests?\s*(?:passing|pass)', readme, re.IGNORECASE)
    if test_count_match:
        doc_count = int(test_count_match.group(1))
        actual_tests = len(list((root / "tests").rglob("test_*.py")))
        if actual_tests > doc_count + 5:  # allow some slack
            issues.append({
                "file": "README.md",
                "type": "stale_test_count",
                "detail": f"Docs say {doc_count} tests, but {actual_tests} test files exist. Update the count.",
            })

    return issues


def audit_agents_md(root: Path) -> list[dict]:
    """Audit AGENTS.md against codebase."""
    issues = []
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    # Check module references
    doc_modules = extract_module_names(agents)
    code_modules = find_python_modules(root)

    for mod in doc_modules:
        if mod not in code_modules:
            issues.append({
                "file": "AGENTS.md",
                "type": "stale_module_ref",
                "detail": f"References {mod} but file not found",
            })

    return issues


def audit_wishlist(root: Path) -> list[dict]:
    """Check wishlist.md for features that are implemented but not marked."""
    issues = []
    wishlist = (root / "wishlist.md").read_text(encoding="utf-8")
    code_modules = find_python_modules(root)

    # Look for features that have implementations but no ✅
    # This is a heuristic — look for ### headings without ✅ that have matching code
    lines = wishlist.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("###") and "✅" not in line:
            # Check if there's a core/ module that matches
            heading = line.lstrip("#").strip().lower()
            for mod in code_modules:
                mod_name = Path(mod).stem.lower()
                if mod_name in heading and mod_name not in ("__init__",):
                    issues.append({
                        "file": "wishlist.md",
                        "type": "maybe_implemented",
                        "detail": f"'{line.strip()}' may be implemented ({mod} exists). Consider marking ✅.",
                    })
                    break

    return issues


def audit_cross_docs(root: Path) -> list[dict]:
    """Check for inconsistencies between README, AGENTS, and design.md."""
    issues = []
    readme = (root / "README.md").read_text(encoding="utf-8")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    design = (root / "design.md").read_text(encoding="utf-8")

    # Check for version strings
    readme_version = re.search(r'v(\d+\.\d+\.\d+)', readme)
    design_version = re.search(r'v(\d+\.\d+\.\d+)', design)
    if readme_version and design_version:
        if readme_version.group(1) != design_version.group(1):
            issues.append({
                "file": "README.md / design.md",
                "type": "version_mismatch",
                "detail": f"README says {readme_version.group(0)}, design.md says {design_version.group(0)}",
            })

    return issues


def run_audit(root: Path, summary_only: bool = False) -> list[dict]:
    """Run all audits."""
    all_issues = []
    all_issues.extend(audit_readme(root))
    all_issues.extend(audit_agents_md(root))
    all_issues.extend(audit_wishlist(root))
    all_issues.extend(audit_cross_docs(root))
    return all_issues


def main() -> int:
    summary_only = "--summary" in sys.argv
    issues = run_audit(ROOT, summary_only)

    if not issues:
        print("✅ No documentation issues found.")
        return 0

    print(f"⚠️  Found {len(issues)} documentation issue(s):\n")
    for issue in issues:
        icon = {"stale_endpoint": "🔗", "stale_test_count": "📊", "stale_module_ref": "📁",
                "maybe_implemented": "💡", "version_mismatch": "🏷️"}.get(issue["type"], "❓")
        print(f"  {icon} [{issue['file']}] {issue['detail']}")

    print(f"\nTotal: {len(issues)} issue(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
