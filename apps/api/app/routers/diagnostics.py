"""Diagnostic endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..curriculum.loader import active_curriculum_version
from ..deps import CurrentUser, SessionDep
from ..errors import CurriculumNotLoadedError
from ..learning.evidence import MODEL_VERSION
from ..learning.mastery import MasteryThresholds, classify_status
from ..models.curriculum import SkillNode
from ..models.learning import LearningSession, SkillState
from ..schemas.diagnostics import (
    DiagnosticReport,
    DiagnosticSkillOutcome,
    ItemPrompt,
    NextItemResponse,
    ResponseCheck,
    SessionResponse,
    SubmitResponseRequest,
    SubmitResponseResult,
)
from ..services import diagnostics as service
from ..services.evidence import current_confidence

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

CAVEATS = [
    "This is an internal estimate, not an official CEFR certificate.",
    "Recognition items show what you can identify, not yet what you can produce.",
    "A short diagnostic cannot confirm a can-do statement. Skills stay marked "
    "'needs evidence' until you have shown them across several different tasks.",
    "Your starting level decides which content you see first. It is not a score.",
]


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def start(user: CurrentUser, session: SessionDep) -> SessionResponse:
    learning_session = service.start_diagnostic(session, user.id)
    session.commit()
    state = service.next_item(session, user.id, learning_session.id)
    return SessionResponse(
        id=learning_session.id,
        status=learning_session.status,
        started_at=learning_session.started_at,
        answered=state.answered,
    )


@router.get("/{session_id}/next", response_model=NextItemResponse)
def next_item(session_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> NextItemResponse:
    result = service.next_item(session, user.id, session_id)
    return NextItemResponse(
        session_id=session_id,
        finished=result.finished,
        answered=result.answered,
        ability_estimate=result.ability_estimate,
        item=ItemPrompt(**result.item.as_prompt()) if result.item else None,
    )


@router.post("/{session_id}/responses", response_model=SubmitResponseResult)
def submit(
    session_id: uuid.UUID,
    payload: SubmitResponseRequest,
    user: CurrentUser,
    session: SessionDep,
) -> SubmitResponseResult:
    _, scored = service.submit_response(
        session,
        user.id,
        session_id,
        item_key=payload.item_key,
        response=payload.response,
        duration_ms=payload.duration_ms,
        hints_used=payload.hints_used,
    )
    session.commit()

    following = service.next_item(session, user.id, session_id)
    return SubmitResponseResult(
        correct=scored.correct,
        score=scored.score,
        explanation=scored.explanation,
        expected=list(scored.expected),
        answered=following.answered,
        finished=following.finished,
        checks=[
            ResponseCheck(code=code, passed=passed, message=message)
            for code, passed, message in scored.checks
        ],
        provisional=scored.provisional,
    )


@router.post("/{session_id}/complete", response_model=DiagnosticReport)
def complete(session_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> DiagnosticReport:
    learning_session = service.complete_diagnostic(session, user.id, session_id)
    session.commit()
    return _build_report(session, user.id, learning_session)


@router.get("/{session_id}/report", response_model=DiagnosticReport)
def report(session_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> DiagnosticReport:
    learning_session = service.get_session(session, user.id, session_id)
    return _build_report(session, user.id, learning_session)


def _build_report(
    session: Session, user_id: uuid.UUID, learning_session: LearningSession
) -> DiagnosticReport:
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()

    thresholds = MasteryThresholds.from_metadata(version.metadata_json)

    rows = session.execute(
        select(SkillState, SkillNode)
        .join(SkillNode, SkillNode.id == SkillState.skill_node_id)
        .where(
            SkillState.user_id == user_id,
            SkillNode.curriculum_version_id == version.id,
        )
        .order_by(SkillNode.domain, SkillNode.cefr_min)
    ).all()

    # Decayed like every other read. A report is not only opened the moment
    # it is produced -- a learner returning to it in September must not see
    # July's certainty presented as current.
    outcomes = [
        DiagnosticSkillOutcome(
            skill_key=node.key,
            title=node.title,
            cefr_level=node.cefr_max,
            mastery_probability=state.mastery_probability,
            confidence=current_confidence(state),
            evidence_count=state.evidence_count,
            distinct_contexts=state.distinct_contexts,
            status=classify_status(
                mastery_probability=state.mastery_probability,
                confidence=current_confidence(state),
                distinct_contexts=state.distinct_contexts,
                evidence_count=state.evidence_count,
                thresholds=thresholds,
            ),
        )
        for state, node in rows
    ]

    return DiagnosticReport(
        session_id=learning_session.id,
        status=learning_session.status,
        curriculum_version=version.semantic_version,
        model_version=MODEL_VERSION,
        items_answered=service.attempt_count(session, learning_session.id),
        skills_observed=len(outcomes),
        starting_band=service.starting_band(session, learning_session.id),
        outcomes=outcomes,
        caveats=CAVEATS,
    )
