"""Recurring error patterns, and turning them into scheduled practice.

An error log that only accumulates is a list of grievances. This module closes
the loop `docs/LEARNING_SCIENCE.md` asks for: an error that keeps recurring
becomes a review card, is spaced like anything else, and stops being scheduled
once the learner stops making it.

Priority follows the ranking in `docs/LEARNING_SCIENCE.md`: errors that block
meaning outrank repeated ones, which outrank everything else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.types import utcnow
from ..learning.scheduling import SCHEDULER_VERSION, initial_due
from ..models.enums import ErrorStatus, MemoryObjectType, ReviewMode
from ..models.learning import ErrorPattern
from ..models.planning import ReviewQueueItem

#: An error must recur this often before it earns a place in the review queue.
#: A one-off slip is noise; scheduling practice for it wastes the learner's time.
RECURRENCE_THRESHOLD = 2

#: Errors that block meaning skip the threshold: they matter immediately.
BLOCKING_THRESHOLD = 1


def record_error(
    session: Session,
    user_id: uuid.UUID,
    *,
    taxonomy_code: str,
    description: str,
    example: str | None = None,
    blocks_meaning: bool = False,
    now: datetime | None = None,
) -> ErrorPattern:
    """Log an error occurrence, merging into an existing pattern if present.

    Patterns accumulate rather than duplicating: the same mistake made ten
    times is one pattern with a count of ten, which is what makes "repeated"
    measurable.
    """
    moment = now or utcnow()
    pattern = session.execute(
        select(ErrorPattern).where(
            ErrorPattern.user_id == user_id, ErrorPattern.taxonomy_code == taxonomy_code
        )
    ).scalar_one_or_none()

    if pattern is None:
        pattern = ErrorPattern(
            user_id=user_id,
            taxonomy_code=taxonomy_code,
            canonical_description=description,
            first_seen_at=moment,
            last_seen_at=moment,
            occurrence_count=1,
            blocks_meaning=blocks_meaning,
            status=ErrorStatus.ACTIVE,
            examples=[example] if example else [],
        )
        session.add(pattern)
    else:
        pattern.occurrence_count += 1
        pattern.last_seen_at = moment
        pattern.status = ErrorStatus.ACTIVE
        # Once an error is seen to block meaning it keeps that flag: a pattern
        # that sometimes destroys the message is a meaning-blocking pattern.
        pattern.blocks_meaning = pattern.blocks_meaning or blocks_meaning
        if example:
            # Keep a bounded sample; the log is for guidance, not forensics.
            pattern.examples = [*pattern.examples, example][-5:]

    pattern.current_priority = priority_for(pattern)
    session.flush()
    return pattern


def priority_for(pattern: ErrorPattern) -> float:
    """Rank an error, 0..1, following `docs/LEARNING_SCIENCE.md`.

    Meaning first, then repetition. Deliberately coarse: a finer ranking would
    imply a precision this has no data to support.
    """
    score = 0.0
    if pattern.blocks_meaning:
        score += 0.5
    # Repetition saturates: the tenth occurrence is not five times the fifth.
    score += min(0.5, 0.1 * pattern.occurrence_count)
    return round(min(1.0, score), 4)


def schedulable(pattern: ErrorPattern) -> bool:
    """Whether this error has earned a place in the review queue."""
    if pattern.status is ErrorStatus.RESOLVED:
        return False
    threshold = BLOCKING_THRESHOLD if pattern.blocks_meaning else RECURRENCE_THRESHOLD
    return pattern.occurrence_count >= threshold


def sync_error_cards(
    session: Session, user_id: uuid.UUID, *, now: datetime | None = None
) -> list[ReviewQueueItem]:
    """Create review cards for errors that have recurred enough to matter.

    Idempotent. Cards are created in `contextual_production` mode: an error is
    only really fixed when the learner produces the correct form themselves,
    not when they recognise it in a list.
    """
    moment = now or utcnow()

    existing = {
        item.memory_object_key
        for item in session.execute(
            select(ReviewQueueItem).where(
                ReviewQueueItem.user_id == user_id,
                ReviewQueueItem.memory_object_type == MemoryObjectType.ERROR_PATTERN,
            )
        ).scalars()
    }

    created: list[ReviewQueueItem] = []
    for pattern in session.execute(
        select(ErrorPattern).where(ErrorPattern.user_id == user_id)
    ).scalars():
        if not schedulable(pattern) or pattern.taxonomy_code in existing:
            continue
        item = ReviewQueueItem(
            user_id=user_id,
            memory_object_type=MemoryObjectType.ERROR_PATTERN,
            memory_object_key=pattern.taxonomy_code,
            review_mode=ReviewMode.CONTEXTUAL_PRODUCTION,
            due_at=initial_due(moment),
            stability=0.0,
            difficulty=0.6,
            scheduler_version=SCHEDULER_VERSION,
        )
        session.add(item)
        created.append(item)

    session.flush()
    return created


def mark_resolved(
    session: Session, user_id: uuid.UUID, taxonomy_code: str, *, now: datetime | None = None
) -> ErrorPattern | None:
    """Stop scheduling an error the learner no longer makes.

    Progress in this product is *fewer repeated errors*, so a resolved pattern
    is a result worth recording, not a row to delete.
    """
    pattern = session.execute(
        select(ErrorPattern).where(
            ErrorPattern.user_id == user_id, ErrorPattern.taxonomy_code == taxonomy_code
        )
    ).scalar_one_or_none()
    if pattern is None:
        return None

    pattern.status = ErrorStatus.RESOLVED
    pattern.current_priority = 0.0
    del now

    for item in session.execute(
        select(ReviewQueueItem).where(
            ReviewQueueItem.user_id == user_id,
            ReviewQueueItem.memory_object_type == MemoryObjectType.ERROR_PATTERN,
            ReviewQueueItem.memory_object_key == taxonomy_code,
        )
    ).scalars():
        session.delete(item)

    session.flush()
    return pattern


def active_errors(session: Session, user_id: uuid.UUID) -> list[ErrorPattern]:
    """Active patterns, most important first."""
    patterns = list(
        session.execute(
            select(ErrorPattern).where(
                ErrorPattern.user_id == user_id,
                ErrorPattern.status != ErrorStatus.RESOLVED,
            )
        )
        .scalars()
        .all()
    )
    return sorted(patterns, key=lambda p: (p.current_priority, p.occurrence_count), reverse=True)
