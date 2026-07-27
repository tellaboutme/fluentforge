"""Diagnostic session orchestration.

Flow: start a session, serve one item at a time, score each response
deterministically, write an `EvidenceEvent` per response, then recompute
`SkillState` on completion.

Session state is derived from stored `Attempt` rows rather than held in memory,
so a learner can leave and resume without losing their place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..curriculum.items import parse_item_bank
from ..curriculum.loader import active_curriculum_version
from ..db.types import utcnow
from ..errors import (
    CurriculumNotLoadedError,
    DiagnosticCompleteError,
    ItemNotFoundError,
    SessionNotFoundError,
)
from ..learning import taxonomy
from ..learning.items import DiagnosticItem, ItemType, ScoredResponse, score_response
from ..learning.selection import SelectionState, provisional_band, replay, select_next
from ..models.curriculum import CurriculumVersion, SkillNode
from ..models.enums import CefrLevel, SessionStatus
from ..models.learning import Attempt, LearningSession
from ..settings import settings
from .errors_log import record_error, sync_error_cards
from .evidence import recompute_all_skill_states, record_evidence
from .reviews import seed_from_diagnostic

DIAGNOSTIC_CONTEXT = "diagnostic"
ACTIVITY_TYPE = "diagnostic_item"


@lru_cache(maxsize=4)
def _load_items(curriculum_dir: str) -> tuple[DiagnosticItem, ...]:
    """Item bank is versioned source data and immutable at runtime, so cache it."""
    return parse_item_bank(Path(curriculum_dir))


def item_bank() -> tuple[DiagnosticItem, ...]:
    return _load_items(str(settings.curriculum_dir))


def items_by_key() -> dict[str, DiagnosticItem]:
    return {item.key: item for item in item_bank()}


@dataclass(frozen=True)
class NextItem:
    item: DiagnosticItem | None
    answered: int
    ability_estimate: float
    finished: bool


def start_diagnostic(session: Session, user_id: uuid.UUID) -> LearningSession:
    """Open a diagnostic session, reusing an unfinished one if present.

    Reuse rather than restart: an interrupted diagnostic should continue, not
    discard the evidence already gathered.
    """
    existing = session.execute(
        select(LearningSession)
        .where(
            LearningSession.user_id == user_id,
            LearningSession.status == SessionStatus.IN_PROGRESS,
        )
        .order_by(LearningSession.started_at.desc())
    ).scalars()
    resumable = next(iter(existing), None)
    if resumable is not None and resumable.context.get("kind") == DIAGNOSTIC_CONTEXT:
        return resumable

    version = _require_curriculum_version(session)
    learning_session = LearningSession(
        user_id=user_id,
        status=SessionStatus.IN_PROGRESS,
        context={"kind": DIAGNOSTIC_CONTEXT, "curriculum_version": version.semantic_version},
    )
    session.add(learning_session)
    session.flush()
    return learning_session


def get_session(session: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> LearningSession:
    """Fetch a session, scoped to its owner.

    Ownership is part of the lookup, not a separate check, so a missing session
    and another learner's session are indistinguishable.
    """
    learning_session = session.execute(
        select(LearningSession).where(
            LearningSession.id == session_id, LearningSession.user_id == user_id
        )
    ).scalar_one_or_none()
    if learning_session is None:
        raise SessionNotFoundError()
    return learning_session


def _attempts(session: Session, session_id: uuid.UUID) -> list[Attempt]:
    return list(
        session.execute(
            select(Attempt)
            .where(Attempt.session_id == session_id)
            .order_by(Attempt.started_at, Attempt.attempt_number)
        )
        .scalars()
        .all()
    )


def attempt_count(session: Session, session_id: uuid.UUID) -> int:
    return len(_attempts(session, session_id))


def _counts_toward_band(item: DiagnosticItem) -> bool:
    """Only right/wrong items place a learner in a band.

    A self-rating is a claim, and a writing task is scored on countable checks
    rather than correctness; neither belongs in a pass-rate calculation.
    """
    return item.item_type is not ItemType.SELF_ASSESSMENT and not item.item_type.is_productive


def starting_band(session: Session, session_id: uuid.UUID) -> CefrLevel | None:
    """Which level's content to open with. Not a placement (see `provisional_band`)."""
    bank = items_by_key()
    results: list[tuple[CefrLevel, bool]] = []
    for attempt in _attempts(session, session_id):
        item = bank.get(attempt.activity_key)
        if item is None or not _counts_toward_band(item):
            continue
        results.append((item.cefr_level, bool((attempt.response or {}).get("correct"))))
    return provisional_band(results)


def _selection_state(attempts: list[Attempt]) -> SelectionState:
    responses: list[tuple[str, bool, float | None]] = []
    for attempt in attempts:
        response = attempt.response or {}
        responses.append(
            (
                attempt.activity_key,
                bool(response.get("correct")),
                response.get("score") if response.get("self_assessment") else None,
            )
        )
    return replay(items_by_key(), responses)


