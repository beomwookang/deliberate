"""Auth endpoints for token and identity verification."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deliberate_server.auth import verify_approval_token

logger = logging.getLogger("deliberate_server.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

MAGIC_LINK_AUDIENCE = "deliberate-magic-link"
MAGIC_LINK_EXPIRY_MINUTES = 15
SESSION_TOKEN_AUDIENCE = "deliberate-session"
SESSION_TOKEN_EXPIRY_HOURS = 24


class VerifyTokenRequest(BaseModel):
    token: str


class VerifyTokenResponse(BaseModel):
    approval_id: str


@router.post("/verify-approval-token", response_model=VerifyTokenResponse)
async def verify_approval_token_endpoint(body: VerifyTokenRequest) -> VerifyTokenResponse:
    """Verify a JWT approval token and return the approval_id."""
    try:
        approval_id = verify_approval_token(body.token)
        return VerifyTokenResponse(approval_id=str(approval_id))
    except pyjwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=410, detail="Token has expired") from e
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e


class MagicLinkRequest(BaseModel):
    email: str
    approval_id: str


class MagicLinkResponse(BaseModel):
    message: str
    token: str | None = None


@router.post("/magic-link", response_model=MagicLinkResponse)
async def request_magic_link(body: MagicLinkRequest) -> MagicLinkResponse:
    """Generate a magic link token for approver email verification."""
    from deliberate_server.auth import _jwt_key

    now = datetime.now(UTC)
    payload = {
        "sub": body.email,
        "aud": MAGIC_LINK_AUDIENCE,
        "approval_id": body.approval_id,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=MAGIC_LINK_EXPIRY_MINUTES),
    }
    token = pyjwt.encode(payload, _jwt_key, algorithm="HS256")

    # TODO: Send email with magic link URL in production
    logger.info("Magic link generated for %s (approval %s)", body.email, body.approval_id)

    return MagicLinkResponse(
        message="Magic link sent to your email",
        token=token,  # Include in response for dev/testing
    )


class VerifyMagicLinkRequest(BaseModel):
    token: str


class SessionTokenResponse(BaseModel):
    session_token: str
    email: str
    expires_at: str


@router.post("/verify-magic-link", response_model=SessionTokenResponse)
async def verify_magic_link(body: VerifyMagicLinkRequest) -> SessionTokenResponse:
    """Verify a magic link token and return a session token."""
    from deliberate_server.auth import _jwt_key

    try:
        payload = pyjwt.decode(
            body.token, _jwt_key, algorithms=["HS256"], audience=MAGIC_LINK_AUDIENCE
        )
    except pyjwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=410, detail="Magic link has expired") from e
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="Invalid magic link") from e

    email: str = payload["sub"]
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=SESSION_TOKEN_EXPIRY_HOURS)

    session_payload = {
        "sub": email,
        "aud": SESSION_TOKEN_AUDIENCE,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": expires_at,
    }
    session_token = pyjwt.encode(session_payload, _jwt_key, algorithm="HS256")

    return SessionTokenResponse(
        session_token=session_token,
        email=email,
        expires_at=expires_at.isoformat(),
    )


class VerifySessionRequest(BaseModel):
    session_token: str


class VerifySessionResponse(BaseModel):
    email: str
    valid: bool


@router.post("/verify-session", response_model=VerifySessionResponse)
async def verify_session(body: VerifySessionRequest) -> VerifySessionResponse:
    """Verify a session token and return the email."""
    from deliberate_server.auth import _jwt_key

    try:
        payload = pyjwt.decode(
            body.session_token, _jwt_key, algorithms=["HS256"], audience=SESSION_TOKEN_AUDIENCE
        )
        return VerifySessionResponse(email=payload["sub"], valid=True)
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from e
