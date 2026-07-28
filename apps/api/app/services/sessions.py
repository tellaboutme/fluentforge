"""A sitting: the unit of work a learner actually sits down to do.

`POST /sessions` and `POST /sessions/{id}/complete` have been in the contract
since the beginning and unimplemented, and the gap left two real problems.

**Sessions were started implicitly and never ended.** Every activity opened a
`LearningSession` keyed on its kind and reused any in-progress one it found,
with no age check at all. A learner's "writing_lab" session from March was
still collecting attempts in July, `ended_at` was null on every row in the
table, and `started_at` meant nothing. Anything that ever wants to ask "what
did you do in one sitting?" was answering over a bucket months deep.

**Finishing had no shape.** A learner could work through today's plan and
there was no moment where the product said what had just happened. That
absence is not neutral: the one place a system is most tempted to invent a
number is the end of a session, and having no ending at all meant the question
was never faced.

What the summary says, and what it refuses to say
-------------------------------------------------
**It reports evidence, not improvement.** No mastery delta, no "you improved
by 4%". `docs/ADAPTIVE_ENGINE.md` forbids an opaque score, and a
sitting-level improvement figure is the most seductive one in the product:
derived from a handful of attempts, presented as if measured, and impossible
to argue with. What each skill gets instead is the count of evidence recorded
now and the number of distinct contexts it now stands on — the quantity the
mastery model actually gates on, and the one a learner can act on.

**It does not claim time on task.** `open_minutes` is how long the sitting was
open, and it is named that way because someone who started a session and made
lunch did not study for forty minutes. This product does not measure time on
task and nothing here should be rendered as if it did.

**One sitting proves nothing on its own**, and `notes` always says so. It is
the same refusal as `CLAUDE.md`'s invariant that recent repeated attempts on
one item cannot prove generalised mastery, applied at the point where it is
least welcome.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..curriculum.loader import active_curriculum_version
from ..db.types import utcnow
from ..errors import AppError, CurriculumNotLoadedError, SessionNotFoundError
from ..learning.mastery import MasteryThresholds, classify_status
from ..models.curriculum import SkillNode
from ..models.enums import SessionStatus
from ..models.learning import Attempt, EvidenceEvent, LearningSession, SkillState
from ..models.planning import Plan, PlanItem

#: `context["kind"]` of a sitting the learner opened deliberately, as opposed
#: to the per-activity sessions opened on their behalf.
SITTING_KIND = "sitting"


class SessionAlreadyEndedError(AppError):
    """Completing an abandoned sitting.

    A sitting is abandoned because the learner walked away from it, and
    completing it afterwards would record that they finished something they
    did not. Distinct from the idempotent case: completing an already
    *completed* sitting returns the original summary, unchanged.
    """

    code = "session_already_ended"
    status_code_default = 409

    def __init__(self) -> None:
        super().__init__("That sitting was abandoned and cannot be completed.")


@dataclass(frozen=True)
class ActivityDone:
    """One activity finished inside a sitting."""

    activity_key: str
    activity_type: str
    submitted_at: datetime
    score: float | None
    #: False for reflection and anything else nothing assessed. A sitting
    #: summary that scored reflections would be judging the one activity
    #: deliberately left unjudged.
    was_judged: bool
    #: Whether this was on today's plan. A learner who worked on something
    #: else did not fail to follow the plan; the plan is a suggestion.
    on_plan: bool


@dataclass(frozen=True)
class SkillTouched:
    """A skill that received evidence during this sitting.

    `distinct_contexts` is the total after this sitting, not the number added,
    because the total is what the mastery model gates on. `needs` puts that
    into words rather than making the learner reverse-engineer a threshold.
    """

    key: str
    title: str
    evidence_recorded: int
    distinct_contexts: int
    status: str
    #: What would move this skill on, or `None` when nothing is outstanding.
    #: Never a promise about when.
    needs: str | None


@dataclass(frozen=True)
class SessionSummary:
    """What happened in one sitting. No claim about what it proved."""

    session_id: uuid.UUID
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None
    #: How long the sitting was open. Not time on task — see the module
    #: docstring. Clients must label it as elapsed time or omit it.
    open_minutes: int
    plan_id: uuid.UUID | None
    activities: list[ActivityDone]
    skills: list[SkillTouched]
    #: Plan coverage, both zero when the sitting is not bound to a plan.
    plan_items_done: int
    plan_items_total: int
    #: Always non-empty. Clients must surface it.
    notes: list[str]


@dataclass(frozen=True)
class Started:
    """The sitting, and whether it already existed.

    `resumed` is returned rather than left to the caller to infer, because
    every way of inferring it is wrong: an empty sitting can be one just
    created or one opened an hour ago and abandoned mid-thought, and telling
    the second learner "session started" is a small lie about their own day.
    """

    sitting: LearningSession
    resumed: bool


def start(
    session: Session,
    user_id: uuid.UUID,
    *,
    plan_id: uuid.UUID | None = None,
) -> Started:
    """Begin a sitting, or return the one already open today.

    Idempotent within a day on purpose: a learner who reloads the page, or
    whose client retries, gets the sitting they are already in rather than a
    second one that splits their work in half.

    Binding to a plan is a lookup, never a generation. Sitting down should not
    manufacture a plan for a day the learner never planned — that would put
    rows in `plans` describing intentions nobody had.
    """
    _abandon_stale(session, user_id)

    today = utcnow().date()
    for candidate in session.execute(
        select(LearningSession)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.status == SessionStatus.IN_PROGRESS,
        )
        .order_by(LearningSession.started_at.desc())
    ).scalars():
        if candidate.context.get("kind") == SITTING_KIND and candidate.started_at.date() == today:
            return Started(sitting=candidate, resumed=True)

    plan = _plan_for(session, user_id, plan_id)
    sitting = LearningSession(
        user_id=user_id,
        plan_id=plan.id if plan else None,
        status=SessionStatus.IN_PROGRESS,
        context={"kind": SITTING_KIND},
    )
    session.add(sitting)
    session.flush()
    return Started(sitting=sitting, resumed=False)


def current(session: Session, user_id: uuid.UUID) -> LearningSession | None:
    """Today's open sitting, if there is one.

    A read, so it starts nothing and abandons nothing. The client needs to
    know which control to show, and finding out by calling `start` would mean
    that merely opening the dashboard began a sitting — after which
    `open_minutes` would count the time the browser tab was left open on a
    page nobody was reading.
    """
    today = utcnow().date()
    for candidate in session.execute(
        select(LearningSession)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.status == SessionStatus.IN_PROGRESS,
        )
        .order_by(LearningSession.started_at.desc())
    ).scalars():
        if candidate.context.get("kind") == SITTING_KIND and candidate.started_at.date() == today:
            return candidate
    return None


def complete(session: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> SessionSummary:
    """End a sitting and describe it.

    Completing an already-completed sitting returns the original summary with
    the original `ended_at`: the write is retryable, and a retry that moved
    the end time would rewrite history to match a network hiccup.

    Raises:
        SessionNotFoundError: no such sitting, or it belongs to someone else.
        SessionAlreadyEndedError: the sitting was abandoned.
    """
    sitting = session.execute(
        select(LearningSession).where(
            LearningSession.id == session_id,
            LearningSession.user_id == user_id,
        )
    ).scalar_one_or_none()
    if sitting is None:
        raise SessionNotFoundError()
    if sitting.status is SessionStatus.ABANDONED:
        raise SessionAlreadyEndedError()

    if sitting.status is SessionStatus.IN_PROGRESS:
        sitting.status = SessionStatus.COMPLETED
        sitting.ended_at = utcnow()
        session.flush()

    return summarise(session, user_id, sitting)


def summarise(session: Session, user_id: uuid.UUID, sitting: LearningSession) -> SessionSummary:
    """Describe a sitting without changing it.

    Split out from `complete` so that reading a past sitting cannot end one,
    and so the summary is exercised independently of the state transition.
    """
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()
    thresholds = MasteryThresholds.from_metadata(version.metadata_json)

    attempts = list(
        session.execute(
            select(Attempt)
            .where(Attempt.session_id == sitting.id, Attempt.submitted_at.is_not(None))
            .order_by(Attempt.submitted_at)
        ).scalars()
    )

    planned = _planned_keys(session, sitting.plan_id)
    activities = [
        ActivityDone(
            activity_key=attempt.activity_key,
            activity_type=attempt.activity_type,
            submitted_at=_submitted(attempt),
            score=_score_of(attempt),
            was_judged=_judged(attempt),
            on_plan=attempt.activity_key in planned,
        )
        for attempt in attempts
    ]

    skills = _skills_touched(session, user_id, sitting, version.id, thresholds)
    done = len(planned & {activity.activity_key for activity in activities})

    return SessionSummary(
        session_id=sitting.id,
        status=sitting.status,
        started_at=sitting.started_at,
        ended_at=sitting.ended_at,
        open_minutes=_open_minutes(sitting),
        plan_id=sitting.plan_id,
        activities=activities,
        skills=skills,
        plan_items_done=done,
        plan_items_total=len(planned),
        notes=_notes(activities, skills, planned, done),
    )


# --- Pieces -----------------------------------------------------------------


def _abandon_stale(session: Session, user_id: uuid.UUID) -> None:
    """Close sessions left open on an earlier day.

    Sitting down today does not continue yesterday. Without this, the
    per-activity sessions opened by `services.activities` are reused
    indefinitely — the original defect this module exists to fix — and every
    sitting summary would report months of work as one afternoon.

    They become `abandoned` rather than `completed`: nobody finished them.
    """
    today = utcnow().date()
    for stale in session.execute(
        select(LearningSession).where(
            LearningSession.user_id == user_id,
            LearningSession.status == SessionStatus.IN_PROGRESS,
        )
    ).scalars():
        if stale.started_at.date() < today:
            stale.status = SessionStatus.ABANDONED
            stale.ended_at = stale.started_at
    session.flush()


def _plan_for(session: Session, user_id: uuid.UUID, plan_id: uuid.UUID | None) -> Plan | None:
    """The plan this sitting is against, if there is one.

    An explicit `plan_id` belonging to someone else resolves to `None` rather
    than raising: which plans exist is not something one learner may learn
    about another, and the sitting is perfectly valid unbound.
    """
    if plan_id is not None:
        return session.execute(
            select(Plan).where(Plan.id == plan_id, Plan.user_id == user_id)
        ).scalar_one_or_none()
    return session.execute(
        select(Plan).where(Plan.user_id == user_id, Plan.plan_date == utcnow().date())
    ).scalar_one_or_none()


def _planned_keys(session: Session, plan_id: uuid.UUID | None) -> set[str]:
    if plan_id is None:
        return set()
    return set(
        session.execute(select(PlanItem.activity_key).where(PlanItem.plan_id == plan_id))
        .scalars()
        .all()
    )


def _skills_touched(
    session: Session,
    user_id: uuid.UUID,
    sitting: LearningSession,
    version_id: uuid.UUID,
    thresholds: MasteryThresholds,
) -> list[SkillTouched]:
    """Skills that received evidence from attempts in this sitting.

    Joined through `attempts` because evidence carries no session of its own.
    Skills the learner merely read about are not here: being shown a rule is
    not evidence of using it.
    """
    counts: dict[uuid.UUID, int] = {}
    for skill_node_id in (
        session.execute(
            select(EvidenceEvent.skill_node_id)
            .join(Attempt, Attempt.id == EvidenceEvent.attempt_id)
            .where(Attempt.session_id == sitting.id, EvidenceEvent.user_id == user_id)
        )
        .scalars()
        .all()
    ):
        counts[skill_node_id] = counts.get(skill_node_id, 0) + 1

    if not counts:
        return []

    nodes = {
        node.id: node
        for node in session.execute(
            select(SkillNode).where(
                SkillNode.curriculum_version_id == version_id,
                SkillNode.id.in_(counts),
            )
        ).scalars()
    }
    states = {
        state.skill_node_id: state
        for state in session.execute(
            select(SkillState).where(
                SkillState.user_id == user_id,
                SkillState.skill_node_id.in_(counts),
            )
        ).scalars()
    }

    touched: list[SkillTouched] = []
    for node_id, recorded in counts.items():
        node = nodes.get(node_id)
        if node is None:
            # Evidence against a skill from an earlier curriculum version.
            # Naming a skill that no longer exists would be worse than
            # omitting it.
            continue
        state = states.get(node_id)
        contexts = state.distinct_contexts if state else 0
        status = classify_status(
            mastery_probability=state.mastery_probability if state else 0.0,
            confidence=state.confidence if state else 0.0,
            distinct_contexts=contexts,
            evidence_count=state.evidence_count if state else 0,
            thresholds=thresholds,
        )
        touched.append(
            SkillTouched(
                key=node.key,
                title=node.title,
                evidence_recorded=recorded,
                distinct_contexts=contexts,
                status=status,
                needs=_needs(contexts, thresholds),
            )
        )

    touched.sort(key=lambda skill: (-skill.evidence_recorded, skill.key))
    return touched


def _needs(distinct_contexts: int, thresholds: MasteryThresholds) -> str | None:
    """What is outstanding for this skill, in the model's own terms.

    Only breadth is reported. Probability and confidence are continuous and
    turning them into "you need 12% more" would be exactly the invented number
    this module refuses; how many different situations a skill has held up in
    is a count the learner can see the sense of.
    """
    missing = thresholds.minimum_distinct_contexts - distinct_contexts
    if missing <= 0:
        return None
    if missing == 1:
        return (
            "This has held up in one fewer situation than it needs. Meeting "
            "it somewhere different is what would tell us most."
        )
    return (
        f"This needs to hold up in {missing} more different situations before "
        f"it counts as more than a good day."
    )


def _open_minutes(sitting: LearningSession) -> int:
    end = sitting.ended_at or utcnow()
    return max(0, int((end - sitting.started_at).total_seconds() // 60))


def _submitted(attempt: Attempt) -> datetime:
    """The query filters these out; this only narrows the type."""
    assert attempt.submitted_at is not None
    return attempt.submitted_at


def _score_of(attempt: Attempt) -> float | None:
    value = attempt.response.get("score")
    return float(value) if isinstance(value, int | float) else None


def _judged(attempt: Attempt) -> bool:
    if attempt.activity_type == "reflection":
        return False
    return attempt.response.get("scored") is not False


def _notes(
    activities: list[ActivityDone],
    skills: list[SkillTouched],
    planned: set[str],
    done: int,
) -> list[str]:
    """What a learner should not conclude from one sitting.

    Always non-empty, and the first note is permanent. A summary of a good
    session is precisely where someone is most inclined to read a verdict into
    the numbers, so the disclaimer belongs there rather than in a help page.
    """
    notes = [
        "One sitting is not proof of anything on its own. What is recorded "
        "here is what you did, not a measure of what you can now do — that "
        "takes the same skill holding up on a different day, in a different "
        "situation.",
    ]

    if not activities:
        notes.append(
            "Nothing was finished in this sitting, so nothing was recorded. "
            "That is not held against you anywhere."
        )
        return notes

    if not skills:
        notes.append(
            "Nothing here produced evidence about a skill. Reflection is "
            "deliberately unjudged, and reading a study unit without "
            "answering anything is not something we can learn from."
        )

    if planned and done < len(planned):
        notes.append(
            f"You did {done} of the {len(planned)} things on today's plan. The "
            f"plan is a suggestion, and the rest will be reconsidered "
            f"tomorrow rather than carried over as a debt."
        )

    if any(activity.on_plan is False for activity in activities) and planned:
        notes.append(
            "Some of what you did was not on the plan. It still counts: "
            "evidence is evidence wherever it came from."
        )

    return notes


__all__ = [
    "SITTING_KIND",
    "ActivityDone",
    "SessionAlreadyEndedError",
    "SessionSummary",
    "SkillTouched",
    "Started",
    "complete",
    "current",
    "start",
    "summarise",
]
