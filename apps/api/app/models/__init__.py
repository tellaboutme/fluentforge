"""SQLAlchemy models.

Importing this package registers every table on ``Base.metadata``; Alembic
autogenerate and the test fixtures both depend on that side effect.
"""

from .curriculum import CurriculumVersion, LearningObjective, SkillEdge, SkillNode
from .enums import (
    CefrLevel,
    CurriculumStatus,
    ErrorStatus,
    EvidenceType,
    MemoryObjectType,
    PlanReasonCode,
    PlanStatus,
    ReviewMode,
    SessionStatus,
    SkillDomain,
    SkillRelation,
    UserStatus,
)
from .identity import LearnerProfile, User
from .learning import Attempt, ErrorPattern, EvidenceEvent, LearningSession, SkillState
from .planning import Plan, PlanItem, ReviewQueueItem

__all__ = [
    "Attempt",
    "CefrLevel",
    "CurriculumStatus",
    "CurriculumVersion",
    "ErrorPattern",
    "ErrorStatus",
    "EvidenceEvent",
    "EvidenceType",
    "LearnerProfile",
    "LearningObjective",
    "LearningSession",
    "MemoryObjectType",
    "Plan",
    "PlanItem",
    "PlanReasonCode",
    "PlanStatus",
    "ReviewMode",
    "ReviewQueueItem",
    "SessionStatus",
    "SkillDomain",
    "SkillEdge",
    "SkillNode",
    "SkillRelation",
    "SkillState",
    "User",
    "UserStatus",
]
