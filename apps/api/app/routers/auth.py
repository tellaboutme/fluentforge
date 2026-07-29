"""Local authentication endpoints.

Rate limited. `docs/PRIVACY_SAFETY.md` asks for limits on auth and there were
none, so `/auth/login` verified passwords as fast as anyone cared to ask --
while `main.py` already mapped 429 to `rate_limited`, a code nothing could
raise. See `app/security/rate_limit.py` for what the limiter is and is not.

Two things this file is careful about.

**The limit is checked before the account is looked up.** A limit that only
bit on real accounts would tell an attacker which addresses are registered,
which is the opposite of what `InvalidCredentialsError` goes out of its way to
hide.

**A successful login clears the caller's attempts.** Somebody who signs in ten
times a day is not guessing, and counting their successes towards a guessing
limit would eventually lock out the people who use the product most.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from ..deps import CurrentUser, SessionDep
from ..schemas.auth import (
    AccountResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from ..security import rate_limit
from ..security.tokens import create_access_token
from ..services.accounts import authenticate, normalise_email, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


def caller(request: Request) -> str:
    """A key for whoever is asking.

    The socket address, not a forwarded header. `X-Forwarded-For` is
    attacker-controlled unless a trusted proxy is known to rewrite it, and
    trusting it here would let anyone reset their own limit by inventing an
    address. A deployment behind a proxy has to configure that explicitly; it
    is not something to guess at.
    """
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, session: SessionDep) -> RegisterResponse:
    # Registration is not a guessing surface, but every attempt costs a
    # password hash, which is deliberately expensive -- so an unlimited one is
    # a way to burn the server's CPU as well as fill the table.
    rate_limit.register_by_caller.check(caller(request))

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
def login(payload: LoginRequest, request: Request, session: SessionDep) -> TokenResponse:
    from_caller = caller(request)
    # Normalised so that casing or stray whitespace cannot be used to get a
    # fresh bucket for the same account.
    account_key = normalise_email(payload.email)

    # Both, and before the lookup. Only by caller and an attacker rotates
    # addresses against one account; only by account and one address sprays
    # many. Neither on its own is a limit.
    rate_limit.login_by_caller.check(from_caller)
    rate_limit.login_by_account.check(account_key)

    user = authenticate(session, email=payload.email, password=payload.password)
    session.commit()

    rate_limit.login_by_caller.clear(from_caller)
    rate_limit.login_by_account.clear(account_key)

    token, expires_in = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=AccountResponse)
def read_current_account(user: CurrentUser) -> AccountResponse:
    return AccountResponse(id=user.id, email=user.email)
