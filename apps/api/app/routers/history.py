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

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..deps import CurrentUser, SessionDep
from ..services import history as service

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
