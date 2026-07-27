"""Schema-level invariants that protect the learning model."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.models.enums import (
    CefrLevel,
    EvidenceType,
    MemoryObjectType,
    ReviewMode,
)
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import EvidenceEvent, LearningSession, SkillState
from apps.api.app.models.planning import ReviewQueueItem

UTC = timezone.utc


def _user(session: Session, email: str = "a@example.com") -> User:
    user = User(email=email, password_hash="x")
    user.profile = LearnerProfile(display_name="A")
    session.add(user)
    session.commit()
    return user


def _skill_node_id(session: Session) -> uuid.UUID:
    from apps.api.app.models.curriculum import SkillNode

    return session.execute(select(SkillNode.id)).scalars().first()  # type: ignore[return-value]


def test_cefr_levels_are_ordered() -> None:
    ranks = [level.rank for level in CefrLevel]
    assert ranks == sorted(ranks)
    assert CefrLevel.A1.rank < CefrLevel.B1.rank < CefrLevel.C2.rank


def test_email_is_unique(db_session: Session) -> None:
    _user(db_session)
    db_session.add(User(email="a@example.com", password_hash="y"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_a_user_removes_their_profile(db_session: Session) -> None:
    user = _user(db_session)
    db_session.delete(user)
    db_session.commit()
    assert db_session.get(LearnerProfile, user.id) is None


def test_naive_datetimes_are_rejected(db_session: Session) -> None:
    """Timestamps must be explicit UTC; a naive value is a bug, not a default."""
    user = _user(db_session)
    db_session.add(LearningSession(user_id=user.id, started_at=datetime(2026, 1, 1, 12, 0, 0)))
    # SQLAlchemy wraps bind-parameter errors in StatementError.
    with pytest.raises(StatementError, match="naive datetime"):
        db_session.commit()


def test_timestamps_round_trip_as_utc(db_session: Session) -> None:
    user = _user(db_session)
    moment = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    db_session.add(LearningSession(user_id=user.id, started_at=moment))
    db_session.commit()

    stored = db_session.execute(select(LearningSession)).scalar_one()
    assert stored.started_at.tzinfo is not None
    assert stored.started_at == moment


def test_evidence_score_must_be_bounded(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    db_session.add(
        EvidenceEvent(
            user_id=user.id,
            skill_node_id=_skill_node_id(db_session),
            evidence_type=EvidenceType.RECOGNITION,
            score=1.5,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_evidence_confidence_must_be_bounded(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    db_session.add(
        EvidenceEvent(
            user_id=user.id,
            skill_node_id=_skill_node_id(db_session),
            evidence_type=EvidenceType.TRANSFER,
            score=0.5,
            confidence=-0.1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_valid_evidence_is_accepted(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    db_session.add(
        EvidenceEvent(
            user_id=user.id,
            skill_node_id=_skill_node_id(db_session),
            evidence_type=EvidenceType.CONTEXTUAL_PRODUCTION,
            score=0.8,
            confidence=0.6,
            independence=0.4,
            novelty=1.0,
            context_key="roleplay-cafe",
        )
    )
    db_session.commit()
    assert db_session.execute(select(EvidenceEvent)).scalar_one().independence == 0.4


def test_mastery_probability_must_be_bounded(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    db_session.add(
        SkillState(
            user_id=user.id,
            skill_node_id=_skill_node_id(db_session),
            mastery_probability=1.4,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_review_modes_are_scheduled_independently(db_session: Session) -> None:
    """Recognising a word and producing it are separate memory states."""
    user = _user(db_session)
    due = utcnow() + timedelta(days=1)
    for mode in (ReviewMode.MEANING_RECOGNITION, ReviewMode.CONTEXTUAL_PRODUCTION):
        db_session.add(
            ReviewQueueItem(
                user_id=user.id,
                memory_object_type=MemoryObjectType.LEXICAL_ENTRY,
                memory_object_key="arrange",
                review_mode=mode,
                due_at=due,
            )
        )
    db_session.commit()

    stored = db_session.execute(select(ReviewQueueItem)).scalars().all()
    assert len(stored) == 2
    assert {item.review_mode for item in stored} == {
        ReviewMode.MEANING_RECOGNITION,
        ReviewMode.CONTEXTUAL_PRODUCTION,
    }


def test_same_object_and_mode_cannot_be_queued_twice(db_session: Session) -> None:
    user = _user(db_session)
    for _ in range(2):
        db_session.add(
            ReviewQueueItem(
                user_id=user.id,
                memory_object_type=MemoryObjectType.LEXICAL_ENTRY,
                memory_object_key="arrange",
                review_mode=ReviewMode.FORM_RECALL,
                due_at=utcnow(),
            )
        )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_foreign_keys_are_enforced(db_session: Session) -> None:
    db_session.add(LearningSession(user_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        db_session.commit()
