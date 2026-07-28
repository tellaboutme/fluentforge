"""Starting and ending a sitting.

The last two unimplemented endpoints in `docs/API_CONTRACTS.md`. See
`app/services/sessions.py` for what the summary deliberately does not claim —
in short: what you did, never how much better you got.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..deps import CurrentUser, SessionDep
from ..models.enums import SessionStatus
from ..services import sessions as service

router = APIRouter(prefix="/sessions", tags=["sessions"])


class StartSessionRequest(BaseModel):
    #: Which plan this sitting is against. Omitted means today's, if one has
    #: already been generated. Never generates one: sitting down should not
    #: manufacture a plan for a day the learner never planned.
    plan_id: uuid.UUID | None = Field(default=None)


class SessionStarted(BaseModel):
    session_id: uuid.UUID
    started_at: datetime
    plan_id: uuid.UUID | None
    #: True when this returned a sitting that was already open. Clients can
    #: use it to avoid saying "session started" to someone resuming one.
    resumed: bool


class ActivityDoneView(BaseModel):
    activity_key: str
    activity_type: str
    submitted_at: datetime
    score: float | None
    was_judged: bool
    on_plan: bool


class SkillTouchedView(BaseModel):
    key: str
    title: str
    evidence_recorded: int
    #: Total after this sitting, which is what the mastery model gates on.
    distinct_contexts: int
    status: str
    needs: str | None


class SessionSummaryView(BaseModel):
    session_id: uuid.UUID
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None
    #: Elapsed time the sitting was open. Not time on task, and clients must
    #: not label it as study time.
    open_minutes: int
    plan_id: uuid.UUID | None
    activities: list[ActivityDoneView]
    skills: list[SkillTouchedView]
    plan_items_done: int
    plan_items_total: int
    #: Always non-empty. Clients must surface it.
    notes: list[str]


@router.post("", response_model=SessionStarted, status_code=status.HTTP_201_CREATED)
def start_session(
    payload: StartSessionRequest, user: CurrentUser, session: SessionDep
) -> SessionStarted:
    """Begin a sitting, or resume today's.

    201 either way. The alternative — 200 for a resume — would make a client
    branch on a status code to answer a question `resumed` answers directly,
    and the resource named by the response exists in both cases.
    """
    started = service.start(session, user.id, plan_id=payload.plan_id)
    sitting = started.sitting
    view = SessionStarted(
        session_id=sitting.id,
        started_at=sitting.started_at,
        plan_id=sitting.plan_id,
        resumed=started.resumed,
    )
    session.commit()
    return view


class CurrentSession(BaseModel):
    #: Null when nothing is open. A separate read rather than a side effect of
    #: `POST /sessions`, so that opening the dashboard does not begin a
    #: sitting and start counting elapsed time on a page nobody is reading.
    session_id: uuid.UUID | None
    started_at: datetime | None
    plan_id: uuid.UUID | None


@router.get("/current", response_model=CurrentSession)
def read_current_session(user: CurrentUser, session: SessionDep) -> CurrentSession:
    """Today's open sitting, or nulls. Never 404: having no sitting open is
    an ordinary state, not a missing resource."""
    sitting = service.current(session, user.id)
    if sitting is None:
        return CurrentSession(session_id=None, started_at=None, plan_id=None)
    return CurrentSession(
        session_id=sitting.id, started_at=sitting.started_at, plan_id=sitting.plan_id
    )


@router.post("/{session_id}/complete", response_model=SessionSummaryView)
def complete_session(
    session_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> SessionSummaryView:
    """End a sitting and describe it.

    Idempotent: completing an already-completed sitting returns the original
    summary with the original `ended_at`.
    """
    summary = service.complete(session, user.id, session_id)
    session.commit()
    return _view(summary)


def _view(summary: service.SessionSummary) -> SessionSummaryView:
    return SessionSummaryView(
        session_id=summary.session_id,
        status=summary.status,
        started_at=summary.started_at,
        ended_at=summary.ended_at,
        open_minutes=summary.open_minutes,
        plan_id=summary.plan_id,
        activities=[
            ActivityDoneView(
                activity_key=activity.activity_key,
                activity_type=activity.activity_type,
                submitted_at=activity.submitted_at,
                score=activity.score,
                was_judged=activity.was_judged,
                on_plan=activity.on_plan,
            )
            for activity in summary.activities
        ],
        skills=[
            SkillTouchedView(
                key=skill.key,
                title=skill.title,
                evidence_recorded=skill.evidence_recorded,
                distinct_contexts=skill.distinct_contexts,
                status=skill.status,
                needs=skill.needs,
            )
            for skill in summary.skills
        ],
        plan_items_done=summary.plan_items_done,
        plan_items_total=summary.plan_items_total,
        notes=summary.notes,
    )
