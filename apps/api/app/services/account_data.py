"""Everything the product holds about one learner, and getting rid of it.

`docs/PRIVACY_SAFETY.md` lists "Provide export and deletion" under data
minimisation. Nothing implemented it. That is a worse gap than an ordinary
missing feature, because the product stores *what a person wrote and said* --
every piece of writing, every transcript of their own speech, every mistake it
noticed -- and a learner had no way to take that with them or make it stop
existing.

Two operations, and each one turns on a single decision.

Export: the rows, not a report
------------------------------
The export is the stored data, not a rendering of it. `response` on an attempt
comes back exactly as written, the same refusal `GET /attempts/{id}/feedback`
makes: a summary would be the product deciding which parts of a person's own
work they are allowed to have.

It carries a `not_included` list, which is the honest part. An export that
silently omits something is worse than no export at all, because it invites
the reader to conclude that what they received is everything.

Deletion: real, and it needs the password
-----------------------------------------
Not deactivation, not a `deleted_at` flag with the rows still sitting there.
Every table that references a learner declares `ondelete="CASCADE"`, and this
relies on that rather than reimplementing it -- a hand-written cascade drifts
out of step with the schema, and the failure mode is a table quietly left
behind.

The password is required again because a session token is not enough
authorisation to destroy a year of somebody's work. A leaked token should cost
a learner their privacy, which is bad; it should not additionally cost them
everything they have done.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models.identity import User
from ..models.learning import Attempt, ErrorPattern, EvidenceEvent, LearningSession, SkillState
from ..models.planning import Plan, PlanItem, ReviewQueueItem
from ..security.passwords import verify_password

#: Bumped when the shape changes, so a learner comparing two exports taken a
#: year apart can tell whether a missing field was removed or never collected.
EXPORT_VERSION = "1"


class NotConfirmedError(AppError):
    """The confirmation phrase was not typed correctly.

    A distinct error from a wrong password on purpose. Telling someone their
    password was wrong when they mistyped a confirmation sends them to reset
    a password that was fine, and hides the actual problem.
    """

    code = "not_confirmed"
    status_code_default = 422

    def __init__(self, phrase: str) -> None:
        super().__init__(f"Type {phrase!r} exactly to confirm.")


class WrongPasswordError(AppError):
    """The password given to authorise deletion did not match.

    401 rather than 403: the credential was wrong, not the permission. The
    message never says whether the account exists, because the caller is
    already authenticated as it.
    """

    code = "wrong_password"
    status_code_default = 401

    def __init__(self) -> None:
        super().__init__("That password is not right.")


def export_account(session: Session, user: User) -> dict[str, Any]:
    """Everything stored about this learner, as data rather than as a report.

    Assembled in memory rather than streamed. One learner's history is small --
    a year of daily practice is a few thousand rows -- and a streaming export
    would need a job, a place to put the file, and a link that expires, all of
    which are ways for the export to fail quietly.
    """
    profile = user.profile

    return {
        "export_version": EXPORT_VERSION,
        "exported_at": _now().isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "status": user.status.value,
            "created_at": _iso(user.created_at),
        },
        "profile": (
            {
                "display_name": profile.display_name,
                "explanation_language": profile.explanation_language,
                "timezone": profile.timezone,
                "daily_minutes": profile.daily_minutes,
                "target_level": profile.target_level.value,
                "track_key": profile.track_key,
                "goals": profile.goals,
                "interests": profile.interests,
                "accessibility_preferences": profile.accessibility_preferences,
                "privacy_preferences": profile.privacy_preferences,
            }
            if profile
            else None
        ),
        "sessions": [
            {
                "id": str(row.id),
                "plan_id": str(row.plan_id) if row.plan_id else None,
                "status": row.status.value,
                "started_at": _iso(row.started_at),
                "ended_at": _iso(row.ended_at),
                "context": row.context,
            }
            for row in _rows(session, LearningSession, user.id, LearningSession.started_at)
        ],
        # The learner's own words. Verbatim, including the feedback exactly as
        # it was recorded -- never recomputed, for the same reason the history
        # endpoint refuses to recompute it.
        "attempts": [
            {
                "id": str(row.id),
                "session_id": str(row.session_id),
                "activity_key": row.activity_key,
                "activity_type": row.activity_type,
                "attempt_number": row.attempt_number,
                "response": row.response,
                "submitted_at": _iso(row.submitted_at),
                "duration_ms": row.duration_ms,
                "hints_used": row.hints_used,
                "scaffolding_level": row.scaffolding_level,
                "evaluator_id": row.evaluator_id,
            }
            for row in _rows(session, Attempt, user.id, Attempt.submitted_at)
        ],
        # Included in full because this is what the profile is *made of*. A
        # learner who disagrees with an estimate can only check the working if
        # they can see the observations behind it.
        "evidence": [
            {
                "id": str(row.id),
                "skill_node_id": str(row.skill_node_id),
                "attempt_id": str(row.attempt_id) if row.attempt_id else None,
                "evidence_type": row.evidence_type.value,
                "score": row.score,
                "weight": row.weight,
                "difficulty": row.difficulty,
                "confidence": row.confidence,
                "independence": row.independence,
                "novelty": row.novelty,
                "context_key": row.context_key,
                "occurred_at": _iso(row.occurred_at),
                "metadata": row.metadata_json,
            }
            for row in _rows(session, EvidenceEvent, user.id, EvidenceEvent.occurred_at)
        ],
        "skill_states": [
            {
                "skill_node_id": str(row.skill_node_id),
                "mastery_probability": row.mastery_probability,
                # As stored. The API decays this on read; the raw value is
                # what the model actually wrote, and both are true statements
                # about different moments.
                "confidence_at_last_update": row.confidence,
                "stability": row.stability,
                "distinct_contexts": row.distinct_contexts,
                "evidence_count": row.evidence_count,
                "last_observed_at": _iso(row.last_observed_at),
                "model_version": row.model_version,
            }
            for row in _rows(session, SkillState, user.id, SkillState.skill_node_id)
        ],
        "error_patterns": [
            {
                "id": str(row.id),
                "taxonomy_code": row.taxonomy_code,
                "description": row.canonical_description,
                "occurrences": row.occurrence_count,
                "first_seen_at": _iso(row.first_seen_at),
                "last_seen_at": _iso(row.last_seen_at),
                "blocks_meaning": row.blocks_meaning,
                "status": row.status.value,
                "examples": row.examples,
            }
            for row in _rows(session, ErrorPattern, user.id, ErrorPattern.first_seen_at)
        ],
        "plans": [
            {
                "id": str(row.id),
                "plan_date": row.plan_date.isoformat(),
                "requested_minutes": row.requested_minutes,
                "status": row.status.value,
                "engine_version": row.engine_version,
                "items": [
                    {
                        "sequence": item.sequence,
                        "activity_key": item.activity_key,
                        "activity_type": item.activity_type,
                        "estimated_minutes": item.estimated_minutes,
                        "reason_codes": item.reason_codes,
                        # The full working behind every plan item, including
                        # components that scored zero. The learner is entitled
                        # to the reasoning, not just the outcome.
                        "priority_components": item.priority_components,
                    }
                    for item in sorted(_plan_items(session, row.id), key=lambda item: item.sequence)
                ],
            }
            for row in _rows(session, Plan, user.id, Plan.plan_date)
        ],
        "review_queue": [
            {
                "memory_object_type": row.memory_object_type.value,
                "memory_object_key": row.memory_object_key,
                "review_mode": row.review_mode.value,
                "due_at": _iso(row.due_at),
                "stability": row.stability,
                "difficulty": row.difficulty,
                "lapses": row.lapses,
                "last_reviewed_at": _iso(row.last_reviewed_at),
                "scheduler_version": row.scheduler_version,
            }
            for row in _rows(session, ReviewQueueItem, user.id, ReviewQueueItem.due_at)
        ],
        "not_included": _not_included(),
    }


def _not_included() -> list[str]:
    """What this export does not contain, and why.

    An export that silently omits something is worse than none at all: it
    invites the reader to conclude that what they got is everything.
    """
    return [
        "No audio. Speech is transcribed in your browser and only the text is "
        "ever sent, so there is no recording of your voice to give you.",
        "No password. It is stored only as a hash, which cannot be turned "
        "back into what you typed.",
        "No curriculum. The texts, tasks and word lists are the same for "
        "everyone and are not yours; they are versioned in the product itself.",
        "No analytics or tracking history, because none is collected.",
    ]


def delete_account(session: Session, user: User, *, password: str) -> None:
    """Delete the account and everything attached to it.

    Real deletion. Not a flag, not an anonymisation pass that leaves the rows
    in place -- the learner asked for the data to stop existing, and a
    `deleted_at` column would mean it does not.

    The cascade comes from the schema: every table referencing a learner
    declares `ondelete="CASCADE"`. Writing the deletions out by hand here
    would drift from the schema the first time a table was added, and the
    failure mode is a table quietly left behind holding somebody's writing.

    Raises:
        WrongPasswordError: the password did not match.
    """
    if not verify_password(password, user.password_hash):
        raise WrongPasswordError()

    session.delete(user)
    session.flush()


def _rows(session: Session, model: Any, user_id: uuid.UUID, order: Any) -> list[Any]:
    return list(
        session.execute(select(model).where(model.user_id == user_id).order_by(order))
        .scalars()
        .all()
    )


def _plan_items(session: Session, plan_id: uuid.UUID) -> list[PlanItem]:
    return list(
        session.execute(select(PlanItem).where(PlanItem.plan_id == plan_id)).scalars().all()
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    from ..db.types import utcnow

    return utcnow()


__all__ = [
    "EXPORT_VERSION",
    "NotConfirmedError",
    "WrongPasswordError",
    "delete_account",
    "export_account",
]
