"""Authentication and token utilities.

JWT approval tokens (HS256): implemented now for M2 readiness.
API key authentication: used in M1 for SDK-to-server auth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from deliberate_server.config import settings

APPROVAL_TOKEN_AUDIENCE = "deliberate-approval"
APPROVAL_TOKEN_EXPIRY_DAYS = 7


def create_approval_token(approval_id: uuid.UUID) -> str:
    """Create a signed JWT token for an approval URL.

    Claims: sub=approval_id, aud=deliberate-approval, jti=unique, iat, exp.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(approval_id),
        "aud": APPROVAL_TOKEN_AUDIENCE,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(days=APPROVAL_TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def verify_approval_token(token: str) -> uuid.UUID:
    """Verify and decode an approval JWT token.

    Returns the approval_id from the token's sub claim.

    Raises:
        jwt.ExpiredSignatureError: Token has expired (caller should return 410).
        jwt.InvalidTokenError: Token is invalid (caller should return 401).
    """
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=["HS256"],
        audience=APPROVAL_TOKEN_AUDIENCE,
    )
    return uuid.UUID(payload["sub"])


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage/comparison using SHA-256."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    """Constant-time comparison of an API key against its stored hash."""
    return hmac.compare_digest(hash_api_key(api_key), stored_hash)


def compute_content_hash(content: dict[str, Any]) -> str:
    """Compute SHA-256 hash of ledger content for tamper detection.

    Uses canonical JSON (sorted keys, no whitespace) for deterministic output.
    The content dict must NOT include the 'signature' field.
    """
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def sign_content_hash(content_hash: str) -> str:
    """HMAC-sign a content hash with the server's secret key."""
    return hmac.new(
        settings.secret_key.encode(),
        content_hash.encode(),
        hashlib.sha256,
    ).hexdigest()


def sign_decision(fields: dict[str, Any]) -> str:
    """Create an HMAC signature over decision fields."""
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(
        settings.secret_key.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
