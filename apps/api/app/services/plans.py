"""Build, persist, and retrieve a learner's daily plan.

Candidates are derived from what the system actually knows: skill states from
the diagnostic, due review items, and recurring error patterns. Nothing is
invented — if a learner has no evidence yet, the plan says so instead of
fabricating a schedule.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..curriculum.loader import active_curriculum_version
from ..curriculum.study import StudyUnit
from ..db.types import utcnow
from ..errors import CurriculumNotLoadedError, PlanNotFoundError
from ..learning import taxonomy
from ..learning.mastery import MasteryThresholds, classify_status
from ..learning.planning import (
    ENGINE_VERSION,
    ActivityKind,
    Candidate,
    SessionTemplate,
    build_plan,
    explain,
)
from ..learning.planning import (
    Plan as ComputedPlan,
)
from ..learning.skill_graph import Edge, downstream_reach
from ..models.curriculum import SkillEdge, SkillNode
from ..models.enums import PlanStatus, SkillDomain, SkillRelation
from ..models.identity import LearnerProfile
from ..models.learning import ErrorPattern, SkillState
from ..models.planning import Plan, PlanItem, ReviewQueueItem
from . import activities

#: How long each kind of activity is assumed to take. Replaced by real
#: activity durations when the `activities` table lands in Milestone 3.
NOMINAL_MINUTES = {
    ActivityKind.REVIEW: 8,
    ActivityKind.INPUT: 10,
    ActivityKind.STUDY: 8,
    ActivityKind.OUTPUT: 10,
    ActivityKind.SPEAKING: 6,
    ActivityKind.REFLECTION: 4,
}

#: Which activity kind best exercises each domain.
DOMAIN_KINDS = {
    SkillDomain.LISTENING: ActivityKind.INPUT,
    SkillDomain.READING: ActivityKind.INPUT,
    SkillDomain.SPOKEN_PRODUCTION: ActivityKind.SPEAKING,
    SkillDomain.SPOKEN_INTERACTION: ActivityKind.SPEAKING,
    SkillDomain.PRONUNCIATION: ActivityKind.SPEAKING,
    SkillDomain.WRITTEN_PRODUCTION: ActivityKind.OUTPUT,
    SkillDomain.WRITTEN_INTERACTION: ActivityKind.OUTPUT,
    SkillDomain.MEDIATION: ActivityKind.OUTPUT,
    SkillDomain.VOCABULARY: ActivityKind.STUDY,
    SkillDomain.GRAMMAR: ActivityKind.STUDY,
    SkillDomain.DISCOURSE: ActivityKind.STUDY,
    SkillDomain.PRAGMATICS: ActivityKind.STUDY,
    SkillDomain.FLUENCY: ActivityKind.SPEAKING,
    SkillDomain.LEARNING_STRATEGIES: ActivityKind.REFLECTION,
}

#: A review is fully urgent once this many days overdue.
FULL_URGENCY_DAYS = 3.0


def get_or_create_today(session: Session, user_id: uuid.UUID, *, on: date | None = None) -> Plan:
    """Return today's plan, generating it on first request.

    Idempotent per day: opening the dashboard twice must not produce two
    different plans, or the learner cannot trust what they see.
    """
    plan_date = on or utcnow().date()
    existing = session.execute(
        select(Plan).where(Plan.user_id == user_id, Plan.plan_date == plan_date)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return generate_plan(session, user_id, on=plan_date)


def get_plan(session: Session, user_id: uuid.UUID, plan_id: uuid.UUID) -> Plan:
    """Fetch a plan scoped to its owner; another learner's is indistinguishable."""
    plan = session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == user_id)
    ).scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError()
    return plan


