"""Daily plans and the spaced review queue."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ..db.types import GUID, JSONB, UTCDateTime, enum_column, utcnow
from .enums import MemoryObjectType, PlanStatus, ReviewMode


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A day's plan. ``rationale`` stores the priority components that produced
    it so the UI can answer "why is this in today's plan?"."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("user_id", "plan_date", name="uq_plans_user_date"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_minutes: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    status: Mapped[PlanStatus] = mapped_column(
        enum_column(PlanStatus, "plan_status"), default=PlanStatus.DRAFT, nullable=False
    )
    rationale: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), default="0.1.0", nullable=False)

    items: Mapped[list[PlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanItem.sequence"
    )


class PlanItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "plan_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "sequence", name="uq_plan_items_plan_sequence"),
        CheckConstraint("estimated_minutes > 0", name="estimated_minutes_positive"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    activity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_codes: Mapped[list[Any]] = mapped_column(JSONB(), default=list, nullable=False)
    priority_components: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), default=dict, nullable=False
    )

    plan: Mapped[Plan] = relationship(back_populates="items")


class ReviewQueueItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One memory object in one retrieval mode.

    Recognition, recall, listening, and production are scheduled separately;
    knowing a word by sight does not mean it is available for production.
    """

    __tablename__ = "review_queue"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "memory_object_type",
            "memory_object_key",
            "review_mode",
            name="uq_review_queue_object_mode",
        ),
        CheckConstraint("stability >= 0", name="stability_non_negative"),
        CheckConstraint("difficulty >= 0 AND difficulty <= 1", name="difficulty_bounded"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_object_type: Mapped[MemoryObjectType] = mapped_column(
        enum_column(MemoryObjectType, "memory_object_type"), nullable=False
    )
    memory_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    review_mode: Mapped[ReviewMode] = mapped_column(
        enum_column(ReviewMode, "review_mode"), nullable=False
    )
    due_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    stability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    difficulty: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    lapses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scheduler_version: Mapped[str] = mapped_column(String(32), default="0.1.0", nullable=False)
