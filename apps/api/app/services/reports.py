"""Disagreeing with a verdict.

`docs/PRIVACY_SAFETY.md` asks the product to "permit reporting bad feedback"
and nothing did. `docs/AI_TUTOR_BEHAVIOR.md` says AI judgement is an
accelerator rather than an authority -- which is a claim about how the product
behaves, and it was not true of anything: a learner who was marked wrong by a
countable check that had misread them, or by a model that hallucinated a
grammar error, could see the verdict, could see it feeding their profile, and
had no way to say it was wrong.

What a report does
------------------
Not nothing, and not what a learner might hope. A report **lowers the
confidence of the evidence that attempt produced**, and leaves the score
alone.

That asymmetry is the whole design. Confidence is how sure the model is;
`mastery_probability` is what it believes. Disputing a judgement is a reason to
be less sure -- the observation might be measuring the checker rather than the
learner -- and it is not evidence that the learner did better. So a report
widens the uncertainty and never raises the estimate.

Which also makes it ungameable in the direction that matters. Someone who
disputes every low score does not inflate their profile; they make it say "we
do not really know" about the skills they disputed, which is both true and
exactly what they have argued for.

What it must not do
-------------------
**Not delete anything.** The attempt, the response and the recorded feedback
stay exactly as they were. A learner returning to `/history` must find what
they were actually told, not a gap where a disagreement used to be.

**Not be repeatable.** One report per attempt. Reporting the same thing five
times is the same complaint, and letting it compound would turn the confidence
reduction into a way to zero out an observation entirely.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.types import utcnow
from ..errors import AppError
from ..models.learning import Attempt, EvidenceEvent, FeedbackReport
from .evidence import recompute_skill_state

#: What a learner can say is wrong. A closed set, because free text alone
#: cannot be counted and a report nobody can count is a report nobody acts on.
REASONS: tuple[str, ...] = (
    # The verdict itself: marked wrong when right, or the reverse.
    "wrong_verdict",
    # The verdict may be right; the explanation did not explain.
    "unclear_feedback",
    # The task, text or clip is the problem, not the judgement of it.
    "bad_content",
    "other",
)

#: What the disputed evidence's confidence is multiplied by.
#:
#: Halved rather than zeroed. A disagreement is a reason to be less sure, not
#: proof that the observation was worthless -- and a learner is not a neutral
#: judge of whether they were marked correctly, which is a fact about
#: everybody and no criticism of them. Zeroing would also make disputing
#: strictly better than not, for anyone willing to dispute everything.
DISPUTED_CONFIDENCE_FACTOR = 0.5


class UnknownReasonError(AppError):
    code = "unknown_reason"
    status_code_default = 422

    def __init__(self, reason: str) -> None:
        super().__init__(f"{reason!r} is not one of {', '.join(REASONS)}.")


class AlreadyReportedError(AppError):
    """A second report on the same attempt.

    409 rather than silently succeeding: the learner should know their first
    report is already recorded, and a client that got a cheerful 200 would
    have no way to tell them.
    """

    code = "already_reported"
    status_code_default = 409

    def __init__(self) -> None:
        super().__init__("You have already reported this one.")


@dataclass(frozen=True)
class ReportOutcome:
    """What the report changed, said plainly enough to show the learner."""

    report_id: uuid.UUID
    reported_at: datetime
    #: How many observations became less certain. Zero for an activity that
    #: produced none -- a reflection, or an attempt whose skill is not in the
    #: active curriculum.
    evidence_softened: int
    #: What the learner should not expect. Always non-empty.
    notes: list[str]


def report_attempt(
    session: Session,
    user_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    reason: str,
    note: str | None = None,
) -> ReportOutcome:
    """Record a disagreement and soften the evidence it produced.

    Raises:
        AttemptNotFoundError: no such attempt, or it belongs to someone else.
        UnknownReasonError: the reason is not in the closed set.
        AlreadyReportedError: this attempt has been reported already.
    """
    from .history import AttemptNotFoundError

    if reason not in REASONS:
        raise UnknownReasonError(reason)

    attempt = session.execute(
        select(Attempt).where(Attempt.id == attempt_id, Attempt.user_id == user_id)
    ).scalar_one_or_none()
    if attempt is None:
        raise AttemptNotFoundError()

    existing = session.execute(
        select(FeedbackReport).where(FeedbackReport.attempt_id == attempt_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise AlreadyReportedError()

    report = FeedbackReport(
        user_id=user_id,
        attempt_id=attempt_id,
        reason=reason,
        # Trimmed and bounded by the schema. Kept verbatim otherwise: this is
        # the learner explaining themselves, and paraphrasing it would defeat
        # the point of asking.
        note=(note or "").strip() or None,
        evaluator_id=attempt.evaluator_id,
    )
    session.add(report)

    softened = _soften_evidence(session, user_id, attempt_id)
    session.flush()

    return ReportOutcome(
        report_id=report.id,
        reported_at=report.created_at or utcnow(),
        evidence_softened=softened,
        notes=_notes(softened),
    )


def _soften_evidence(session: Session, user_id: uuid.UUID, attempt_id: uuid.UUID) -> int:
    """Lower the confidence of everything this attempt evidenced.

    The score is untouched. Confidence is how sure the model is and
    `mastery_probability` is what it believes; a disagreement is a reason for
    the first and not the second, so this can only widen the uncertainty and
    never raise the estimate.

    The original is recorded so the change is auditable and reversible -- and
    so that a second pass could not compound it even if one somehow happened.
    """
    events = list(
        session.execute(
            select(EvidenceEvent).where(
                EvidenceEvent.attempt_id == attempt_id,
                EvidenceEvent.user_id == user_id,
            )
        ).scalars()
    )

    touched: set[uuid.UUID] = set()
    for event in events:
        metadata = dict(event.metadata_json)
        if metadata.get("disputed"):
            continue
        metadata["disputed"] = True
        metadata["confidence_before_dispute"] = event.confidence
        event.metadata_json = metadata
        event.confidence = round(event.confidence * DISPUTED_CONFIDENCE_FACTOR, 6)
        touched.add(event.skill_node_id)

    session.flush()
    for skill_node_id in touched:
        recompute_skill_state(session, user_id=user_id, skill_node_id=skill_node_id)

    return len(events)


def _notes(softened: int) -> list[str]:
    """What the learner should and should not expect from having reported.

    Always non-empty. A report that said only "thanks" would let someone
    believe their score had been overturned, and finding out otherwise later
    is worse than being told now.
    """
    notes = [
        "Your score has not changed, and neither has the feedback you were "
        "given. What changed is how sure we are: a judgement you disagree "
        "with is a weaker basis for an estimate about you.",
    ]

    if softened:
        notes.append(
            "This will show up as lower confidence on the skills involved, "
            "not as a higher level. Disagreeing tells us we might be wrong; "
            "it cannot tell us you did better."
        )
    else:
        notes.append(
            "Nothing about your profile rested on this one, so there was "
            "nothing to soften. The report is still recorded."
        )

    return notes


def reports_for(session: Session, user_id: uuid.UUID) -> list[FeedbackReport]:
    """Everything this learner has reported. Included in their data export."""
    return list(
        session.execute(
            select(FeedbackReport)
            .where(FeedbackReport.user_id == user_id)
            .order_by(FeedbackReport.created_at)
        )
        .scalars()
        .all()
    )


__all__ = [
    "DISPUTED_CONFIDENCE_FACTOR",
    "REASONS",
    "AlreadyReportedError",
    "ReportOutcome",
    "UnknownReasonError",
    "report_attempt",
    "reports_for",
]
