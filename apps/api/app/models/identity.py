"""Identity and learner preference models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ..db.types import GUID, JSONB, UTCDateTime, enum_column
from .enums import CefrLevel, UserStatus


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A local account. Credentials never leave the API service."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, "user_status"), default=UserStatus.ACTIVE, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    profile: Mapped[LearnerProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class LearnerProfile(TimestampMixin, Base):
    """Goals, constraints, and preferences that drive planning."""

    __tablename__ = "learner_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    explanation_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    target_level: Mapped[CefrLevel] = mapped_column(
        enum_column(CefrLevel, "cefr_level"), default=CefrLevel.C2, nullable=False
    )
    #: Which track the learner is following. A plain string rather than an
    #: enum because tracks are versioned curriculum source: adding one must
    #: be an authoring action, not a schema migration. An unknown key falls
    #: back to `general` at read time rather than raising -- dropping a track
    #: from the curriculum must not lock a learner out of their own profile.
    track_key: Mapped[str] = mapped_column(String(64), default="general", nullable=False)

    goals: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)
    interests: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)
    accessibility_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), default=dict, nullable=False
    )
    privacy_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), default=dict, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="profile")
