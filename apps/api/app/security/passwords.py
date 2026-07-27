"""Password hashing and policy.

bcrypt is used directly rather than through a wrapper library to keep the
dependency surface small and the failure modes obvious.
"""

from __future__ import annotations

import bcrypt

from ..errors import WeakPasswordError
from ..settings import settings

# bcrypt truncates silently beyond 72 bytes; reject rather than truncate.
MAX_PASSWORD_BYTES = 72
BCRYPT_ROUNDS = 12


def validate_password(password: str) -> None:
    """Enforce the password policy.

    Raises:
        WeakPasswordError: with an actionable message.
    """
    minimum = settings.password_min_length
    if len(password) < minimum:
        raise WeakPasswordError(
            f"Password must be at least {minimum} characters.",
            details={"min_length": minimum},
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise WeakPasswordError(
            f"Password must be at most {MAX_PASSWORD_BYTES} bytes.",
            details={"max_bytes": MAX_PASSWORD_BYTES},
        )
    if password.strip() != password:
        raise WeakPasswordError("Password must not start or end with whitespace.")
    if len(set(password)) < 4:
        raise WeakPasswordError("Password must use at least 4 distinct characters.")


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode(
        "utf-8"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification. Never raises on malformed stored hashes."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
