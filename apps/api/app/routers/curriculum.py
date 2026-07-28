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
from ..schemas.profile import TrackOption, TrackOptions
from ..services import tracks

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


@router.get("/tracks", response_model=TrackOptions)
def read_tracks() -> TrackOptions:
    """The tracks a learner may choose, and what choosing one does.

    Unauthenticated, like the rest of this router: which tracks exist is a
    property of the curriculum, not of a learner, and someone deciding whether
    to sign up should be able to see what the product is for.

    `priority_domains` is returned rather than kept internal so the choice is
    inspectable. A track presented as a name with unstated consequences is the
    same opaque personalisation `docs/ADAPTIVE_ENGINE.md` refuses elsewhere.
    """
    return TrackOptions(
        tracks=[
            TrackOption(
                key=track.key,
                name=track.name,
                levels=list(track.levels),
                scenarios=list(track.scenarios),
                priority_domains=[SkillDomain(domain) for domain in track.priority_domains],
            )
            for track in tracks.available()
        ],
        caveats=[
            "A track changes what gets offered first. It never removes "
            "anything: if something basic is holding you back, you will still "
            "be given it, ahead of work that fits the track better.",
            "The levels listed are where a track's situations live, not a "
            "requirement to meet before choosing it.",
            "You can change track whenever you like. Nothing you have already "
            "shown is lost or reset by switching.",
        ],
    )
