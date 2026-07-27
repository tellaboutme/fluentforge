"""Access token issue and verification."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt

from ..db.types import utcnow
from ..errors import NotAuthenticatedError
from ..settings import settings

TOKEN_TYPE = "access"
ISSUER = "fluentforge"


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    expires_in_seconds: int


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    issued_at = utcnow()
    payload = {
        "sub": str(user_id),
        "iss": ISSUER,
        "typ": TOKEN_TYPE,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> TokenClaims:
    """Verify a token.

    Raises:
        NotAuthenticatedError: for expired, malformed, or wrong-purpose tokens.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise NotAuthenticatedError("Your session expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise NotAuthenticatedError("Invalid session token.") from exc

    if payload.get("typ") != TOKEN_TYPE:
        raise NotAuthenticatedError("Invalid session token.")

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise NotAuthenticatedError("Invalid session token.") from exc

    remaining = int(payload["exp"]) - int(utcnow().timestamp())
    return TokenClaims(user_id=user_id, expires_in_seconds=max(remaining, 0))
