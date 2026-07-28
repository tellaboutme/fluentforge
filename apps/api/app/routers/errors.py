"""The learner's own error log.

`GET /profile/errors` has been in the contract since the beginning and
unimplemented. The reflection screen shows the top three; this is the whole
list, because a learner should be able to see everything the system believes
about their recurring mistakes rather than the three it chose to mention.

The field worth arguing about is `remedy`. Every error names a linguistic
feature, and where a study unit drills that feature the learner can open it
directly. Where none does, the response says **why** rather than leaving a
null for a client to render as a dash:

- some errors are recorded against legacy `item.<skill>` codes, which name a
  skill rather than a practisable feature — there is nothing a unit could
  honestly claim to fix;
- pronunciation features cannot be drilled by anything in this product at
  all. A study unit is read and typed; it cannot teach a sound contrast, and
  offering one would be a lie about what the practice does.

Naming the second case separately matters. "We have not written this yet" and
"nothing we can build in this format would help" are different promises, and
collapsing them would suggest the gap is a backlog item when it needs an
audio pipeline.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import CurrentUser, SessionDep
from ..learning import taxonomy
from ..services import activities
from ..services.errors_log import active_errors, priority_for, schedulable

router = APIRouter(prefix="/profile", tags=["profile"])

#: Why an error has no openable practice. Stable machine values; clients
#: render their own wording.
NO_FEATURE = "no_feature"
NEEDS_SPEECH = "needs_speech"
NOT_WRITTEN = "not_written"


class ErrorPatternView(BaseModel):
    code: str
    #: Rendered. Clients must never show the raw code: it is a machine
    #: identifier and reads as one.
    label: str
    description: str
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    #: `docs/LEARNING_SCIENCE.md` ranks by this before repetition.
    blocks_meaning: bool
    priority: float
    #: Whether this has recurred often enough to earn a place in the review
    #: queue. Surfaced so a learner can see that a single slip is recorded
    #: and not yet being drilled.
    scheduled: bool
    #: Something openable that answers this, or null. A study unit for a
    #: production error; another text or clip for a comprehension one, since
    #: there is no rule to explain about missing what a text implies.
    remedy_key: str | None
    remedy_title: str | None
    #: Which kind of activity `remedy_key` opens. Clients need it to say
    #: "practise this" versus "read another one" honestly.
    remedy_type: str | None
    #: Present only when `remedy_key` is null. Says which kind of gap it is.
    no_remedy_reason: str | None


class ErrorLog(BaseModel):
    items: list[ErrorPatternView]
    #: How many have no openable practice, and why. A learner looking at a
    #: list of unanswerable errors deserves the count rather than having to
    #: infer it.
    without_remedy: int


@router.get("/errors", response_model=ErrorLog)
def read_errors(user: CurrentUser, session: SessionDep) -> ErrorLog:
    """Everything recorded about this learner's recurring errors."""
    items: list[ErrorPatternView] = []

    for pattern in active_errors(session, user.id):
        code = pattern.taxonomy_code
        remedy = activities.remedy_for_feature(code)

        items.append(
            ErrorPatternView(
                code=code,
                label=taxonomy.label_for(code),
                description=pattern.canonical_description,
                occurrences=pattern.occurrence_count,
                first_seen_at=pattern.first_seen_at,
                last_seen_at=pattern.last_seen_at,
                blocks_meaning=pattern.blocks_meaning,
                priority=priority_for(pattern),
                scheduled=schedulable(pattern),
                remedy_key=remedy.activity_key if remedy else None,
                remedy_title=remedy.title if remedy else None,
                remedy_type=remedy.activity_type if remedy else None,
                no_remedy_reason=None if remedy else _why_not(code),
            )
        )

    return ErrorLog(
        items=items,
        without_remedy=sum(1 for item in items if item.remedy_key is None),
    )


def _why_not(code: str) -> str:
    """Which kind of gap this is.

    Three answers, and the distinction is the point. A backlog item, a code
    that cannot have a remedy by construction, and a skill this product
    cannot teach in this format are different promises to a learner.
    """
    if not taxonomy.is_known(code):
        # A legacy `item.<skill>` code names a skill, not a practisable
        # feature. Nothing could honestly claim to fix "something in
        # grammar.connected_time_modality".
        return NO_FEATURE
    if ".comprehension." in code:
        # A comprehension feature is answered by another text or clip, so
        # reaching here means the bank has none asking that question type —
        # a content gap, not a format one.
        return NOT_WRITTEN
    if code.startswith("pronunciation."):
        # A study unit is read and typed. It cannot teach a sound contrast,
        # and one claiming to would be lying about what the practice does.
        return NEEDS_SPEECH
    return NOT_WRITTEN
