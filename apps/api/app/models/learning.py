"""Learning records: sessions, attempts, evidence, mastery, and error patterns.

Mastery is never written directly. It is derived from `evidence_events`, each
of which records how the evidence was produced (independence, novelty,
difficulty, confidence) so a weak signal cannot masquerade as proof.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ..db.types import GUID, JSONB, UTCDateTime, enum_column, utcnow
from .enums import ErrorStatus, EvidenceType, SessionStatus


class LearningSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "learning_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("plans.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SessionStatus] = mapped_column(
        enum_column(SessionStatus, "session_status"),
        default=SessionStatus.IN_PROGRESS,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)

    attempts: Mapped[list[Attempt]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Attempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One learner response to one activity.

    ``hints_used`` and ``scaffolding_level`` are required inputs to evidence
    weighting: a correct answer with heavy support is weaker evidence.
    """

    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        CheckConstraint("hints_used >= 0", name="hints_used_non_negative"),
        UniqueConstraint(
            "session_id", "activity_key", "attempt_number", name="uq_attempts_session_activity"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Activities are not yet a persisted table (Milestone 3+); the stable key
    # keeps attempts referenceable until they are.
    activity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scaffolding_level: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evaluator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    session: Mapped[LearningSession] = relationship(back_populates="attempts")
    evidence_events: Mapped[list[EvidenceEvent]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class EvidenceEvent(UUIDPrimaryKeyMixin, Base):
    """An observation about one skill, produced by one attempt.

    All of ``score``, ``confidence``, ``independence`` and ``novelty`` are
    bounded 0..1 and enforced at the database level: mastery inference is only
    as trustworthy as these inputs.
    """

    __tablename__ = "evidence_events"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="score_bounded"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_bounded"),
        CheckConstraint("independence >= 0 AND independence <= 1", name="independence_bounded"),
        CheckConstraint("novelty >= 0 AND novelty <= 1", name="novelty_bounded"),
        CheckConstraint("weight >= 0", name="weight_non_negative"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_node_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("skill_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("attempts.id", ondelete="SET NULL"), nullable=True
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        enum_column(EvidenceType, "evidence_type"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    difficulty: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    independence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    novelty: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    context_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)

    attempt: Mapped[Attempt | None] = relationship(back_populates="evidence_events")


class SkillState(TimestampMixin, Base):
    """Current mastery estimate per learner per skill.

    A derived projection of `evidence_events`, recomputed by the assessment
    engine. ``confidence`` decays without observation; ``mastery_probability``
    does not.
    """

    __tablename__ = "skill_states"
    __table_args__ = (
        CheckConstraint(
            "mastery_probability >= 0 AND mastery_probability <= 1",
            name="mastery_probability_bounded",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_bounded"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    skill_node_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("skill_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    mastery_probability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    distinct_contexts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    model_version: Mapped[str] = mapped_column(String(32), default="0.1.0", nullable=False)


class ErrorPattern(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recurring learner error, prioritised by impact on meaning."""

    __tablename__ = "error_patterns"
    __table_args__ = (
        UniqueConstraint("user_id", "taxonomy_code", name="uq_error_patterns_user_code"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    taxonomy_code: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_description: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_priority: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    blocks_meaning: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[ErrorStatus] = mapped_column(
        enum_column(ErrorStatus, "error_status"), default=ErrorStatus.ACTIVE, nullable=False
    )
    examples: Mapped[list[Any]] = mapped_column(JSONB(), default=list, nullable=False)


class FeedbackReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A learner saying a verdict was wrong.

    `docs/AI_TUTOR_BEHAVIOR.md` positions AI judgement as an accelerator
    rather than an authority. That is a claim about how the product behaves,
    and it needs somewhere for the disagreement to go.

    One per attempt, enforced here rather than in the service: reporting the
    same thing five times is one complaint, and letting it repeat would turn
    the confidence reduction it causes into a way to zero an observation out.

    ``evaluator_id`` is copied from the attempt at report time rather than
    joined at read time. The evaluator can be replaced, and the useful
    question later is which one produced the feedback somebody objected to --
    not which one is running now.
    """

    __tablename__ = "feedback_reports"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_feedback_reports_attempt"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: From a closed set. Free text alone cannot be counted, and a report
    #: nobody can count is a report nobody acts on.
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The learner explaining themselves, verbatim and optional.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