def generate_plan(
    session: Session,
    user_id: uuid.UUID,
    *,
    on: date | None = None,
    replace_existing: bool = False,
) -> Plan:
    """Generate and persist a plan for one day."""
    plan_date = on or utcnow().date()
    profile = session.get(LearnerProfile, user_id)
    minutes = profile.daily_minutes if profile else 40

    existing = session.execute(
        select(Plan).where(Plan.user_id == user_id, Plan.plan_date == plan_date)
    ).scalar_one_or_none()
    if existing is not None:
        if not replace_existing:
            return existing
        for item in list(existing.items):
            session.delete(item)
        session.delete(existing)
        session.flush()

    candidates = collect_candidates(session, user_id)
    computed = build_plan(candidates, requested_minutes=minutes)

    plan = Plan(
        user_id=user_id,
        plan_date=plan_date,
        requested_minutes=minutes,
        status=PlanStatus.ACTIVE if computed.items else PlanStatus.DRAFT,
        engine_version=ENGINE_VERSION,
        rationale={
            "template_minutes": SessionTemplate.for_minutes(minutes).minutes,
            "candidates_considered": len(candidates),
            "total_minutes": computed.total_minutes,
            "has_receptive": computed.has_receptive,
            "has_productive": computed.has_productive,
            "unmet_constraints": list(computed.unmet_constraints),
        },
    )
    session.add(plan)
    session.flush()

    for planned in computed.items:
        session.add(
            PlanItem(
                plan_id=plan.id,
                sequence=planned.sequence,
                activity_key=planned.candidate.activity_key,
                activity_type=planned.candidate.activity_type,
                estimated_minutes=planned.candidate.estimated_minutes,
                reason_codes=[code.value for code in planned.scored.reason_codes],
                # Every component is stored, including the ones that scored
                # zero: "why not something else?" needs them too.
                priority_components={
                    "priority": planned.scored.priority,
                    "slot": planned.slot,
                    "kind": planned.candidate.kind,
                    "skill_key": planned.candidate.skill_key,
                    "domain": planned.candidate.domain.value,
                    "title": planned.candidate.title,
                    "explanation": explain(planned),
                    "components": {
                        name: round(value, 6) for name, value in planned.scored.components.items()
                    },
                },
            )
        )

    session.flush()
    return plan


def collect_candidates(session: Session, user_id: uuid.UUID) -> list[Candidate]:
    """Derive today's candidate activities from stored learner state."""
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()

    thresholds = MasteryThresholds.from_metadata(version.metadata_json)
    now = utcnow()

    nodes = {
        node.id: node
        for node in session.execute(
            select(SkillNode).where(SkillNode.curriculum_version_id == version.id)
        ).scalars()
    }
    states = {
        state.skill_node_id: state
        for state in session.execute(
            select(SkillState).where(SkillState.user_id == user_id)
        ).scalars()
    }
    # How much each skill gates, from the authored graph. Computed once for
    # the whole plan rather than per candidate: it depends only on the
    # curriculum, not on the learner.
    reach = _gating_power(session, nodes)

    candidates: list[Candidate] = []

    # 1. Due reviews — the most time-sensitive item a plan can carry.
    for review in session.execute(
        select(ReviewQueueItem).where(ReviewQueueItem.user_id == user_id)
    ).scalars():
        overdue_days = (now - review.due_at).total_seconds() / 86400.0
        if overdue_days < 0:
            continue
        candidates.append(
            Candidate(
                activity_key=f"review:{review.memory_object_key}:{review.review_mode.value}",
                activity_type="review",
                kind=ActivityKind.REVIEW,
                skill_key=review.memory_object_key,
                domain=SkillDomain.VOCABULARY,
                estimated_minutes=NOMINAL_MINUTES[ActivityKind.REVIEW],
                title=f"Review: {review.memory_object_key}",
                due_pressure=min(1.0, 0.4 + overdue_days / FULL_URGENCY_DAYS),
                days_since_practised=(
                    (now - review.last_reviewed_at).total_seconds() / 86400.0
                    if review.last_reviewed_at
                    else 999.0
                ),
            )
        )

    # 2. Error patterns — a repeated mistake outranks new material.
    #    Where a study unit drills the feature that went wrong, the candidate
    #    points at that unit: an error the learner can act on beats a reminder
    #    that they keep getting something wrong.
    for pattern in session.execute(
        select(ErrorPattern).where(ErrorPattern.user_id == user_id)
    ).scalars():
        remedy = _study_for_error(pattern.taxonomy_code)
        feature = taxonomy.get(pattern.taxonomy_code)

        if remedy is not None:
            error_key = activities.study_key_for(remedy)
            error_type = activities.STUDY_TYPE
            error_skill = remedy.skill_key
            error_minutes = remedy.minutes
            error_title = remedy.title
        else:
            error_key = f"error:{pattern.taxonomy_code}"
            error_type = "error_practice"
            error_skill = pattern.taxonomy_code
            error_minutes = NOMINAL_MINUTES[ActivityKind.STUDY]
            error_title = pattern.canonical_description

        candidates.append(
            Candidate(
                activity_key=error_key,
                activity_type=error_type,
                kind=ActivityKind.STUDY,
                skill_key=error_skill,
                domain=feature.domain if feature else SkillDomain.GRAMMAR,
                estimated_minutes=error_minutes,
                title=error_title,
                error_pressure=min(1.0, pattern.current_priority),
                is_openable=remedy is not None,
                days_since_practised=(now - pattern.last_seen_at).total_seconds() / 86400.0,
            )
        )

    # 3. Skill practice, one candidate per observed or adjacent skill.
    for node_id, node in nodes.items():
        state = states.get(node_id)
        kind = DOMAIN_KINDS.get(node.domain, ActivityKind.STUDY)
        status = classify_status(
            mastery_probability=state.mastery_probability if state else 0.0,
            confidence=state.confidence if state else 0.0,
            distinct_contexts=state.distinct_contexts if state else 0,
            evidence_count=state.evidence_count if state else 0,
            thresholds=thresholds,
        )

        # A skill with no evidence at all is only worth scheduling if it sits
        # at or near where the learner is working; otherwise the plan would
        # fill with C2 material for an A1 learner.
        if state is None and node.difficulty > 0.5:
            continue

        # Prefer a real, openable activity over an abstract skill placeholder.
        # A plan item a learner cannot start is worse than no plan item.
        openable = _pick_activity(node.key, kind)

        if openable is not None:
            skill_key_for_item = openable.activity_key
            skill_type = openable.activity_type
            skill_minutes = openable.minutes
            skill_title = openable.title
        else:
            skill_key_for_item = f"skill:{node.key}"
            skill_type = "skill_practice"
            skill_minutes = NOMINAL_MINUTES[kind]
            skill_title = node.title

        candidates.append(
            Candidate(
                activity_key=skill_key_for_item,
                activity_type=skill_type,
                kind=kind,
                skill_key=node.key,
                domain=node.domain,
                estimated_minutes=skill_minutes,
                title=skill_title,
                mastery_probability=state.mastery_probability if state else 0.0,
                confidence=state.confidence if state else 0.0,
                status=status,
                is_openable=openable is not None,
                has_evidence=bool(state and state.evidence_count > 0),
                prerequisite_weakness=_prerequisite_weakness(node, state, reach),
                days_since_practised=(
                    (now - state.last_observed_at).total_seconds() / 86400.0
                    if state and state.last_observed_at
                    else 999.0
                ),
            )
        )

    # 4. Reflection always fits, and the templates reserve time for it.
    candidates.append(
        Candidate(
            activity_key="reflect:daily",
            activity_type="reflection",
            kind=ActivityKind.REFLECTION,
            skill_key="strategies.reflection",
            domain=SkillDomain.LEARNING_STRATEGIES,
            estimated_minutes=NOMINAL_MINUTES[ActivityKind.REFLECTION],
            title="Review your feedback",
            # Not a competency: it must not be scored as one.
            targets_a_skill=False,
        )
    )

    return candidates


