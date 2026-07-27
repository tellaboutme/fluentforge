"""Learner profile and skill-estimate contracts.

Note the shape: there is no single learner level. The profile exposes a list of
per-skill estimates, each with its own confidence and evidence count.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import CefrLevel, SkillDomain


class SkillEstimate(BaseModel):
    """One skill's current estimate.

    ``mastery_probability`` and ``confidence`` are independent: a learner can
    have a high estimate we are not yet confident in, and vice versa.
    """

    skill_key: str
    domain: SkillDomain
    title: str
    cefr_estimate: CefrLevel | None = Field(
        default=None,
        description="Null until enough evidence exists to place the skill.",
    )
    mastery_probability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=0)
    distinct_contexts: int = Field(ge=0)
    last_observed_at: datetime | None = None
    status: str = Field(
        description="unobserved | emerging | supported | independent",
    )


class DomainSummary(BaseModel):
    domain: SkillDomain
    tracked_skills: int
    observed_skills: int
    mean_confidence: float = Field(ge=0, le=1)


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    display_name: str
    target_level: CefrLevel
    daily_minutes: int
    explanation_language: str
    timezone: str
    goals: dict[str, Any]
    interests: dict[str, Any]
    curriculum_version: str
    skills: list[SkillEstimate]
    domain_summaries: list[DomainSummary]


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    daily_minutes: int | None = Field(default=None, ge=5, le=240)
    target_level: CefrLevel | None = None
    explanation_language: str | None = Field(default=None, min_length=2, max_length=16)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    goals: dict[str, Any] | None = None
    interests: dict[str, Any] | None = None
