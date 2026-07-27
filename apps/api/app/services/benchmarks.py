"""Benchmark sessions: the one measurement in the product.

Every other activity records that something was *practised*, under conditions
the learner partly chose — with an explanation on screen, after a hint, on a
text they had already read. A benchmark records what they can do with none of
that, and `EvidenceType.BENCHMARK` is weighted accordingly.

The rules that make that weight honest live in `learning/benchmarks.py`. This
module enforces them against the record and refuses what they refuse:

- a benchmark asked for early is refused with the reason, not silently
  allowed;
- the items are chosen server-side from what the learner has never seen, so a
  client cannot pick an easy set;
- hints are not a parameter, because there is nothing to hint at;
- evidence is recorded at independence 1.0 and evaluator confidence 1.0,
  which is only defensible because the item types are closed and the answers
  known in advance;
- the whole benchmark is **one context per skill**, so eight items cannot
  satisfy the mastery model's breadth requirement on their own.

Reuses the diagnostic's item bank and scorer. A separate bank would mean two
definitions of what a correct answer is, and they would drift.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.types import utcnow
from ..errors import (
    AppError,
    DiagnosticCompleteError,
    ItemNotFoundError,
    SessionNotFoundError,
)
from ..learning.benchmarks import (
    ITEM_COUNT,
    Eligibility,
    eligibility,
    select_items,
)
from ..learning.items import DiagnosticItem, score_response
from ..models.curriculum import SkillNode
from ..models.enums import CefrLevel, EvidenceType, SessionStatus
from ..models.learning import Attempt, EvidenceEvent, LearningSession
from .diagnostics import item_bank, items_by_key
from .evidence import recompute_all_skill_states, record_evidence

BENCHMARK_CONTEXT = "benchmark"
ACTIVITY_TYPE = "benchmark_item"
EVALUATOR_ID = "deterministic/0.1.0"


class BenchmarkNotDueError(AppError):
    """Asked for before it was due.

    A 409 rather than a 403: nothing is forbidden, the answer is "not yet",
    and the message says when and why.
    """

    code = "benchmark_not_due"
    status_code_default = 409

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


@dataclass(frozen=True)
class BenchmarkPlan:
    """The items chosen for one benchmark, in the order they will be served."""

    session_id: uuid.UUID
    band: CefrLevel
    items: tuple[DiagnosticItem, ...]


@dataclass(frozen=True)
class BenchmarkOutcome:
    """What a finished benchmark established."""

    session_id: uuid.UUID
    band: CefrLevel
    answered: int
    correct: int
    #: Skills whose estimate this benchmark moved *down*. Surfaced rather than
    #: buried: a measurement that only ever agreed with the learner would not
    #: be a measurement, and hiding a fall would make it one.
    lowered: tuple[str, ...]

    @property
    def score(self) -> float:
        if self.answered == 0:
            return 0.0
        return round(self.correct / self.answered, 4)


# --- Eligibility ------------------------------------------------------------


def _observation_count(session: Session, user_id: uuid.UUID) -> int:
    return len(
        session.execute(select(EvidenceEvent.id).where(EvidenceEvent.user_id == user_id))
        .scalars()
        .all()
    )


def _seen_item_keys(session: Session, user_id: uuid.UUID) -> set[str]:
    """Every item this learner has already met, in any context.

    Deliberately not scoped to benchmarks. An item met in the diagnostic is
    just as remembered as one met in a benchmark, and either way it stops
    measuring what it was chosen to measure.
    """
    return set(
        session.execute(select(Attempt.activity_key).where(Attempt.user_id == user_id))
        .scalars()
        .all()
    )


def _last_benchmark(session: Session, user_id: uuid.UUID) -> LearningSession | None:
    rows = session.execute(
        select(LearningSession)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.status == SessionStatus.COMPLETED,
        )
        .order_by(LearningSession.ended_at.desc())
    ).scalars()
    return next((row for row in rows if row.context.get("kind") == BENCHMARK_CONTEXT), None)


def check_eligibility(session: Session, user_id: uuid.UUID) -> Eligibility:
    """Whether a benchmark may be taken now, and why not when it may not."""
    seen = _seen_item_keys(session, user_id)
    unseen = sum(1 for item in item_bank() if item.key not in seen)
    last = _last_benchmark(session, user_id)

    return eligibility(
        now=utcnow(),
        observation_count=_observation_count(session, user_id),
        last_benchmark_at=last.ended_at if last is not None else None,
        unseen_item_count=unseen,
    )


# --- Running one ------------------------------------------------------------


#: Mastery at or above which a skill counts towards where to pitch the items.
#: Matches the mastery model's "supported" threshold: below it, the estimate
#: is not yet saying anything about a level.
BAND_THRESHOLD = 0.70


def _band_for(session: Session, user_id: uuid.UUID) -> CefrLevel:
    """Where to pitch the items.

    Taken from what the learner has actually shown, never from a target they
    set: benchmarking someone at the level they hope to reach measures
    ambition, and produces a confident zero the mastery model would accept at
    full weight.

    The **median** of the bands they hold, not the maximum. One strong skill
    should not pitch a whole benchmark above where the learner is; the point
    of a wide measurement is that it is wide.
    """
    from ..models.learning import SkillState

    rows = (
        session.execute(
            select(SkillNode.cefr_min)
            .join(SkillState, SkillState.skill_node_id == SkillNode.id)
            .where(
                SkillState.user_id == user_id,
                SkillState.mastery_probability >= BAND_THRESHOLD,
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return CefrLevel.A1
    ranks = sorted(level.rank for level in rows)
    return list(CefrLevel)[ranks[len(ranks) // 2]]


def start(session: Session, user_id: uuid.UUID) -> BenchmarkPlan:
    """Open a benchmark, or refuse with a reason.

    Raises:
        BenchmarkNotDueError: it is not due yet.
    """
    verdict = check_eligibility(session, user_id)
    if verdict.blocked:
        raise BenchmarkNotDueError(verdict.reason)

    band = _band_for(session, user_id)
    items = select_items(
        item_bank(),
        band=band,
        seen_keys=_seen_item_keys(session, user_id),
        count=ITEM_COUNT,
    )

    learning_session = LearningSession(
        user_id=user_id,
        status=SessionStatus.IN_PROGRESS,
        started_at=utcnow(),
        # The chosen items are fixed at the start and stored, so the benchmark
        # cannot quietly change shape while it is being taken -- and so a
        # client cannot ask for a different, easier set halfway through.
        context={
            "kind": BENCHMARK_CONTEXT,
            "band": band.value,
            "item_keys": [item.key for item in items],
        },
    )
    session.add(learning_session)
    session.flush()

    return BenchmarkPlan(session_id=learning_session.id, band=band, items=items)


def get_session(session: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> LearningSession:
    learning_session = session.execute(
        select(LearningSession).where(
            LearningSession.id == session_id,
            LearningSession.user_id == user_id,
        )
    ).scalar_one_or_none()
    if learning_session is None or learning_session.context.get("kind") != BENCHMARK_CONTEXT:
        # Indistinguishable from "no such session" on purpose: which sessions
        # exist is not something one learner may learn about another.
        raise SessionNotFoundError()
    return learning_session


def _answered_keys(session: Session, session_id: uuid.UUID) -> set[str]:
    return set(
        session.execute(select(Attempt.activity_key).where(Attempt.session_id == session_id))
        .scalars()
        .all()
    )


def remaining(
    session: Session, user_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[DiagnosticItem, ...]:
    """The items still to answer, in their fixed order."""
    learning_session = get_session(session, user_id, session_id)
    answered = _answered_keys(session, learning_session.id)
    bank = items_by_key()
    keys: list[str] = list(learning_session.context.get("item_keys", []))
    return tuple(bank[key] for key in keys if key not in answered and key in bank)


def submit_response(
    session: Session,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    item_key: str,
    response: str,
    duration_ms: int | None = None,
) -> Attempt:
    """Score one benchmark response.

    No `hints_used` parameter, and that is the point rather than an omission:
    a benchmark with a hint is not a benchmark, so there is nowhere for one to
    be reported.

    An item answered twice is refused. Everywhere else in the product a repeat
    is weaker evidence; here it would be a second attempt at a measurement,
    which is a different thing entirely.
    """
    learning_session = get_session(session, user_id, session_id)
    if learning_session.status is not SessionStatus.IN_PROGRESS:
        raise DiagnosticCompleteError()

    chosen: list[str] = list(learning_session.context.get("item_keys", []))
    if item_key not in chosen:
        raise ItemNotFoundError(item_key)
    if item_key in _answered_keys(session, learning_session.id):
        raise DiagnosticCompleteError()

    item = items_by_key()[item_key]
    scored = score_response(item, response)

    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=item_key,
        activity_type=ACTIVITY_TYPE,
        attempt_number=1,
        response={
            "raw": response,
            "normalised": scored.normalised_response,
            "correct": scored.correct,
            "score": scored.score,
            "provisional": False,
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id=EVALUATOR_ID,
    )
    session.add(attempt)
    session.flush()

    node = _skill_node(session, item.skill_key)
    if node is not None:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            # The whole reason this module exists.
            evidence_type=EvidenceType.BENCHMARK,
            score=scored.score,
            difficulty=item.difficulty,
            # Closed items with a known answer: the score is not an estimate.
            confidence=1.0,
            # Nothing was available to lean on. This is the only place in the
            # product where that is true by construction rather than by
            # self-report.
            independence=1.0,
            novelty=1.0,
            # One context for the whole benchmark, per skill. Eight items in
            # one sitting must not satisfy the model's breadth requirement:
            # `CLAUDE.md` is explicit that recent repeated attempts cannot
            # independently prove generalised mastery.
            context_key=f"benchmark:{learning_session.id}",
            metadata={
                "source": BENCHMARK_CONTEXT,
                "item_type": item.item_type.value,
                "band": learning_session.context.get("band"),
                "unaided": True,
            },
        )

    return attempt


def complete(session: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> BenchmarkOutcome:
    """Close the benchmark and report what it moved, including downwards."""
    from ..models.learning import SkillState

    learning_session = get_session(session, user_id, session_id)

    before = {
        state.skill_node_id: state.mastery_probability
        for state in session.execute(
            select(SkillState).where(SkillState.user_id == user_id)
        ).scalars()
    }

    if learning_session.status is SessionStatus.IN_PROGRESS:
        learning_session.status = SessionStatus.COMPLETED
        learning_session.ended_at = utcnow()

    recompute_all_skill_states(session, user_id=user_id)
    session.flush()

    attempts = (
        session.execute(select(Attempt).where(Attempt.session_id == learning_session.id))
        .scalars()
        .all()
    )

    after = {
        state.skill_node_id: state
        for state in session.execute(
            select(SkillState).where(SkillState.user_id == user_id)
        ).scalars()
    }
    lowered = sorted(
        node.key
        for node_id, state in after.items()
        if node_id in before
        and state.mastery_probability < before[node_id] - 1e-9
        and (node := session.get(SkillNode, node_id)) is not None
    )

    return BenchmarkOutcome(
        session_id=learning_session.id,
        band=CefrLevel(learning_session.context.get("band", CefrLevel.A1.value)),
        answered=len(attempts),
        correct=sum(1 for attempt in attempts if attempt.response.get("correct")),
        lowered=tuple(lowered),
    )


def _skill_node(session: Session, skill_key: str) -> SkillNode | None:
    return session.execute(select(SkillNode).where(SkillNode.key == skill_key)).scalars().first()


__all__ = [
    "ACTIVITY_TYPE",
    "BENCHMARK_CONTEXT",
    "BenchmarkNotDueError",
    "BenchmarkOutcome",
    "BenchmarkPlan",
    "check_eligibility",
    "complete",
    "remaining",
    "start",
    "submit_response",
]
