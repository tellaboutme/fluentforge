"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db.session import get_session
from .errors import AccountInactiveError, NotAuthenticatedError
from .models.enums import UserStatus
from .models.identity import User
from .security.tokens import decode_access_token
from .services.accounts import get_user_by_id

bearer_scheme = HTTPBearer(auto_error=False, description="Bearer access token")

SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise NotAuthenticatedError()

    claims = decode_access_token(credentials.credentials)
    user = get_user_by_id(session, claims.user_id)
    if user is None:
        raise NotAuthenticatedError()
    if user.status is not UserStatus.ACTIVE:
        raise AccountInactiveError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
