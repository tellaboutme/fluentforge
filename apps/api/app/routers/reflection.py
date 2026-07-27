"""Reflection endpoints.

The only pair in the API where a learner sends prose and nothing judges it.
That is stated on the wire — `scored: false` on the way back — because a
client has no other way to know, and a screen that implied otherwise would
teach the learner to write reflections that pass checks.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import CurrentUser, SessionDep
from ..services import reflection as service

router = APIRouter(prefix="/reflection", tags=["reflection"])


class RecurringErrorView(BaseModel):
    code: str
    #: Rendered, never the raw code. Clients must show this.
    label: str
    description: str
    occurrences: int
    blocks_meaning: bool


class ReflectionPromptResponse(BaseModel):
    #: At most three. A list of everything wrong is a list nobody acts on.
    recurring_errors: list[RecurringErrorView]
    untouched_skills: list[str]
    #: How much of the learner's own work nothing has judged. Surfaced
    #: because it is the product's blind spot, and someone reflecting on
    #: their progress should not read silence as approval.
    unjudged_count: int
    previous_note: str | None


class ReflectionNote(BaseModel):
    note: str = Field(max_length=4000)
    duration_ms: int | None = Field(default=None, ge=0)


class ReflectionSaved(BaseModel):
    saved: bool
    #: Always false, and said out loud. Nothing here was checked, corrected,
    #: or counted towards any skill: a stated intention is not a demonstrated
    #: one.
    scored: bool = False
    evidence_recorded: bool = False


@router.get("", response_model=ReflectionPromptResponse)
def read_prompt(user: CurrentUser, session: SessionDep) -> ReflectionPromptResponse:
    """What the system has actually noticed, offered back for reflection."""
    prompt = service.build_prompt(session, user.id)
    return ReflectionPromptResponse(
        recurring_errors=[
            RecurringErrorView(
                code=error.code,
                label=error.label,
                description=error.description,
                occurrences=error.occurrences,
                blocks_meaning=error.blocks_meaning,
            )
            for error in prompt.recurring_errors
        ],
        untouched_skills=list(prompt.untouched_skills),
        unjudged_count=prompt.unjudged_count,
        previous_note=prompt.previous_note,
    )


@router.post("", response_model=ReflectionSaved, status_code=201)
def save_note(payload: ReflectionNote, user: CurrentUser, session: SessionDep) -> ReflectionSaved:
    """Store a reflection. Nothing is scored and no evidence is recorded.

    There is no minimum length: "nothing new this week" is a legitimate
    reflection and sometimes the true one.
    """
    service.record(session, user.id, note=payload.note, duration_ms=payload.duration_ms)
    session.commit()
    return ReflectionSaved(saved=True)
