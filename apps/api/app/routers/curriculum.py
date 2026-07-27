"""Read-only curriculum endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from ..curriculum.loader import active_curriculum_version
from ..deps import SessionDep
from ..errors import CurriculumNotLoadedError
from ..models.curriculum import SkillNode
from ..models.enums import CefrLevel, SkillDomain

router = APIRouter(prefix="/curriculum", tags=["curriculum"])


class SkillNodeSummary(BaseModel):
    key: str
    domain: SkillDomain
    title: str
    can_do: str
    cefr_min: CefrLevel
    cefr_max: CefrLevel
    difficulty: float


class CurriculumVersionResponse(BaseModel):
    semantic_version: str
    status: str
    source_hash: str
    skill_count: int
    skills: list[SkillNodeSummary]


@router.get("", response_model=CurriculumVersionResponse)
def read_active_curriculum(session: SessionDep) -> CurriculumVersionResponse:
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()

    nodes = (
        session.execute(
            select(SkillNode)
            .where(SkillNode.curriculum_version_id == version.id)
            .order_by(SkillNode.cefr_min, SkillNode.domain, SkillNode.key)
        )
        .scalars()
        .all()
    )

    return CurriculumVersionResponse(
        semantic_version=version.semantic_version,
        status=version.status.value,
        source_hash=version.source_hash,
        skill_count=len(nodes),
        skills=[
            SkillNodeSummary(
                key=node.key,
                domain=node.domain,
                title=node.title,
                can_do=node.description or "",
                cefr_min=node.cefr_min,
                cefr_max=node.cefr_max,
                difficulty=node.difficulty,
            )
            for node in nodes
        ],
    )
