"""The skill graph, as the learner sees it.

`curriculum/graph.yml` holds 119 authored claims about what depends on what,
each with a written reason, and until now the only thing that read them was
the planner. A learner could be told "this is in your plan because a
prerequisite is weak" and had no way to see the prerequisite, the claim, or
the reason.

That asymmetry is worth removing on its own terms. `docs/ADAPTIVE_ENGINE.md`
forbids an opaque priority score precisely so a learner can disagree with the
reasoning rather than merely receive it — and the graph is the largest piece
of reasoning in the product they could not inspect.

Two things this is careful about.

**It says the graph is judgement, not measurement.** 119 claims, each
defensible and none validated against learner outcomes. A map presented
without that caveat would read as a discovered structure, which it is not.
`caveats` is non-empty for the same reason the diagnostic report's is.

**It shows no level a learner has not earned.** `cefr_estimate` stays null
until a skill reaches `supported`, exactly as on the profile. A skill map is
a tempting place to quietly relax that, because a grid of blanks looks
unfinished — and a grid of invented levels would be worse.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from ..curriculum.loader import active_curriculum_version
from ..deps import CurrentUser, SessionDep
from ..errors import CurriculumNotLoadedError
from ..learning.mastery import (
    STATUS_UNOBSERVED,
    MasteryThresholds,
    cefr_estimate_for,
    classify_status,
)
from ..models.curriculum import SkillEdge, SkillNode
from ..models.enums import CefrLevel, SkillDomain, SkillRelation
from ..models.learning import SkillState

router = APIRouter(prefix="/profile", tags=["profile"])

#: Mastery below which a prerequisite is reported as holding something back.
#: Matches the mastery model's "supported" threshold: above it, the skill is
#: not what is in the way.
WEAK_BELOW = 0.70


class SkillNodeView(BaseModel):
    key: str
    title: str
    domain: SkillDomain
    level: CefrLevel
    status: str
    mastery_probability: float
    confidence: float
    evidence_count: int
    #: Null until the skill reaches `supported`. Clients render that as
    #: "needs evidence", never as a low level.
    cefr_estimate: CefrLevel | None
    #: Skills this one is holding back, named only when the learner is
    #: actually weak at it. Listing them regardless would tell a learner
    #: their strong skills are blocking things.
    blocking: list[str]
    #: Prerequisites of this skill that the learner is weak at. This is the
    #: answer to "why can I not get anywhere with this?".
    blocked_by: list[str]


class SkillEdgeView(BaseModel):
    source: str
    target: str
    relation: SkillRelation
    #: How strongly the claim is believed, not how important the skill is.
    weight: float


class SkillMap(BaseModel):
    nodes: list[SkillNodeView]
    edges: list[SkillEdgeView]
    #: Always non-empty, and clients must surface it. See the module
    #: docstring: the graph is expert judgement.
    caveats: list[str]


@router.get("/skill-map", response_model=SkillMap)
def read_skill_map(user: CurrentUser, session: SessionDep) -> SkillMap:
    """Every skill, its state, and what the graph says depends on what."""
    version = active_curriculum_version(session)
    if version is None:
        raise CurriculumNotLoadedError()

    thresholds = MasteryThresholds.from_metadata(version.metadata_json)
    nodes = {
        node.id: node
        for node in session.execute(
            select(SkillNode).where(SkillNode.curriculum_version_id == version.id)
        ).scalars()
    }
    states = {
        state.skill_node_id: state
        for state in session.execute(
            select(SkillState).where(SkillState.user_id == user.id)
        ).scalars()
    }

    edges = [
        edge
        for edge in session.execute(select(SkillEdge)).scalars()
        if edge.from_skill_id in nodes and edge.to_skill_id in nodes
    ]

    def mastery(node_id: uuid.UUID) -> float:
        state = states.get(node_id)
        return state.mastery_probability if state else 0.0

    weak = {node_id for node_id in nodes if mastery(node_id) < WEAK_BELOW}

    blocking: dict[str, list[str]] = {node.key: [] for node in nodes.values()}
    blocked_by: dict[str, list[str]] = {node.key: [] for node in nodes.values()}
    for edge in edges:
        if edge.relation is not SkillRelation.PREREQUISITE:
            # `supports` is real and never gates. Reporting it here would
            # tell a learner they are blocked by something that only helps.
            continue
        source, target = nodes[edge.from_skill_id], nodes[edge.to_skill_id]
        if edge.from_skill_id in weak:
            blocking[source.key].append(target.key)
            blocked_by[target.key].append(source.key)

    views: list[SkillNodeView] = []
    for node in nodes.values():
        state = states.get(node.id)
        status = classify_status(
            mastery_probability=state.mastery_probability if state else 0.0,
            confidence=state.confidence if state else 0.0,
            distinct_contexts=state.distinct_contexts if state else 0,
            evidence_count=state.evidence_count if state else 0,
            thresholds=thresholds,
        )
        views.append(
            SkillNodeView(
                key=node.key,
                title=node.title,
                domain=node.domain,
                level=node.cefr_min,
                status=status,
                mastery_probability=state.mastery_probability if state else 0.0,
                confidence=state.confidence if state else 0.0,
                evidence_count=state.evidence_count if state else 0,
                cefr_estimate=cefr_estimate_for(status, node.cefr_max),
                blocking=sorted(blocking[node.key]),
                blocked_by=sorted(blocked_by[node.key]),
            )
        )

    views.sort(key=lambda view: (view.level.rank, view.key))

    return SkillMap(
        nodes=views,
        edges=sorted(
            (
                SkillEdgeView(
                    source=nodes[edge.from_skill_id].key,
                    target=nodes[edge.to_skill_id].key,
                    relation=edge.relation,
                    weight=edge.weight,
                )
                for edge in edges
            ),
            key=lambda edge: (edge.source, edge.target, edge.relation.value),
        ),
        caveats=_caveats(views),
    )


def _caveats(views: list[SkillNodeView]) -> list[str]:
    """What a learner should not conclude from this map.

    Always non-empty. The first caveat is permanent and is the important
    one: a map drawn without it looks like a discovered structure rather
    than a set of authored claims.
    """
    caveats = [
        "The dependencies here are expert judgement, not measurement. Each one "
        "is defensible and none has been checked against how people actually "
        "learn, so treat a line between two skills as an argument rather than "
        "a finding.",
    ]

    unobserved = sum(1 for view in views if view.status == STATUS_UNOBSERVED)
    if unobserved:
        caveats.append(
            f"{unobserved} of {len(views)} skills have no evidence at all yet. "
            f"They are shown as unmeasured rather than as weak: nothing here "
            f"says you cannot do them."
        )

    if any(view.blocked_by for view in views):
        caveats.append(
            "A skill listed as blocked is one whose prerequisites you have not "
            "shown yet. It is a suggestion about order, not a rule about what "
            "you are allowed to attempt."
        )

    return caveats
