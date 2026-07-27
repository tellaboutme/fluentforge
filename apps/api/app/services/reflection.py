"""Reflection: the last plan kind with nothing behind it.

`docs/LEARNING_SCIENCE.md` puts metacognition in the loop, and every session
template has reserved four minutes for it since Milestone 1. The slot has
rendered unlinked ever since, because nothing existed to open.

What reflection is here
-----------------------
Not an exercise. The learner is shown what the system has actually noticed
about them — the errors that keep recurring, the work it could not judge, how
long since each skill was last observed — and asked what they make of it.

The material is the point. A reflection prompt with nothing concrete in it
("how do you feel your learning is going?") produces nothing worth reading,
and a learner who has been asked that twice stops answering.

What it deliberately does not do
--------------------------------
**It records no evidence, of any kind.** A learner who writes "I need to work
on the past simple" has not demonstrated the past simple, and a system that
counted the sentence would be recording an intention as an achievement. The
attempt is stored because it is history the learner may want to reread; it
touches no skill state.

**It is not scored, checked, or corrected.** This is the one place in the
product where the learner writes and nothing at all judges it. Running the
writing checks over a reflection would teach them to write reflections that
pass checks, which is the opposite of the point.

**It has no minimum length.** "Nothing new this week" is a legitimate
reflection and sometimes the true one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.types import utcnow
from ..learning import taxonomy
from ..models.curriculum import SkillNode
from ..models.enums import SessionStatus
from ..models.learning import Attempt, LearningSession, SkillState
from .errors_log import active_errors, priority_for

REFLECTION_CONTEXT = "reflection"
ACTIVITY_TYPE = "reflection"

#: How many recurring errors to put in front of the learner.
#:
#: Three, for the same reason the rubric evaluator returns at most three
#: corrections: a list of everything wrong is a list nobody acts on.
MAX_ERRORS = 3

#: How many unjudged pieces of work to mention.
MAX_UNJUDGED = 3

#: Days after which a skill counts as unobserved for this purpose. Shorter
#: than the mastery model's confidence half-life: the question here is "what
#: have you not touched lately", not "what has the model stopped believing".
STALE_DAYS = 14


@dataclass(frozen=True)
class RecurringError:
    code: str
    label: str
    description: str
    occurrences: int
    blocks_meaning: bool


@dataclass(frozen=True)
class ReflectionPrompt:
    """What the system has noticed, offered back to the learner."""

    recurring_errors: tuple[RecurringError, ...]
    #: Skills with evidence that has not been refreshed lately.
    untouched_skills: tuple[str, ...]
    #: How many pieces of the learner's own writing or speech nothing has
    #: judged. Named because it is a limit of the product, and a learner
    #: reflecting on their progress deserves to know the system's own blind
    #: spot rather than assuming silence meant approval.
    unjudged_count: int
    #: The learner's previous note, if there is one. Reflection that never
    #: refers back is a diary nobody rereads.
    previous_note: str | None


def build_prompt(session: Session, user_id: uuid.UUID) -> ReflectionPrompt:
    """Gather what is worth reflecting on. Never invents material."""
    patterns = sorted(
        active_errors(session, user_id),
        key=lambda pattern: (-priority_for(pattern), pattern.taxonomy_code),
    )[:MAX_ERRORS]

    errors = tuple(
        RecurringError(
            code=pattern.taxonomy_code,
            label=taxonomy.label_for(pattern.taxonomy_code),
            description=pattern.canonical_description,
            occurrences=pattern.occurrence_count,
            blocks_meaning=pattern.blocks_meaning,
        )
        for pattern in patterns
    )

    now = utcnow()
    stale: list[str] = []
    for state in session.execute(select(SkillState).where(SkillState.user_id == user_id)).scalars():
        if state.last_observed_at is None:
            continue
        if (now - state.last_observed_at).days < STALE_DAYS:
            continue
        node = session.get(SkillNode, state.skill_node_id)
        if node is not None:
            stale.append(node.key)

    unjudged = sum(
        1
        for attempt in session.execute(select(Attempt).where(Attempt.user_id == user_id)).scalars()
        if attempt.response.get("provisional") is True
    )

    return ReflectionPrompt(
        recurring_errors=errors,
        untouched_skills=tuple(sorted(stale)),
        unjudged_count=unjudged,
        previous_note=_previous_note(session, user_id),
    )


def _previous_note(session: Session, user_id: uuid.UUID) -> str | None:
    rows = session.execute(
        select(Attempt)
        .where(Attempt.user_id == user_id, Attempt.activity_type == ACTIVITY_TYPE)
        .order_by(Attempt.submitted_at.desc())
    ).scalars()
    previous = next(iter(rows), None)
    if previous is None:
        return None
    note = previous.response.get("note")
    return note if isinstance(note, str) and note.strip() else None


def record(
    session: Session,
    user_id: uuid.UUID,
    *,
    note: str,
    duration_ms: int | None = None,
) -> Attempt:
    """Store a reflection.

    Nothing is scored and no evidence is written. The attempt exists because
    it is the learner's own record, not because it proves anything: a stated
    intention is not a demonstrated skill, and counting it would be recording
    the intention as the achievement.
    """
    learning_session = _open_session(session, user_id)

    # Reflections reuse one open session and one key, so the attempt number
    # has to advance or the second one violates
    # `(session_id, activity_key, attempt_number)`. It is a counter here and
    # nothing more: unlike everywhere else in the product, a repeat is not
    # weaker evidence, because there is no evidence.
    written = len(
        session.execute(
            select(Attempt.id).where(
                Attempt.session_id == learning_session.id,
                Attempt.activity_key == "reflect:daily",
            )
        )
        .scalars()
        .all()
    )

    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key="reflect:daily",
        activity_type=ACTIVITY_TYPE,
        attempt_number=written + 1,
        response={
            "note": note.strip(),
            # Explicit rather than absent. A future reader of this row should
            # not have to infer from a missing field that nothing judged it.
            "scored": False,
            "evidence_recorded": False,
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id="none",
    )
    session.add(attempt)
    session.flush()
    return attempt


def _open_session(session: Session, user_id: uuid.UUID) -> LearningSession:
    existing = session.execute(
        select(LearningSession)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.status == SessionStatus.IN_PROGRESS,
        )
        .order_by(LearningSession.started_at.desc())
    ).scalars()
    for candidate in existing:
        if candidate.context.get("kind") == REFLECTION_CONTEXT:
            return candidate

    learning_session = LearningSession(
        user_id=user_id,
        status=SessionStatus.IN_PROGRESS,
        context={"kind": REFLECTION_CONTEXT},
    )
    session.add(learning_session)
    session.flush()
    return learning_session


def history(session: Session, user_id: uuid.UUID, *, limit: int = 10) -> list[Attempt]:
    """Past reflections, newest first."""
    rows = session.execute(
        select(Attempt)
        .where(Attempt.user_id == user_id, Attempt.activity_type == ACTIVITY_TYPE)
        .order_by(Attempt.submitted_at.desc())
        .limit(limit)
    ).scalars()
    return list(rows)


__all__ = [
    "ACTIVITY_TYPE",
    "MAX_ERRORS",
    "REFLECTION_CONTEXT",
    "RecurringError",
    "ReflectionPrompt",
    "build_prompt",
    "history",
    "record",
]
