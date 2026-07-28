"""A learner's own past work, and the feedback it was given.

Everything a learner has written, said, or answered is stored in `attempts`
and, until now, was unreachable. They saw their feedback once, on the screen
that produced it, and then it was gone. That is a strange thing for a product
built on the claim that a profile is made of evidence the learner actually
produced: the evidence existed and they could not look at it.

What is returned, and what is deliberately not
----------------------------------------------
**The feedback as it was recorded, not as it would be computed now.**
Re-deriving it would give a different answer whenever the curriculum version,
the checks, or the evaluator has changed since — and the learner would see a
verdict nobody ever gave them. So the stored response is returned verbatim,
with the timestamp and the evaluator that produced it, and the client can say
when it was recorded.

**No re-scoring, and no new evidence.** Reading your own history is not an
attempt, and a system that recorded it as one would be counting rereading as
practice.

**Reflections appear and carry no feedback.** They are attempts, so hiding
them would leave a gap in the learner's own record with no explanation; but
nothing judged them, and the shape says so rather than showing an empty
score.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models.learning import Attempt

#: How many attempts one page returns. A learner with a year of history does
#: not want all of it at once, and neither does the browser.
PAGE_SIZE = 25

#: Activity types whose stored response holds nothing that was judged.
UNJUDGED_TYPES = frozenset({"reflection"})


class AttemptNotFoundError(AppError):
    """Also raised for another learner's attempt.

    Indistinguishable on purpose: which attempts exist is not something one
    learner may learn about another, and a different status code for
    "someone else's" would leak exactly that.
    """

    code = "attempt_not_found"
    status_code_default = 404

    def __init__(self) -> None:
        super().__init__("No such attempt.")


@dataclass(frozen=True)
class HistoryEntry:
    """One past attempt, reduced to what a list needs."""

    attempt_id: uuid.UUID
    activity_key: str
    activity_type: str
    submitted_at: datetime
    #: What the learner produced, shortened for a list. The full text is on
    #: the detail endpoint.
    summary: str
    score: float | None
    #: False for reflection, and for anything else nothing assessed.
    was_judged: bool


@dataclass(frozen=True)
class AttemptFeedback:
    """One attempt in full, exactly as it was recorded."""

    attempt_id: uuid.UUID
    activity_key: str
    activity_type: str
    submitted_at: datetime
    #: Which evaluator produced this, at the time. Surfaced because a learner
    #: comparing two pieces of feedback deserves to know whether the same
    #: thing judged them. `None` where nothing did — a reflection, for
    #: instance — which is a different fact from "an evaluator we cannot
    #: name", and the client should be able to tell them apart.
    evaluator_id: str | None
    response: dict[str, object]
    was_judged: bool

    @property
    def is_stale(self) -> bool:
        """Whether anything here might be judged differently today.

        Always true for judged work, and it is not hedging. The checks, the
        curriculum version and the evaluator can all have moved since, so
        this is a record of what was said rather than a claim about what
        would be said now.
        """
        return self.was_judged


def _summarise(attempt: Attempt) -> str:
    """One line naming what the learner produced.

    Prefers their own words over a score: a list of "0.75" tells someone
    nothing about which piece of work they are looking at.
    """
    response = attempt.response
    for field in ("text", "note", "transcript", "raw"):
        value = response.get(field)
        if isinstance(value, str) and value.strip():
            flat = " ".join(value.split())
            return flat if len(flat) <= 120 else flat[:117] + "..."

    answers = response.get("answers")
    if isinstance(answers, dict) and answers:
        return f"{len(answers)} answers"
    return attempt.activity_key


def _submitted(attempt: Attempt) -> datetime:
    """The query filters these out, so this only narrows the type."""
    assert attempt.submitted_at is not None
    return attempt.submitted_at


def _score_of(attempt: Attempt) -> float | None:
    value = attempt.response.get("score")
    return float(value) if isinstance(value, int | float) else None


def _judged(attempt: Attempt) -> bool:
    if attempt.activity_type in UNJUDGED_TYPES:
        return False
    return attempt.response.get("scored") is not False


def recent(
    session: Session,
    user_id: uuid.UUID,
    *,
    limit: int = PAGE_SIZE,
    before: datetime | None = None,
) -> list[HistoryEntry]:
    """A learner's attempts, newest first.

    Keyset pagination on `submitted_at` rather than an offset: a learner
    scrolling back through their history while new attempts arrive would
    otherwise see items shift between pages.
    """
    # Only finished attempts. `submitted_at` is nullable because a row can
    # exist before the learner has submitted anything, and an unfinished
    # attempt in a history list would be a piece of work they never handed
    # in — with no feedback to show and no way to act on it.
    query = select(Attempt).where(Attempt.user_id == user_id, Attempt.submitted_at.is_not(None))
    if before is not None:
        query = query.where(Attempt.submitted_at < before)
    query = query.order_by(Attempt.submitted_at.desc()).limit(max(1, min(limit, PAGE_SIZE)))

    return [
        HistoryEntry(
            attempt_id=attempt.id,
            activity_key=attempt.activity_key,
            activity_type=attempt.activity_type,
            submitted_at=_submitted(attempt),
            summary=_summarise(attempt),
            score=_score_of(attempt),
            was_judged=_judged(attempt),
        )
        for attempt in session.execute(query).scalars()
    ]


def feedback(session: Session, user_id: uuid.UUID, attempt_id: uuid.UUID) -> AttemptFeedback:
    """One attempt in full, as it was recorded.

    Raises:
        AttemptNotFoundError: no such attempt, or it belongs to someone else.
    """
    attempt = session.execute(
        select(Attempt).where(
            Attempt.id == attempt_id,
            Attempt.user_id == user_id,
            Attempt.submitted_at.is_not(None),
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise AttemptNotFoundError()
    assert attempt.submitted_at is not None  # narrowed by the query above

    return AttemptFeedback(
        attempt_id=attempt.id,
        activity_key=attempt.activity_key,
        activity_type=attempt.activity_type,
        submitted_at=attempt.submitted_at,
        evaluator_id=attempt.evaluator_id,
        response=dict(attempt.response),
        was_judged=_judged(attempt),
    )


__all__ = [
    "PAGE_SIZE",
    "AttemptFeedback",
    "AttemptNotFoundError",
    "HistoryEntry",
    "feedback",
    "recent",
]
