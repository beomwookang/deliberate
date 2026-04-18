"""Tests for auth utilities: JWT tokens, API key hashing, content hashing."""

from __future__ import annotations

import uuid
from datetime import UTC

import jwt
import pytest

from deliberate_server.auth import (
    APPROVAL_TOKEN_AUDIENCE,
    compute_content_hash,
    create_approval_token,
    hash_api_key,
    sign_content_hash,
    verify_api_key,
    verify_approval_token,
)
from deliberate_server.config import settings


class TestJwtTokens:
    def test_create_and_verify_token(self) -> None:
        approval_id = uuid.uuid4()
        token = create_approval_token(approval_id)
        result = verify_approval_token(token)
        assert result == approval_id

    def test_token_has_required_claims(self) -> None:
        approval_id = uuid.uuid4()
        token = create_approval_token(approval_id)
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience=APPROVAL_TOKEN_AUDIENCE,
        )
        assert payload["sub"] == str(approval_id)
        assert payload["aud"] == APPROVAL_TOKEN_AUDIENCE
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_expired_token_raises(self) -> None:
        from datetime import datetime, timedelta

        approval_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = {
            "sub": str(approval_id),
            "aud": APPROVAL_TOKEN_AUDIENCE,
            "jti": str(uuid.uuid4()),
            "iat": now - timedelta(days=10),
            "exp": now - timedelta(days=1),
        }
        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
        with pytest.raises(jwt.ExpiredSignatureError):
            verify_approval_token(token)

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(jwt.InvalidTokenError):
            verify_approval_token("not-a-real-token")

    def test_wrong_audience_raises(self) -> None:
        approval_id = uuid.uuid4()
        payload = {
            "sub": str(approval_id),
            "aud": "wrong-audience",
            "jti": str(uuid.uuid4()),
            "iat": 1700000000,
            "exp": 9999999999,
        }
        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
        with pytest.raises(jwt.InvalidAudienceError):
            verify_approval_token(token)


class TestApiKeyHashing:
    def test_hash_and_verify(self) -> None:
        key = "my-secret-api-key"
        hashed = hash_api_key(key)
        assert verify_api_key(key, hashed)

    def test_wrong_key_fails(self) -> None:
        hashed = hash_api_key("correct-key")
        assert not verify_api_key("wrong-key", hashed)


class TestContentHash:
    def test_deterministic(self) -> None:
        content = {"a": 1, "b": "hello", "c": [1, 2, 3]}
        h1 = compute_content_hash(content)
        h2 = compute_content_hash(content)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_key_order_irrelevant(self) -> None:
        c1 = {"b": 2, "a": 1}
        c2 = {"a": 1, "b": 2}
        assert compute_content_hash(c1) == compute_content_hash(c2)

    def test_different_content_different_hash(self) -> None:
        c1 = {"a": 1}
        c2 = {"a": 2}
        assert compute_content_hash(c1) != compute_content_hash(c2)

    def test_sign_content_hash(self) -> None:
        h = compute_content_hash({"test": True})
        sig = sign_content_hash(h)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex
