"""Learner profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, SessionDep
from ..schemas.profile import ProfileResponse, ProfileUpdateRequest
from ..services.profiles import build_profile_response, update_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
def read_profile(user: CurrentUser, session: SessionDep) -> ProfileResponse:
    return build_profile_response(session, user.id)


@router.patch("", response_model=ProfileResponse)
def patch_profile(
    payload: ProfileUpdateRequest, user: CurrentUser, session: SessionDep
) -> ProfileResponse:
    update_profile(session, user.id, payload)
    session.commit()
    return build_profile_response(session, user.id)
