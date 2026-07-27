"""Account registration and sign-in.

Pure service functions: no FastAPI types, so they are testable without HTTP.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.types import utcnow
from ..errors import (
    AccountInactiveError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)
from ..models.enums import CefrLevel, UserStatus
from ..models.identity import LearnerProfile, User
from ..security.passwords import hash_password, verify_password


def normalise_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.execute(
        select(User).where(func.lower(User.email) == normalise_email(email))
    ).scalar_one_or_none()


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    daily_minutes: int = 40,
    target_level: CefrLevel = CefrLevel.C2,
    explanation_language: str = "en",
    timezone: str = "UTC",
) -> User:
    """Create an account and its learner profile in one transaction.

    Raises:
        EmailAlreadyRegisteredError: the email is taken.
        WeakPasswordError: the password fails policy.
    """
    normalised = normalise_email(email)
    if get_user_by_email(session, normalised) is not None:
        raise EmailAlreadyRegisteredError()

    # hash_password validates policy first, so a weak password never creates a row.
    password_hash = hash_password(password)

    user = User(email=normalised, password_hash=password_hash, status=UserStatus.ACTIVE)
    user.profile = LearnerProfile(
        display_name=display_name.strip(),
        daily_minutes=daily_minutes,
        target_level=target_level,
        explanation_language=explanation_language,
        timezone=timezone,
        goals={},
        interests={},
        accessibility_preferences={},
        privacy_preferences={"store_raw_audio": False},
    )
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, *, email: str, password: str) -> User:
    """Verify credentials.

    Raises:
        InvalidCredentialsError: unknown email or wrong password (indistinguishable).
        AccountInactiveError: correct credentials on a suspended/deleted account.
    """
    user = get_user_by_email(session, email)
    if user is None:
        # Spend comparable time on unknown emails so response timing does not
        # reveal whether an address is registered.
        verify_password(password, _DUMMY_HASH)
        raise InvalidCredentialsError()

    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()

    if user.status is not UserStatus.ACTIVE:
        raise AccountInactiveError()

    user.last_login_at = utcnow()
    session.flush()
    return user


# A real bcrypt hash of a value no one can supply, used only for timing parity.
_DUMMY_HASH = "$2b$12$T6ZP0Yq0Zb4kQx8Fq1lQe.6mUkS0m3Q2n0y7C1pW9hR8vJ4sK2xLa"
