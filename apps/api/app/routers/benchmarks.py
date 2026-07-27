"""Benchmark endpoints.

Shaped deliberately unlike the activity endpoints. An activity is opened by
key: the client decides what to do next and asks for it. A benchmark has no
key, because the client does not get to choose one — `POST /benchmarks`
either returns the items the server picked or refuses with a reason.

That difference is the whole feature. A benchmark a learner could pick would
measure what they felt ready for.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..deps import CurrentUser, SessionDep
from ..models.enums import CefrLevel
from ..services import benchmarks as service

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


class BenchmarkItemPrompt(BaseModel):
    key: str
    item_type: str
    skill_key: str
    cefr_level: CefrLevel
    prompt: str
    instructions: str
    options: list[str]


class BenchmarkEligibility(BaseModel):
    due: bool
    #: Always says what has to happen next, never "you are not allowed".
    reason: str
    next_due_at: str | None = None


class BenchmarkSession(BaseModel):
    session_id: uuid.UUID
    #: Where the items were pitched, taken from what the learner has shown.
    band: CefrLevel
    items: list[BenchmarkItemPrompt]
    #: Restated on the wire so a client cannot present a benchmark as ordinary
    #: practice. Hints and explanations are not available here.
    unaided: Literal[True] = True


class BenchmarkAnswer(BaseModel):
    # Extra fields are rejected rather than ignored. There is deliberately no
    # `hints_used` here -- a benchmark taken with a hint is not a benchmark --
    # and a client that sends one should be told, not quietly have it dropped
    # while its result is recorded as unaided.
    model_config = ConfigDict(extra="forbid")

    item_key: str
    response: str = Field(max_length=4000)
    duration_ms: int | None = Field(default=None, ge=0)


class BenchmarkAnswerOutcome(BaseModel):
    item_key: str
    correct: bool
    score: float
    #: The remaining items, so a client never has to ask what comes next.
    remaining: int


class BenchmarkResult(BaseModel):
    session_id: uuid.UUID
    band: CefrLevel
    answered: int
    correct: int
    score: float
    #: Skills this benchmark moved *down*. Clients must show these: a
    #: measurement that only ever agreed with the learner would not be one,
    #: and hiding a fall would quietly make it one.
    lowered: list[str]


def _prompt(item: object) -> BenchmarkItemPrompt:
    from ..learning.items import DiagnosticItem

    assert isinstance(item, DiagnosticItem)
    return BenchmarkItemPrompt(
        key=item.key,
        item_type=item.item_type.value,
        skill_key=item.skill_key,
        cefr_level=item.cefr_level,
        prompt=item.prompt,
        instructions=item.instructions,
        options=list(item.options),
    )


@router.get("/eligibility", response_model=BenchmarkEligibility)
def read_eligibility(user: CurrentUser, session: SessionDep) -> BenchmarkEligibility:
    """Whether a benchmark is due, and what has to happen if not."""
    verdict = service.check_eligibility(session, user.id)
    return BenchmarkEligibility(
        due=verdict.due,
        reason=verdict.reason,
        next_due_at=verdict.next_due_at.isoformat() if verdict.next_due_at else None,
    )


@router.post("", response_model=BenchmarkSession, status_code=201)
def start_benchmark(user: CurrentUser, session: SessionDep) -> BenchmarkSession:
    """Start a benchmark, or refuse with `benchmark_not_due` and the reason."""
    plan = service.start(session, user.id)
    session.commit()
    return BenchmarkSession(
        session_id=plan.session_id,
        band=plan.band,
        items=[_prompt(item) for item in plan.items],
    )


@router.post("/{session_id}/responses", response_model=BenchmarkAnswerOutcome)
def answer(
    session_id: uuid.UUID,
    payload: BenchmarkAnswer,
    user: CurrentUser,
    session: SessionDep,
) -> BenchmarkAnswerOutcome:
    """Score one response.

    No `hints_used` field, and its absence is the contract rather than an
    oversight: a benchmark taken with a hint is not a benchmark, so there is
    nowhere to report one.
    """
    attempt = service.submit_response(
        session,
        user.id,
        session_id,
        item_key=payload.item_key,
        response=payload.response,
        duration_ms=payload.duration_ms,
    )
    left = service.remaining(session, user.id, session_id)
    session.commit()
    return BenchmarkAnswerOutcome(
        item_key=payload.item_key,
        correct=bool(attempt.response.get("correct")),
        score=float(attempt.response.get("score", 0.0)),
        remaining=len(left),
    )


@router.post("/{session_id}/complete", response_model=BenchmarkResult)
def complete_benchmark(
    session_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> BenchmarkResult:
    outcome = service.complete(session, user.id, session_id)
    session.commit()
    return BenchmarkResult(
        session_id=outcome.session_id,
        band=outcome.band,
        answered=outcome.answered,
        correct=outcome.correct,
        score=outcome.score,
        lowered=list(outcome.lowered),
    )
