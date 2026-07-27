"""Versioned curriculum models.

A curriculum version is immutable once published. Generated and scored objects
reference the version they were produced against so historical evidence stays
interpretable (`docs/ARCHITECTURE.md`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from ..db.types import GUID, JSONB, UTCDateTime, enum_column
from .enums import CefrLevel, CurriculumStatus, SkillDomain, SkillRelation


class CurriculumVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "curriculum_versions"
    __table_args__ = (
        UniqueConstraint("semantic_version", name="uq_curriculum_versions_semantic_version"),
    )

    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[CurriculumStatus] = mapped_column(
        enum_column(CurriculumStatus, "curriculum_status"),
        default=CurriculumStatus.DRAFT,
        nullable=False,
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)

    skill_nodes: Mapped[list[SkillNode]] = relationship(
        back_populates="curriculum_version", cascade="all, delete-orphan"
    )

    @property
    def is_immutable(self) -> bool:
        return self.status in (CurriculumStatus.PUBLISHED, CurriculumStatus.RETIRED)


class SkillNode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A trackable competency. ``key`` is stable across curriculum versions."""

    __tablename__ = "skill_nodes"
    __table_args__ = (
        UniqueConstraint("curriculum_version_id", "key", name="uq_skill_nodes_version_key"),
    )

    curriculum_version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("curriculum_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    domain: Mapped[SkillDomain] = mapped_column(
        enum_column(SkillDomain, "skill_domain"), nullable=False
    )
    subdomain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cefr_min: Mapped[CefrLevel] = mapped_column(
        enum_column(CefrLevel, "cefr_level"), nullable=False
    )
    cefr_max: Mapped[CefrLevel] = mapped_column(
        enum_column(CefrLevel, "cefr_level"), nullable=False
    )
    difficulty: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB(), default=dict, nullable=False)

    curriculum_version: Mapped[CurriculumVersion] = relationship(back_populates="skill_nodes")
    objectives: Mapped[list[LearningObjective]] = relationship(
        back_populates="skill_node", cascade="all, delete-orphan"
    )


class SkillEdge(UUIDPrimaryKeyMixin, Base):
    """Typed relation in the skill graph (prerequisite, supports, ...)."""

    __tablename__ = "skill_edges"
    __table_args__ = (
        UniqueConstraint("from_skill_id", "to_skill_id", "relation", name="uq_skill_edges_triple"),
    )

    from_skill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("skill_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_skill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("skill_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation: Mapped[SkillRelation] = mapped_column(
        enum_column(SkillRelation, "skill_relation"), nullable=False
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


class LearningObjective(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A can-do statement plus the evidence required to consider it supported."""

    __tablename__ = "learning_objectives"
    __table_args__ = (
        UniqueConstraint("skill_node_id", "key", name="uq_learning_objectives_node_key"),
    )

    skill_node_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("skill_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    can_do: Mapped[str] = mapped_column(Text, nullable=False)
    cefr_level: Mapped[CefrLevel] = mapped_column(
        enum_column(CefrLevel, "cefr_level"), nullable=False
    )
    min_contexts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    evidence_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), default=dict, nullable=False
    )

    skill_node: Mapped[SkillNode] = relationship(back_populates="objectives")