def next_item(session: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> NextItem:
    """Serve the next item, or report that the diagnostic is finished."""
    learning_session = get_session(session, user_id, session_id)
    attempts = _attempts(session, learning_session.id)
    state = _selection_state(attempts)

    if learning_session.status is not SessionStatus.IN_PROGRESS:
        return NextItem(None, len(attempts), state.ability, finished=True)

    candidate = select_next(list(item_bank()), state)
    return NextItem(
        item=candidate,
        answered=len(attempts),
        ability_estimate=state.ability,
        finished=candidate is None,
    )


def submit_response(
    session: Session,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    item_key: str,
    response: str,
    duration_ms: int | None = None,
    hints_used: int = 0,
) -> tuple[Attempt, ScoredResponse]:
    """Score one response, store the attempt, and record evidence.

    Raises:
        SessionNotFoundError, DiagnosticCompleteError, ItemNotFoundError.
    """
    learning_session = get_session(session, user_id, session_id)
    if learning_session.status is not SessionStatus.IN_PROGRESS:
        raise DiagnosticCompleteError()

    item = items_by_key().get(item_key)
    if item is None:
        raise ItemNotFoundError(item_key)

    scored = score_response(item, response)

    existing = _attempts(session, learning_session.id)
    attempt_number = sum(1 for a in existing if a.activity_key == item_key) + 1

    # Hints and repeats weaken evidence rather than being ignored.
    independence = max(0.0, 1.0 - 0.35 * hints_used)
    novelty = 1.0 if attempt_number == 1 else 0.4

    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key=item_key,
        activity_type=ACTIVITY_TYPE,
        attempt_number=attempt_number,
        response={
            "raw": response,
            "normalised": scored.normalised_response,
            "correct": scored.correct,
            "score": scored.score,
            "self_assessment": item.item_type is ItemType.SELF_ASSESSMENT,
            "checks": [
                {"code": code, "passed": passed, "message": message}
                for code, passed, message in scored.checks
            ],
            "provisional": scored.provisional,
        },
        submitted_at=utcnow(),
        duration_ms=duration_ms,
        hints_used=hints_used,
        scaffolding_level=round(1.0 - independence, 4),
        evaluator_id="deterministic/0.1.0",
    )
    session.add(attempt)
    session.flush()

    # A wrong answer on a closed item is a data point about *what* went wrong,
    # not only that something did. Logging it lets the error feed the review
    # queue once it recurs.
    if not scored.correct and _counts_toward_band(item):
        # Prefer the linguistic feature the item names: `grammar.tense.
        # perfect_vs_past` can be practised, and a study unit can answer it.
        # Items that name none — reading comprehension, mostly — keep the
        # legacy skill-shaped code, which stays readable and still schedules
        # practice but earns no automatic remedy. Inventing a feature for them
        # would be worse than admitting there isn't one.
        feature = item.feature
        record_error(
            session,
            user_id,
            taxonomy_code=feature or f"item.{item.skill_key}",
            description=(
                taxonomy.describe(feature) if feature else f"Difficulty with: {item.prompt[:80]}"
            ),
            example=scored.normalised_response or None,
            blocks_meaning=taxonomy.blocks_meaning_default(feature) if feature else False,
        )
        sync_error_cards(session, user_id)

    skill_node = _skill_node(session, item.skill_key)
    if skill_node is not None:
        record_evidence(
            session,
            user_id=user_id,
            skill_node_id=skill_node.id,
            attempt_id=attempt.id,
            evidence_type=item.evidence_type,
            score=scored.score,
            difficulty=item.difficulty,
            # A closed item's score is certain; free writing scored by countable
            # checks is not, and says so (see learning/writing.py).
            confidence=scored.evaluator_confidence,
            independence=independence,
            novelty=novelty,
            context_key=item.key,
            metadata={
                "item_type": item.item_type.value,
                "source": DIAGNOSTIC_CONTEXT,
                "provisional": scored.provisional,
            },
        )

    return attempt, scored


def complete_diagnostic(
    session: Session, user_id: uuid.UUID, session_id: uuid.UUID
) -> LearningSession:
    """Close the session and rebuild every affected skill state."""
    learning_session = get_session(session, user_id, session_id)
    if learning_session.status is SessionStatus.IN_PROGRESS:
        learning_session.status = SessionStatus.COMPLETED
        learning_session.ended_at = utcnow()

    recompute_all_skill_states(session, user_id=user_id)

    # Seed review cards now: the diagnostic has just established roughly where
    # the learner is, which is exactly what scopes a useful starting deck.
    band = starting_band(session, session_id)
    seed_from_diagnostic(session, user_id, band_rank=band.rank if band else None)

    session.flush()
    return learning_session


def _skill_node(session: Session, skill_key: str) -> SkillNode | None:
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()
    return session.execute(
        select(SkillNode).where(
            SkillNode.curriculum_version_id == version.id, SkillNode.key == skill_key
        )
    ).scalar_one_or_none()


def _require_curriculum_version(session: Session) -> CurriculumVersion:
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()
    return version
