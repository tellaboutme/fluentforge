"""Daily plan contracts.

Every item carries its reason codes, its human explanation, and the full
component breakdown that produced it. `docs/ADAPTIVE_ENGINE.md` requires the
UI to be able to answer "why is this in today's plan?" — that is only possible
if the answer travels with the data.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import PlanReasonCode, PlanStatus


class PlanItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    activity_key: str
    activity_type: str
    estimated_minutes: int
    title: str
    kind: str
    skill_key: str
    domain: str
    reason_codes: list[PlanReasonCode]
    explanation: str = Field(
        description="A one-line, learner-facing reason for this item's presence."
    )
    priority: float
    components: dict[str, float] = Field(
        description="Every priority component, including those that scored zero. "
        "Stored so plan decisions stay auditable rather than opaque."
    )


class PlanResponse(BaseModel):
    id: uuid.UUID
    plan_date: date
    requested_minutes: int
    total_minutes: int
    status: PlanStatus
    engine_version: str
    items: list[PlanItemResponse]
    has_receptive: bool
    has_productive: bool
    unmet_constraints: list[str] = Field(
        default_factory=list,
        description="Constraints the planner could not satisfy today. Surfaced "
        "rather than hidden, so a thin plan does not look like a complete one.",
    )


class GeneratePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regenerate: bool = Field(
        default=False,
        description="Replace today's plan. Off by default: a plan that changes "
        "on every page load cannot be trusted or followed.",
    )