@dataclass(frozen=True)
class _Openable:
    """A concrete activity a plan item can point at."""

    activity_key: str
    activity_type: str
    title: str
    minutes: int


def _pick_activity(skill_key: str, kind: str) -> _Openable | None:
    """The activity that best fills this slot for this skill, if one exists.

    One kind, one source. A `study` slot must not be filled with a reading
    text just because a text happens to exist for the skill — the session
    template asks for focused study there, and silently substituting input
    would quietly dismantle the receptive/productive balance the template is
    enforcing.

    Ties break towards the shortest, then the lowest key, so the same learner
    state always produces the same plan.
    """
    if kind == ActivityKind.INPUT:
        # Reading and listening both fill the input slot, and a skill key
        # belongs to one or the other, so checking both is unambiguous rather
        # than a preference.
        texts = activities.texts_for_skill(skill_key)
        if texts:
            text = min(texts, key=lambda item: (item.minutes, item.key))
            return _Openable(
                activity_key=activities.activity_key_for(text),
                activity_type=activities.READING_TYPE,
                title=text.title,
                minutes=text.minutes,
            )
        clips = activities.clips_for_skill(skill_key)
        if clips:
            clip = min(clips, key=lambda item: (item.minutes, item.key))
            return _Openable(
                activity_key=activities.listening_key_for(clip),
                activity_type=activities.LISTENING_TYPE,
                title=clip.title,
                minutes=clip.minutes,
            )
        return None

    if kind == ActivityKind.STUDY:
        units = activities.study_for_skill(skill_key)
        if units:
            unit = min(units, key=lambda item: (item.minutes, item.key))
            return _Openable(
                activity_key=activities.study_key_for(unit),
                activity_type=activities.STUDY_TYPE,
                title=unit.title,
                minutes=unit.minutes,
            )
        return None

    if kind == ActivityKind.OUTPUT:
        tasks = activities.tasks_for_skill(skill_key)
        if tasks:
            task = min(tasks, key=lambda item: (item.minutes, item.key))
            return _Openable(
                activity_key=activities.writing_key_for(task),
                activity_type=activities.WRITING_TYPE,
                title=task.title,
                minutes=task.minutes,
            )
        return None

    if kind == ActivityKind.SPEAKING:
        spoken = activities.speaking_for_skill(skill_key)
        if spoken:
            prompt = min(spoken, key=lambda item: (item.minutes, item.key))
            return _Openable(
                activity_key=activities.speaking_key_for(prompt),
                activity_type=activities.SPEAKING_TYPE,
                title=prompt.title,
                minutes=prompt.minutes,
            )
        return None

    # Reflection has no activity behind it yet. Returning None keeps the plan
    # item honest rather than linking it somewhere wrong.
    return None


