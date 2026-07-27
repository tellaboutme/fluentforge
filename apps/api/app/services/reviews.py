"""Review queue: seeding cards, serving what is due, and rescheduling.

A review is evidence like any other, so answering one writes an
`EvidenceEvent` through the same path as a diagnostic item. Retrieval after a
delay is among the strongest evidence the model accepts, and recording it
anywhere else would put the mastery estimate out of step with what the learner
has actually done.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..curriculum.lexis import LexicalEntry, parse_lexis
from ..curriculum.loader import active_curriculum_version
from ..db.types import utcnow
from ..errors import CurriculumNotLoadedError, ReviewNotFoundError
from ..learning.scheduling import (
    SCHEDULER_VERSION,
    Grade,
    MemoryState,
    ScheduleResult,
    initial_due,
)
from ..learning.scheduling import (
    review as apply_review,
)
from ..models.curriculum import SkillNode
from ..models.enums import EvidenceType, MemoryObjectType, ReviewMode
from ..models.planning import ReviewQueueItem
from ..settings import settings
from .evidence import recompute_skill_state, record_evidence

#: How each retrieval mode maps onto the evidence taxonomy. Recognition can
#: never be recorded as production, whatever the learner got right.
MODE_EVIDENCE = {
    ReviewMode.MEANING_RECOGNITION: EvidenceType.RECOGNITION,
    ReviewMode.FORM_RECOGNITION: EvidenceType.RECOGNITION,
    ReviewMode.LISTENING_RECOGNITION: EvidenceType.RECOGNITION,
    ReviewMode.MEANING_RECALL: EvidenceType.CONTROLLED_RECALL,
    ReviewMode.FORM_RECALL: EvidenceType.CONTROLLED_RECALL,
    ReviewMode.PRONUNCIATION_PRODUCTION: EvidenceType.CONTEXTUAL_PRODUCTION,
    ReviewMode.CONTEXTUAL_PRODUCTION: EvidenceType.CONTEXTUAL_PRODUCTION,
}


@lru_cache(maxsize=4)
def _load_lexis(curriculum_dir: str) -> tuple[LexicalEntry, ...]:
    return parse_lexis(Path(curriculum_dir))


def lexis() -> tuple[LexicalEntry, ...]:
    return _load_lexis(str(settings.curriculum_dir))


def lexis_by_key() -> dict[str, LexicalEntry]:
    return {entry.key: entry for entry in lexis()}


def seed_reviews(
    session: Session,
    user_id: uuid.UUID,
    *,
    up_to_level_rank: int | None = None,
    now: datetime | None = None,
) -> list[ReviewQueueItem]:
    """Create review cards for a learner, one per entry per declared mode.

    Idempotent: re-running adds only what is missing, so a learner who returns
    after new vocabulary lands gets the new cards without losing their history.

    Args:
        up_to_level_rank: only seed entries at or below this CEFR rank. Seeding
            C1 idioms for an A1 learner would bury the useful cards.
    """
    moment = now or utcnow()
    existing = {
        (item.memory_object_key, item.review_mode)
        for item in session.execute(
            select(ReviewQueueItem).where(ReviewQueueItem.user_id == user_id)
        ).scalars()
    }

    created: list[ReviewQueueItem] = []
    for entry in lexis():
        if up_to_level_rank is not None and entry.cefr_level.rank > up_to_level_rank:
            continue
        for mode in entry.modes:
            if (entry.key, mode) in existing:
                continue
            item = ReviewQueueItem(
                user_id=user_id,
                memory_object_type=MemoryObjectType.LEXICAL_ENTRY,
                memory_object_key=entry.key,
                review_mode=mode,
                due_at=initial_due(moment, mode=mode),
                stability=0.0,
                difficulty=0.35,
                scheduler_version=SCHEDULER_VERSION,
            )
            session.add(item)
            created.append(item)

    session.flush()
    return created


def due_reviews(
    session: Session,
    user_id: uuid.UUID,
    *,
    limit: int = 20,
    now: datetime | None = None,
) -> list[ReviewQueueItem]:
    """Cards due for review, most overdue first.

    Capped: `docs/ADAPTIVE_ENGINE.md` asks for a *manageable portion* of due
    reviews. Showing a learner 300 overdue cards is how people quit.
    """
    moment = now or utcnow()
    return list(
        session.execute(
            select(ReviewQueueItem)
            .where(ReviewQueueItem.user_id == user_id, ReviewQueueItem.due_at <= moment)
            .order_by(ReviewQueueItem.due_at)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def due_count(session: Session, user_id: uuid.UUID, *, now: datetime | None = None) -> int:
    moment = now or utcnow()
    return len(
        session.execute(
            select(ReviewQueueItem.id).where(
                ReviewQueueItem.user_id == user_id, ReviewQueueItem.due_at <= moment
            )
        )
        .scalars()
        .all()
    )


def get_review(session: Session, user_id: uuid.UUID, review_id: uuid.UUID) -> ReviewQueueItem:
    item = session.execute(
        select(ReviewQueueItem).where(
            ReviewQueueItem.id == review_id, ReviewQueueItem.user_id == user_id
        )
    ).scalar_one_or_none()
    if item is None:
        raise ReviewNotFoundError()
    return item


def answer_review(
    session: Session,
    user_id: uuid.UUID,
    review_id: uuid.UUID,
    *,
    grade: Grade,
    now: datetime | None = None,
) -> tuple[ReviewQueueItem, ScheduleResult]:
    """Record a review outcome, reschedule the card, and write evidence."""
    moment = now or utcnow()
    item = get_review(session, user_id, review_id)

    result = apply_review(
        MemoryState(
            stability=item.stability,
            difficulty=item.difficulty,
            repetitions=item.repetitions,
            lapses=item.lapses,
        ),
        grade,
        mode=item.review_mode,
        now=moment,
    )

    item.stability = result.state.stability
    item.difficulty = result.state.difficulty
    item.repetitions = result.state.repetitions
    item.lapses = result.state.lapses
    item.last_reviewed_at = moment
    item.due_at = result.due_at
    item.scheduler_version = result.scheduler_version

    _record_review_evidence(session, user_id, item, grade, moment)
    session.flush()
    return item, result


def _record_review_evidence(
    session: Session,
    user_id: uuid.UUID,
    item: ReviewQueueItem,
    grade: Grade,
    moment: datetime,
) -> None:
    """Write the review as evidence against the entry's skill.

    Delayed retrieval is stronger evidence than an immediate check, which the
    novelty factor expresses: a card seen many times in one day contributes
    less than one recalled after a genuine gap.
    """
    entry = lexis_by_key().get(item.memory_object_key)
    if entry is None:
        return

    version = active_curriculum_version(session)
    if version is None:
        return

    node = session.execute(
        select(SkillNode).where(
            SkillNode.curriculum_version_id == version.id,
            SkillNode.key == entry.skill_key,
        )
    ).scalar_one_or_none()
    if node is None:
        return

    score = 0.0 if grade.is_lapse else {Grade.HARD: 0.6, Grade.GOOD: 1.0, Grade.EASY: 1.0}[grade]

    # A card recalled after a real gap proves more than one drilled minutes ago.
    days_since = (
        (moment - item.last_reviewed_at).total_seconds() / 86400.0
        if item.last_reviewed_at
        else 999.0
    )
    novelty = min(1.0, 0.3 + days_since)

    record_evidence(
        session,
        user_id=user_id,
        skill_node_id=node.id,
        evidence_type=MODE_EVIDENCE[item.review_mode],
        score=score,
        difficulty=_difficulty_for(entry),
        confidence=1.0,
        independence=1.0,
        novelty=novelty,
        context_key=f"review:{item.memory_object_key}:{item.review_mode.value}",
        occurred_at=moment,
        metadata={
            "source": "review",
            "review_mode": item.review_mode.value,
            "grade": grade.value,
        },
    )
    recompute_skill_state(session, user_id=user_id, skill_node_id=node.id, now=moment)


def _difficulty_for(entry: LexicalEntry) -> float:
    """Map the entry's CEFR level onto the 0..1 difficulty the model expects."""
    return round((entry.cefr_level.rank + 0.5) / 6, 4)


def seed_from_diagnostic(
    session: Session, user_id: uuid.UUID, *, band_rank: int | None
) -> list[ReviewQueueItem]:
    """Seed cards after a diagnostic, scoped to the learner's starting band.

    One level above the band is included: review should reach slightly beyond
    what is already comfortable.
    """
    if active_curriculum_version(session) is None:
        raise CurriculumNotLoadedError()
    ceiling = None if band_rank is None else band_rank + 1
    return seed_reviews(session, user_id, up_to_level_rank=ceiling)
