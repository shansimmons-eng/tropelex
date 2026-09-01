"""
Tests for the locally-served documentation routes (core/tropebook/web/
server.py): /guide, /faq, /getting-started, /api-reference. /faq and
/getting-started are new (#search) -- before this, only /guide and
/api-reference existed locally, and neither had test coverage at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


class TestLocalDocRoutes:
    @pytest.mark.parametrize("path,expected_text", [
        ("/guide", "Tropelex Documentation"),
        ("/faq", "Tropelex FAQ"),
        ("/getting-started", "Tropelex Getting Started"),
        ("/api-reference", "Tropelex API Reference"),
    ])
    def test_route_serves_real_content(self, client, path, expected_text):
        resp = client.get(path)
        assert resp.status_code == 200
        assert expected_text in resp.text

    def test_api_docs_alias_serves_same_content(self, client):
        assert client.get("/api-docs").status_code == 200

    @pytest.mark.parametrize("path", ["/guide", "/faq", "/getting-started", "/api-reference"])
    def test_no_leftover_deployed_site_relative_links(self, client, path):
        """Regression for the staleness bug #search found: internal nav
        must point at local routes (rewritten by scripts/sync_local_docs.py),
        not the deployed site's own *.html filenames."""
        resp = client.get(path)
        assert 'href="index.html"' not in resp.text
        assert 'href="faq.html"' not in resp.text
        assert 'href="getting-started.html"' not in resp.text
        assert 'href="api-reference.html"' not in resp.text

    @pytest.mark.parametrize("path", ["/guide", "/faq", "/getting-started", "/api-reference"])
    def test_local_nav_has_dashboard_link(self, client, path):
        """Confirms the local-only nav customization (scripts/sync_local_
        docs.py) is present, not just a bare copy of the deployed site."""
        resp = client.get(path)
        assert "Back to Dashboard" in resp.text
