"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select, text

from ..curriculum.loader import active_curriculum_version
from ..deps import SessionDep
from ..models.curriculum import CurriculumVersion
from ..settings import settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    curriculum_version: str | None
    curriculum_versions_loaded: int
    ai_provider: str
    speech_provider: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness only. Never touches the database, so it stays fast and honest."""
    return HealthResponse(status="ok", service="fluentforge-api")


@router.get("/ready", response_model=ReadinessResponse)
def ready(session: SessionDep) -> ReadinessResponse:
    """Readiness: the API is only useful once the database and curriculum exist."""
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - readiness must report, not raise
        return ReadinessResponse(
            status="degraded",
            database="unavailable",
            curriculum_version=None,
            curriculum_versions_loaded=0,
            ai_provider=settings.ai_provider,
            speech_provider=settings.speech_provider,
        )

    version = active_curriculum_version(session)
    loaded = len(session.execute(select(CurriculumVersion.id)).scalars().all())

    return ReadinessResponse(
        status="ok" if version is not None else "degraded",
        database="ok",
        curriculum_version=version.semantic_version if version else None,
        curriculum_versions_loaded=loaded,
        ai_provider=settings.ai_provider,
        speech_provider=settings.speech_provider,
    )
