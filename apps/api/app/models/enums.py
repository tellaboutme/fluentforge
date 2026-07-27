"""Domain enumerations shared by models, schemas, and services.

Values are the stable machine codes persisted in the database. Never rename a
value without a migration; add new members instead.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String-valued enum.

    Written as an explicit ``str`` mixin rather than ``enum.StrEnum`` so the
    package remains importable on Python 3.10+ interpreters used in some CI
    and sandbox images. Behaviour is identical for our usage: values are always
    persisted and serialised via ``.value``.
    """

    def __str__(self) -> str:
        return str(self.value)


class CefrLevel(StrEnum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"

    @property
    def rank(self) -> int:
        return _CEFR_ORDER.index(self)


_CEFR_ORDER: tuple[CefrLevel, ...] = (
    CefrLevel.A1,
    CefrLevel.A2,
    CefrLevel.B1,
    CefrLevel.B2,
    CefrLevel.C1,
    CefrLevel.C2,
)


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class CurriculumStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class SkillDomain(StrEnum):
    """Top-level capability domains from `docs/PRODUCT_SPEC.md`."""

    LISTENING = "listening"
    SPOKEN_PRODUCTION = "spoken_production"
    SPOKEN_INTERACTION = "spoken_interaction"
    PRONUNCIATION = "pronunciation"
    READING = "reading"
    WRITTEN_PRODUCTION = "written_production"
    WRITTEN_INTERACTION = "written_interaction"
    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"
    FLUENCY = "fluency"
    DISCOURSE = "discourse"
    PRAGMATICS = "pragmatics"
    MEDIATION = "mediation"
    LEARNING_STRATEGIES = "learning_strategies"


class SkillRelation(StrEnum):
    PREREQUISITE = "prerequisite"
    SUPPORTS = "supports"
    CONFUSABLE = "confusable"
    TRANSFER = "transfer"


class EvidenceType(StrEnum):
    """Evidence strength differs by type; see `docs/ASSESSMENT_ENGINE.md`."""

    RECOGNITION = "recognition"
    CONTROLLED_RECALL = "controlled_recall"
    CONTEXTUAL_PRODUCTION = "contextual_production"
    COMPREHENSION = "comprehension"
    INTERACTION = "interaction"
    TRANSFER = "transfer"
    BENCHMARK = "benchmark"
    SELF_REPORT = "self_report"


class ReviewMode(StrEnum):
    """Memory states are tracked separately per retrieval mode."""

    MEANING_RECOGNITION = "meaning_recognition"
    FORM_RECOGNITION = "form_recognition"
    FORM_RECALL = "form_recall"
    MEANING_RECALL = "meaning_recall"
    LISTENING_RECOGNITION = "listening_recognition"
    PRONUNCIATION_PRODUCTION = "pronunciation_production"
    CONTEXTUAL_PRODUCTION = "contextual_production"


class MemoryObjectType(StrEnum):
    LEXICAL_ENTRY = "lexical_entry"
    PHRASE = "phrase"
    SKILL_NODE = "skill_node"
    ERROR_PATTERN = "error_pattern"


class SessionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ErrorStatus(StrEnum):
    ACTIVE = "active"
    IMPROVING = "improving"
    RESOLVED = "resolved"


class PlanReasonCode(StrEnum):
    """Reason codes are logged per plan item so plans stay explainable."""

    DUE_REVIEW = "DUE_REVIEW"
    EXPECTED_GAIN = "EXPECTED_GAIN"
    WEAK_PREREQUISITE = "WEAK_PREREQUISITE"
    GOAL_RELEVANCE = "GOAL_RELEVANCE"
    UNCERTAINTY = "UNCERTAINTY"
    SKILL_BALANCE = "SKILL_BALANCE"
    ERROR_FOLLOW_UP = "ERROR_FOLLOW_UP"
    MODALITY_DIVERSITY = "MODALITY_DIVERSITY"
    TRANSFER_CHECK = "TRANSFER_CHECK"