def _study_for_error(taxonomy_code: str) -> StudyUnit | None:
    """A study unit that drills the feature this error names, if one exists.

    Legacy `item.<skill>` codes match nothing, by design: they do not name a
    feature, so there is no unit that can honestly claim to fix them.
    """
    units = activities.study_for_feature(taxonomy_code)
    if not units:
        return None
    return min(units, key=lambda unit: (unit.minutes, unit.key))


def _gating_power(session: Session, nodes: dict[uuid.UUID, SkillNode]) -> dict[str, float]:
    """How much each skill gates, walked from the stored prerequisite edges.

    Only `prerequisite` edges count. `supports` is recorded because it is
    true, and it is deliberately excluded here: a skill that merely helps
    another is not holding it back, and letting it score as though it were
    would quietly reinstate the guesswork this replaces.
    """
    if not nodes:
        return {}

    keys = {node.id: node.key for node in nodes.values()}
    rows = session.execute(
        select(SkillEdge).where(
            SkillEdge.from_skill_id.in_(keys),
            SkillEdge.relation == SkillRelation.PREREQUISITE,
        )
    ).scalars()

    edges = [
        Edge(source=keys[row.from_skill_id], target=keys[row.to_skill_id], weight=row.weight)
        for row in rows
        # An edge can point outside this curriculum version only if two
        # versions are loaded at once. Skipping is right: a plan built from
        # one version must not be shaped by another's dependencies.
        if row.from_skill_id in keys and row.to_skill_id in keys
    ]
    return dict(downstream_reach(edges, keys.values()))


def _prerequisite_weakness(
    node: SkillNode,
    state: SkillState | None,
    reach: dict[str, float],
) -> float:
    """How much this skill is holding others back.

    Two things multiplied: how weak the learner is at it, and how much it
    gates according to `curriculum/graph.yml`.

    The second factor used to be `1 - difficulty`, on the assumption that a
    lower-level skill blocks more. Within one domain that is nearly true;
    across domains it is not, and the assumption was invisible in the plan
    explanation. A2 vocabulary gates spoken and written production, and
    through them interaction and mediation. A2 pronunciation gates almost
    nothing, because the graph deliberately refuses to let intelligibility
    block production. The old proxy scored the two identically.

    A skill with no evidence scores zero, unchanged: "we have never looked"
    is not the same claim as "this is weak", and the uncertainty component
    already covers the first.
    """
    if state is None:
        return 0.0
    weakness = 1.0 - state.mastery_probability
    gates = reach.get(node.key, 0.0)
    return max(0.0, min(1.0, weakness * gates))


def domain_shares(session: Session, user_id: uuid.UUID, *, days: int = 7) -> dict[str, float]:
    """Proportion of recent plan items per domain, for the balance component."""
    since = utcnow().date() - timedelta(days=days)
    plans = session.execute(
        select(Plan).where(Plan.user_id == user_id, Plan.plan_date >= since)
    ).scalars()

    counts: dict[str, int] = {}
    total = 0
    for plan in plans:
        for item in plan.items:
            domain = str(item.priority_components.get("domain", ""))
            if not domain:
                continue
            counts[domain] = counts.get(domain, 0) + 1
            total += 1

    if total == 0:
        return {}
    return {domain: count / total for domain, count in counts.items()}


def complete_plan(session: Session, user_id: uuid.UUID, plan_id: uuid.UUID) -> Plan:
    plan = get_plan(session, user_id, plan_id)
    plan.status = PlanStatus.COMPLETED
    session.flush()
    return plan


__all__ = [
    "ComputedPlan",
    "collect_candidates",
    "complete_plan",
    "domain_shares",
    "generate_plan",
    "get_or_create_today",
    "get_plan",
]
