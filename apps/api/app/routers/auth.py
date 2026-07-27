"""Local authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from ..deps import CurrentUser, SessionDep
from ..schemas.auth import (
    AccountResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from ..security.tokens import create_access_token
from ..services.accounts import authenticate, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, session: SessionDep) -> RegisterResponse:
    user = register_user(
        session,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        daily_minutes=payload.daily_minutes,
        target_level=payload.target_level,
        explanation_language=payload.explanation_language,
        timezone=payload.timezone,
    )
    session.commit()

    token, expires_in = create_access_token(user.id)
    return RegisterResponse(
        account=AccountResponse(id=user.id, email=user.email),
        token=TokenResponse(access_token=token, expires_in=expires_in),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: SessionDep) -> TokenResponse:
    user = authenticate(session, email=payload.email, password=payload.password)
    session.commit()

    token, expires_in = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=AccountResponse)
def read_current_account(user: CurrentUser) -> AccountResponse:
    return AccountResponse(id=user.id, email=user.email)
