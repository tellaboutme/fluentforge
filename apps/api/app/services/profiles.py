"""Build the learner profile view: per-skill estimates, never one overall level."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..curriculum.loader import active_curriculum_version
from ..errors import CurriculumNotLoadedError, ProfileNotFoundError, UnknownTrackError
from ..learning.mastery import (
    MasteryThresholds,
    cefr_estimate_for,
    classify_status,
)
from ..models.curriculum import SkillNode
from ..models.identity import LearnerProfile
from ..models.learning import SkillState
from ..schemas.profile import (
    DomainSummary,
    ProfileResponse,
    ProfileUpdateRequest,
    SkillEstimate,
)
from . import tracks
from .evidence import current_confidence


def get_profile(session: Session, user_id: uuid.UUID) -> LearnerProfile:
    profile = session.get(LearnerProfile, user_id)
    if profile is None:
        raise ProfileNotFoundError()
    return profile


def update_profile(
    session: Session, user_id: uuid.UUID, changes: ProfileUpdateRequest
) -> LearnerProfile:
    profile = get_profile(session, user_id)
    updates = changes.model_dump(exclude_unset=True)

    # Tracks are curriculum source, not an enum, so the check lives here
    # rather than in the schema. Rejecting an unknown key matters: a typo that
    # silently stored would leave the learner looking at a track name they
    # chose while their plan quietly fell back to general.
    track_key = updates.get("track_key")
    if track_key is not None and tracks.get(track_key) is None:
        raise UnknownTrackError(track_key)

    for field, value in updates.items():
        if value is not None:
            setattr(profile, field, value)
    session.flush()
    return profile


def build_profile_response(session: Session, user_id: uuid.UUID) -> ProfileResponse:
    """Assemble the profile view for one learner.

    Every skill in the active curriculum appears, including unobserved ones:
    knowing what has *not* been assessed is part of an honest profile.
    """
    profile = get_profile(session, user_id)

    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()

    thresholds = MasteryThresholds.from_metadata(version.metadata_json)

    nodes = (
        session.execute(
            select(SkillNode)
            .where(SkillNode.curriculum_version_id == version.id)
            .order_by(SkillNode.domain, SkillNode.cefr_min, SkillNode.key)
        )
        .scalars()
        .all()
    )

    states = {
        state.skill_node_id: state
        for state in session.execute(
            select(SkillState).where(SkillState.user_id == user_id)
        ).scalars()
    }

    skills: list[SkillEstimate] = []
    per_domain: dict[str, list[SkillEstimate]] = defaultdict(list)

    for node in nodes:
        state = states.get(node.id)
        mastery = state.mastery_probability if state else 0.0
        confidence = current_confidence(state)
        contexts = state.distinct_contexts if state else 0
        evidence_count = state.evidence_count if state else 0

        status = classify_status(
            mastery_probability=mastery,
            confidence=confidence,
            distinct_contexts=contexts,
            evidence_count=evidence_count,
            thresholds=thresholds,
        )

        estimate = SkillEstimate(
            skill_key=node.key,
            domain=node.domain,
            title=node.title,
            cefr_estimate=cefr_estimate_for(status, node.cefr_max),
            mastery_probability=mastery,
            confidence=confidence,
            evidence_count=evidence_count,
            distinct_contexts=contexts,
            last_observed_at=state.last_observed_at if state else None,
            status=status,
        )
        skills.append(estimate)
        per_domain[node.domain.value].append(estimate)

    summaries = [
        DomainSummary(
            domain=entries[0].domain,
            tracked_skills=len(entries),
            observed_skills=sum(1 for entry in entries if entry.evidence_count > 0),
            mean_confidence=round(sum(entry.confidence for entry in entries) / len(entries), 4),
        )
        for entries in per_domain.values()
    ]

    return ProfileResponse(
        user_id=profile.user_id,
        display_name=profile.display_name,
        target_level=profile.target_level,
        daily_minutes=profile.daily_minutes,
        explanation_language=profile.explanation_language,
        timezone=profile.timezone,
        goals=profile.goals,
        interests=profile.interests,
        track_key=profile.track_key,
        # Null rather than the raw key when the curriculum no longer defines
        # it. A client that showed the key would present a machine identifier
        # as the learner's chosen purpose.
        track_name=(chosen.name if (chosen := tracks.get(profile.track_key)) else None),
        curriculum_version=version.semantic_version,
        skills=skills,
        domain_summaries=sorted(summaries, key=lambda item: item.domain.value),
    )
