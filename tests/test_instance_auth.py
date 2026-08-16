"""Tests for P1 (Adversarial Hardening plan): instance shared-secret auth
and Host header validation. Closes gap A -- previously any local process
could mutate state with zero credentials.

conftest.py's patched TestClient sends an allowed Host header and a valid
Authorization token by default on every instance, so most of the existing
suite exercises the "authenticated" path implicitly. These tests exercise
the middleware's actual decision boundaries directly.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app

SECRET = os.environ["TROPEL_EX_SECRET"]


@pytest.fixture
def project():
    return f"test_instance_auth_{uuid.uuid4().hex[:8]}"


def _create_project_body(project):
    return {"project_name": project}


class TestHostValidation:
    def test_valid_host_passes(self, project):
        client = TestClient(app, base_url="http://127.0.0.1:8766")
        resp = client.post("/api/memory", json=_create_project_body(project))
        assert resp.status_code == 200

    def test_spoofed_host_rejected(self, project):
        client = TestClient(app, base_url="http://127.0.0.1:8766")
        resp = client.post(
            "/api/memory",
            json=_create_project_body(project),
            headers={"Host": "evil.com"},
        )
        assert resp.status_code == 400
        assert "Invalid Host header" in resp.json()["detail"]

    def test_get_requests_also_host_validated(self):
        client = TestClient(app, base_url="http://127.0.0.1:8766")
        resp = client.get(
            "/api/interfaces/status",
            headers={"Host": "attacker.example"},
        )
        assert resp.status_code == 400


class TestInstanceAuthOnMutatingEndpoints:
    def test_no_token_no_same_origin_signal_rejected(self, project):
        client = TestClient(app, base_url="http://127.0.0.1:8766", headers={})
        resp = client.post(
            "/api/memory",
            json=_create_project_body(project),
            headers={"Authorization": ""},
        )
        assert resp.status_code == 401
        assert "instance secret" in resp.json()["detail"]

    def test_correct_token_accepted(self, project):
        client = TestClient(app, base_url="http://127.0.0.1:8766", headers={})
        resp = client.post(
            "/api/memory",
            json=_create_project_body(project),
            headers={"Authorization": f"Bearer {SECRET}"},
        )
        assert resp.status_code == 200

    def test_token_via_x_tropelex_key_header_accepted(self, project):
        client = TestClient(app, base_url="http://127.0.0.1:8766", headers={})
        resp = client.post(
            "/api/memory",
            json=_create_project_body(project),
            headers={"Authorization": "", "X-Tropelex-Key": SECRET},
        )
        assert resp.status_code == 200

    def test_wrong_token_rejected(self, project):
        client = TestClient(app, base_url="http://127.0.0.1:8766", headers={})
        resp = client.post(
            "/api/memory",
            json=_create_project_body(project),
            headers={"Authorization": "Bearer not-the-real-secret"},
        )
        assert resp.status_code == 401

    def test_same_origin_browser_request_exempt_without_token(self, project):
        """The dashboard, running as same-origin browser JS, never sends a
        token -- the browser's own Sec-Fetch-Site header (which page JS
        cannot forge) is what exempts it."""
        client = TestClient(app, base_url="http://127.0.0.1:8766", headers={})
        resp = client.post(
            "/api/memory",
            json=_create_project_body(project),
            headers={"Authorization": "", "Sec-Fetch-Site": "same-origin"},
        )
        assert resp.status_code == 200

    def test_cross_site_request_not_exempt_even_with_browser_header(self, project):
        """A request the browser marks cross-site (e.g. a malicious page on
        another origin trying to POST here) must still present the token --
        Sec-Fetch-Site alone only exempts genuinely same-origin traffic."""
        client = TestClient(app, base_url="http://127.0.0.1:8766", headers={})
        resp = client.post(
            "/api/memory",
            json=_create_project_body(project),
            headers={"Authorization": "", "Sec-Fetch-Site": "cross-site"},
        )
        assert resp.status_code == 401

    def test_get_requests_are_never_auth_gated(self, project):
        """Reads stay open by default (TROPEL_EX_LOCK_READS is a separate,
        not-yet-implemented follow-up) -- only mutating methods are gated."""
        client = TestClient(app, base_url="http://127.0.0.1:8766", headers={})
        resp = client.get("/api/interfaces/status")
        assert resp.status_code == 200
