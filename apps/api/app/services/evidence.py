"""Record evidence and derive mastery from it.

`skill_states` is a cache of what `evidence_events` already imply. Nothing in
the application may write mastery directly; it is always recomputed from raw
evidence, so the model can be replaced without invalidating history.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.types import utcnow
from ..learning.evidence import (
    DEFAULT_CONFIG,
    MODEL_VERSION,
    MasteryModelConfig,
    MasteryResult,
    Observation,
    compute_mastery,
)
from ..models.enums import EvidenceType
from ..models.learning import EvidenceEvent, SkillState


def record_evidence(
    session: Session,
    *,
    user_id: uuid.UUID,
    skill_node_id: uuid.UUID,
    evidence_type: EvidenceType,
    score: float,
    attempt_id: uuid.UUID | None = None,
    weight: float = 1.0,
    difficulty: float = 0.5,
    confidence: float = 1.0,
    independence: float = 1.0,
    novelty: float = 1.0,
    context_key: str | None = None,
    occurred_at: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> EvidenceEvent:
    """Append one immutable observation.

    Evidence events are never updated or deleted in normal operation; a
    correction is a new event, not an edit.
    """
    event = EvidenceEvent(
        user_id=user_id,
        skill_node_id=skill_node_id,
        attempt_id=attempt_id,
        evidence_type=evidence_type,
        score=score,
        weight=weight,
        difficulty=difficulty,
        confidence=confidence,
        independence=independence,
        novelty=novelty,
        context_key=context_key,
        occurred_at=occurred_at or utcnow(),
        metadata_json=dict(metadata or {}),
    )
    session.add(event)
    session.flush()
    return event


def _to_observation(event: EvidenceEvent) -> Observation:
    return Observation(
        evidence_type=event.evidence_type,
        score=event.score,
        occurred_at=event.occurred_at,
        weight=event.weight,
        difficulty=event.difficulty,
        confidence=event.confidence,
        independence=event.independence,
        novelty=event.novelty,
        context_key=event.context_key,
    )


def recompute_skill_state(
    session: Session,
    *,
    user_id: uuid.UUID,
    skill_node_id: uuid.UUID,
    now: datetime | None = None,
    config: MasteryModelConfig = DEFAULT_CONFIG,
) -> SkillState:
    """Rebuild one skill state from its full evidence history."""
    events = (
        session.execute(
            select(EvidenceEvent)
            .where(
                EvidenceEvent.user_id == user_id,
                EvidenceEvent.skill_node_id == skill_node_id,
            )
            .order_by(EvidenceEvent.occurred_at)
        )
        .scalars()
        .all()
    )

    result = compute_mastery(
        [_to_observation(event) for event in events], now=now or utcnow(), config=config
    )

    state = session.get(SkillState, (user_id, skill_node_id))
    if state is None:
        state = SkillState(user_id=user_id, skill_node_id=skill_node_id)
        session.add(state)

    _apply(state, result)
    session.flush()
    return state


def _apply(state: SkillState, result: MasteryResult) -> None:
    state.mastery_probability = result.mastery_probability
    state.confidence = result.confidence
    state.stability = result.stability
    state.evidence_count = result.evidence_count
    state.distinct_contexts = result.distinct_contexts
    state.last_observed_at = result.last_observed_at
    state.model_version = MODEL_VERSION


def recompute_all_skill_states(
    session: Session,
    *,
    user_id: uuid.UUID,
    now: datetime | None = None,
    config: MasteryModelConfig = DEFAULT_CONFIG,
) -> list[SkillState]:
    """Recompute every skill this learner has evidence for.

    Used after a diagnostic completes and whenever the model version changes.
    Confidence decays with time, so stored states drift out of date even when no
    new evidence arrives; a scheduled refresh will own that in Milestone 2.
    """
    skill_ids = (
        session.execute(
            select(EvidenceEvent.skill_node_id).where(EvidenceEvent.user_id == user_id).distinct()
        )
        .scalars()
        .all()
    )

    return [
        recompute_skill_state(
            session, user_id=user_id, skill_node_id=skill_id, now=now, config=config
        )
        for skill_id in skill_ids
    ]
