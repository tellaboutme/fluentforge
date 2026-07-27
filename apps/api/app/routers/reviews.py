"""Review queue endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..deps import CurrentUser, SessionDep
from ..learning.scheduling import Grade
from ..models.enums import MemoryObjectType, ReviewMode
from ..services import errors_log
from ..services import reviews as service

router = APIRouter(prefix="/reviews", tags=["reviews"])


class ReviewCard(BaseModel):
    id: uuid.UUID
    memory_object_key: str
    review_mode: ReviewMode
    lemma: str
    pos: str
    cefr_level: str
    #: Withheld until the learner has committed to an answer.
    meaning: str | None = None
    example: str | None = None
    repetitions: int
    lapses: int


class DueReviewsResponse(BaseModel):
    due_now: int = Field(description="Total due, which may exceed the returned cards.")
    returned: int = Field(description="Capped so a large backlog stays approachable.")
    cards: list[ReviewCard]


class AnswerReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: Grade


class AnswerReviewResponse(BaseModel):
    id: uuid.UUID
    interval_days: float
    due_at: str
    explanation: str
    stability: float
    difficulty: float
    repetitions: int
    lapses: int
    #: The full card, revealed only now that the learner has committed.
    meaning: str
    example: str


class SeedReviewsResponse(BaseModel):
    created: int
    due_now: int


@router.get("/due", response_model=DueReviewsResponse)
def read_due(user: CurrentUser, session: SessionDep, limit: int = 20) -> DueReviewsResponse:
    items = service.due_reviews(session, user.id, limit=limit)
    entries = service.lexis_by_key()

    patterns = {
        pattern.taxonomy_code: pattern for pattern in errors_log.active_errors(session, user.id)
    }

    cards: list[ReviewCard] = []
    for item in items:
        if item.memory_object_type is MemoryObjectType.ERROR_PATTERN:
            pattern = patterns.get(item.memory_object_key)
            if pattern is not None:
                cards.append(
                    ReviewCard(
                        id=item.id,
                        memory_object_key=item.memory_object_key,
                        review_mode=item.review_mode,
                        lemma=pattern.canonical_description,
                        pos="error pattern",
                        cefr_level="",
                        meaning=None,
                        example=None,
                        repetitions=item.repetitions,
                        lapses=item.lapses,
                    )
                )
            continue

        entry = entries.get(item.memory_object_key)
        if entry is None:
            continue
        cards.append(
            ReviewCard(
                id=item.id,
                memory_object_key=item.memory_object_key,
                review_mode=item.review_mode,
                lemma=entry.lemma,
                pos=entry.pos,
                cefr_level=entry.cefr_level.value,
                # A recall card that shipped its own answer would not be a
                # test of anything.
                meaning=None,
                example=None,
                repetitions=item.repetitions,
                lapses=item.lapses,
            )
        )

    return DueReviewsResponse(
        due_now=service.due_count(session, user.id),
        returned=len(cards),
        cards=cards,
    )


@router.post("/seed", response_model=SeedReviewsResponse)
def seed(user: CurrentUser, session: SessionDep) -> SeedReviewsResponse:
    """Create any missing cards. Idempotent."""
    created = service.seed_reviews(session, user.id)
    session.commit()
    return SeedReviewsResponse(created=len(created), due_now=service.due_count(session, user.id))


@router.post("/{review_id}/answer", response_model=AnswerReviewResponse)
def answer(
    review_id: uuid.UUID,
    payload: AnswerReviewRequest,
    user: CurrentUser,
    session: SessionDep,
) -> AnswerReviewResponse:
    item, result = service.answer_review(session, user.id, review_id, grade=payload.grade)
    session.commit()

    entry = service.lexis_by_key()[item.memory_object_key]
    return AnswerReviewResponse(
        id=item.id,
        interval_days=result.interval_days,
        due_at=item.due_at.isoformat(),
        explanation=result.explanation,
        stability=item.stability,
        difficulty=item.difficulty,
        repetitions=item.repetitions,
        lapses=item.lapses,
        meaning=entry.meaning,
        example=entry.example,
    )
