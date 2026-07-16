"""Unit tests for jwt_service — pure function verification."""

import pytest
from datetime import datetime, timedelta, timezone

from core.auth.jwt_service import generate_token, validate_token


SECRET = "test-secret-key-for-unit-tests"
VALID_PAYLOAD = {"user_id": "u-123", "role": "admin"}


class TestGenerateToken:
    """generate_token returns a valid JWT string."""

    def test_returns_string(self):
        token = generate_token(VALID_PAYLOAD, SECRET)
        assert isinstance(token, str)

    def test_token_has_three_parts(self):
        token = generate_token(VALID_PAYLOAD, SECRET)
        assert len(token.split(".")) == 3

    def test_includes_custom_claims(self):
        token = generate_token(VALID_PAYLOAD, SECRET)
        decoded = validate_token(token, SECRET)
        assert decoded["user_id"] == "u-123"
        assert decoded["role"] == "admin"

    def test_custom_expires_hours(self):
        token = generate_token(VALID_PAYLOAD, SECRET, expires_hours=1)
        decoded = validate_token(token, SECRET)
        assert decoded is not None

    def test_missing_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            generate_token({"role": "admin"}, SECRET)

    def test_missing_role_raises(self):
        with pytest.raises(ValueError, match="role"):
            generate_token({"user_id": "u-1"}, SECRET)


class TestValidateToken:
    """validate_token returns dict on success, None on failure."""

    def test_valid_token_returns_payload(self):
        token = generate_token(VALID_PAYLOAD, SECRET)
        result = validate_token(token, SECRET)
        assert result is not None
        assert result["user_id"] == "u-123"
        assert result["role"] == "admin"

    def test_wrong_secret_returns_none(self):
        token = generate_token(VALID_PAYLOAD, SECRET)
        result = validate_token(token, "wrong-secret")
        assert result is None

    def test_malformed_token_returns_none(self):
        assert validate_token("not-a-jwt", SECRET) is None

    def test_empty_string_returns_none(self):
        assert validate_token("", SECRET) is None

    def test_expired_token_returns_none(self):
        # Force expiration by backdating iat/exp
        payload = {**VALID_PAYLOAD, "iat": datetime.now(timezone.utc) - timedelta(hours=48), "exp": datetime.now(timezone.utc) - timedelta(hours=24)}
        import jwt as pyjwt
        token = pyjwt.encode(payload, SECRET, algorithm="HS256")
        assert validate_token(token, SECRET) is None

    def test_different_role_round_trips(self):
        token = generate_token({"user_id": "u-99", "role": "viewer"}, SECRET)
        result = validate_token(token, SECRET)
        assert result["role"] == "viewer"
