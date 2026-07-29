"""A learner's own past work.

`GET /attempts/{id}/feedback` has been in `docs/API_CONTRACTS.md` since the
beginning and unimplemented. Everything a learner produced was stored and
unreachable: they saw their feedback once, on the screen that produced it,
and then it was gone.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from ..deps import CurrentUser, SessionDep
from ..services import history as service
from ..services import reports

router = APIRouter(tags=["history"])


class HistoryItem(BaseModel):
    attempt_id: uuid.UUID
    activity_key: str
    activity_type: str
    submitted_at: datetime
    #: The learner's own words where there are any, because a list of scores
    #: does not tell someone which piece of work they are looking at.
    summary: str
    score: float | None
    #: False for reflection, and for anything else nothing assessed.
    was_judged: bool


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    #: Pass back as `before` for the next page. Null when the history ends.
    next_before: datetime | None


class AttemptFeedbackResponse(BaseModel):
    attempt_id: uuid.UUID
    activity_key: str
    activity_type: str
    submitted_at: datetime
    #: Which evaluator produced this at the time. A learner comparing two
    #: pieces of feedback deserves to know whether the same thing judged
    #: them. Null where nothing did.
    evaluator_id: str | None
    #: The stored response, verbatim. Not recomputed: the checks, the
    #: curriculum version and the evaluator may all have changed since, and
    #: re-deriving would show a verdict nobody ever gave.
    response: dict[str, Any]
    was_judged: bool
    #: True whenever the feedback might be produced differently today.
    #: Clients should date the feedback rather than present it as current.
    is_stale: bool


@router.get("/attempts", response_model=HistoryPage)
def read_history(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=service.PAGE_SIZE)] = service.PAGE_SIZE,
    before: Annotated[datetime | None, Query()] = None,
) -> HistoryPage:
    """The learner's attempts, newest first.

    Keyset pagination rather than an offset: scrolling back while new
    attempts arrive would otherwise make items shift between pages.
    """
    entries = service.recent(session, user.id, limit=limit, before=before)
    return HistoryPage(
        items=[
            HistoryItem(
                attempt_id=entry.attempt_id,
                activity_key=entry.activity_key,
                activity_type=entry.activity_type,
                submitted_at=entry.submitted_at,
                summary=entry.summary,
                score=entry.score,
                was_judged=entry.was_judged,
            )
            for entry in entries
        ],
        next_before=entries[-1].submitted_at if len(entries) == limit else None,
    )


@router.get("/attempts/{attempt_id}/feedback", response_model=AttemptFeedbackResponse)
def read_feedback(
    attempt_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AttemptFeedbackResponse:
    """One attempt in full, as it was recorded.

    Reading your own history is not an attempt: nothing is re-scored and no
    evidence is written. A system that recorded this would be counting
    rereading as practice.
    """
    found = service.feedback(session, user.id, attempt_id)
    return AttemptFeedbackResponse(
        attempt_id=found.attempt_id,
        activity_key=found.activity_key,
        activity_type=found.activity_type,
        submitted_at=found.submitted_at,
        evaluator_id=found.evaluator_id,
        response=found.response,
        was_judged=found.was_judged,
        is_stale=found.is_stale,
    )


class ReportRequest(BaseModel):
    #: From the closed set in `services.reports.REASONS`. Free text alone
    #: cannot be counted, and a report nobody can count is one nobody acts on.
    reason: str
    #: The learner explaining themselves. Optional, kept verbatim, bounded so
    #: a report cannot become an essay nobody reads.
    note: str | None = Field(default=None, max_length=2000)


class ReportResponse(BaseModel):
    report_id: uuid.UUID
    reported_at: datetime
    #: How many observations became less certain.
    evidence_softened: int
    #: What the learner should and should not expect. Always non-empty, and
    #: clients must surface it: a report that said only "thanks" would let
    #: someone believe their score had been overturned.
    notes: list[str]


@router.post(
    "/attempts/{attempt_id}/report",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def report_feedback(
    attempt_id: uuid.UUID,
    payload: ReportRequest,
    user: CurrentUser,
    session: SessionDep,
) -> ReportResponse:
    """Say a verdict was wrong.

    Lowers the confidence of the evidence this attempt produced and leaves the
    score alone. Confidence is how sure the model is; `mastery_probability` is
    what it believes. Disagreeing is a reason for the first and not the
    second, so a report can only widen the uncertainty -- which is also what
    makes it ungameable, since disputing everything cannot inflate a profile.

    Nothing is deleted. The attempt, the response and the recorded feedback
    stay exactly as they were, so `/history` still shows what the learner was
    actually told.
    """
    outcome = reports.report_attempt(
        session, user.id, attempt_id, reason=payload.reason, note=payload.note
    )
    session.commit()
    return ReportResponse(
        report_id=outcome.report_id,
        reported_at=outcome.reported_at,
        evidence_softened=outcome.evidence_softened,
        notes=outcome.notes,
    )
