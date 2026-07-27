"""Diagnostic contracts.

`ItemPrompt` is the only item shape sent to a client. It has no `answer_key`
field, so an answer key cannot leak through this boundary by accident.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import CefrLevel, EvidenceType, SessionStatus


class ItemPrompt(BaseModel):
    key: str
    item_type: str
    skill_key: str
    cefr_level: CefrLevel
    prompt: str
    instructions: str
    options: list[str]
    difficulty: float
    evidence_type: EvidenceType
    # Written responses only. Shown before the learner writes, so no one fails
    # a length requirement they were never told about.
    min_words: int | None = None
    max_words: int | None = None


class SessionResponse(BaseModel):
    id: uuid.UUID
    status: SessionStatus
    started_at: datetime
    answered: int


class NextItemResponse(BaseModel):
    session_id: uuid.UUID
    finished: bool
    answered: int
    item: ItemPrompt | None = None
    ability_estimate: float = Field(
        ge=0,
        le=1,
        description="Internal routing estimate for item selection. Not a CEFR level "
        "and not shown to the learner as a score.",
    )


class SubmitResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(min_length=1, max_length=128)
    response: str = Field(max_length=2000)
    duration_ms: int | None = Field(default=None, ge=0)
    hints_used: int = Field(default=0, ge=0, le=10)


class ResponseCheck(BaseModel):
    """One countable check on a written response."""

    code: str
    passed: bool
    message: str


class SubmitResponseResult(BaseModel):
    correct: bool
    score: float
    explanation: str
    expected: list[str] = Field(
        description="Revealed only after the response is submitted, never before."
    )
    answered: int
    finished: bool
    checks: list[ResponseCheck] = Field(
        default_factory=list,
        description="Per-check detail for written responses; empty for closed items.",
    )
    provisional: bool = Field(
        default=False,
        description="True when scoring is deterministic-only and cannot judge "
        "accuracy. The UI must not present a provisional score as a verdict.",
    )


class DiagnosticSkillOutcome(BaseModel):
    skill_key: str
    title: str
    cefr_level: CefrLevel
    mastery_probability: float
    confidence: float
    evidence_count: int
    distinct_contexts: int
    status: str


class DiagnosticReport(BaseModel):
    session_id: uuid.UUID
    status: SessionStatus
    curriculum_version: str
    model_version: str
    items_answered: int
    skills_observed: int
    starting_band: CefrLevel | None = Field(
        default=None,
        description="Which level's content to open with. A routing decision, not a "
        "placement or a mastery claim. Null when too few items were answered.",
    )
    outcomes: list[DiagnosticSkillOutcome]
    caveats: list[str] = Field(
        description="Stated limits of this result. Always non-empty: a short "
        "diagnostic cannot certify a level."
    )
