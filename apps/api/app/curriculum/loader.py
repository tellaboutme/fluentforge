"""Load parsed curriculum source into the database.

Published versions are immutable. Editing curriculum source and reloading
produces a new version rather than rewriting history, so evidence collected
against an older version stays interpretable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.types import utcnow
from ..models.curriculum import CurriculumVersion, LearningObjective, SkillEdge, SkillNode
from ..models.enums import CefrLevel, CurriculumStatus
from .graph import ParsedGraph, parse_graph
from .parser import ParsedCurriculum, ParsedObjective, parse_curriculum


class ImmutableCurriculumError(RuntimeError):
    """Raised when published curriculum source has been modified in place."""


@dataclass(frozen=True)
class LoadResult:
    version: CurriculumVersion
    created: bool
    skill_nodes: int
    objectives: int
    edges: int


def _difficulty_for(level: CefrLevel) -> float:
    """Map a CEFR band onto a 0..1 difficulty prior.

    Difficulty and CEFR are related but not identical (`CLAUDE.md`); this is a
    starting prior that evidence later refines, not a definition.
    """
    return round((level.rank + 0.5) / len(CefrLevel), 4)


def _build_nodes(version: CurriculumVersion, parsed: ParsedCurriculum) -> dict[str, SkillNode]:
    nodes: dict[str, SkillNode] = {}
    for objective in parsed.objectives:
        node = SkillNode(
            curriculum_version=version,
            key=objective.key,
            domain=objective.domain,
            subdomain=objective.subdomain,
            title=objective.title,
            description=objective.can_do,
            cefr_min=objective.level,
            cefr_max=objective.level,
            difficulty=_difficulty_for(objective.level),
            metadata_json={"source_level": objective.level.value},
        )
        node.objectives.append(_build_objective(objective))
        nodes[objective.key] = node
    return nodes


def _build_objective(parsed: ParsedObjective) -> LearningObjective:
    return LearningObjective(
        key=parsed.key,
        can_do=parsed.can_do,
        cefr_level=parsed.level,
        min_contexts=parsed.min_contexts,
        evidence_requirements={
            "evidence_types": [item.value for item in parsed.evidence_types],
            "min_contexts": parsed.min_contexts,
        },
    )


def _build_edges(graph: ParsedGraph, nodes: dict[str, SkillNode]) -> list[SkillEdge]:
    """Turn the authored graph into rows.

    Edges used to be derived here — level N in a domain depends on level N-1,
    every relation `prerequisite`, every weight 1.0. They are now read from
    `curriculum/graph.yml`, which carries relation and weight per edge and a
    stated reason for each claim. The reason is not persisted: it belongs to
    the source, which is versioned and hashed, and a column holding a
    paragraph nobody queries would be a worse home for it.
    """
    return [
        SkillEdge(
            from_skill_id=nodes[edge.source].id,
            to_skill_id=nodes[edge.target].id,
            relation=edge.relation,
            weight=edge.weight,
        )
        for edge in graph.edges
    ]


def load_curriculum(
    session: Session,
    curriculum_dir: Path,
    *,
    publish: bool = False,
) -> LoadResult:
    """Load curriculum source into the database.

    Idempotent: re-running with unchanged source returns the existing version
    without rewriting rows.

    Raises:
        CurriculumError: source data is invalid.
        ImmutableCurriculumError: a published version's source has changed.
    """
    parsed = parse_curriculum(curriculum_dir)
    # Parsed before anything is written: a graph that would mislead the
    # planner should stop the load, not survive it.
    graph = parse_graph(curriculum_dir, parsed.objectives)

    existing = session.execute(
        select(CurriculumVersion).where(
            CurriculumVersion.semantic_version == parsed.semantic_version
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.source_hash == parsed.source_hash:
            if publish and existing.status is CurriculumStatus.DRAFT:
                existing.status = CurriculumStatus.PUBLISHED
                existing.published_at = utcnow()
                session.flush()
            return LoadResult(
                version=existing,
                created=False,
                skill_nodes=len(existing.skill_nodes),
                objectives=sum(len(node.objectives) for node in existing.skill_nodes),
                edges=_count_edges(session, existing),
            )
        if existing.is_immutable:
            raise ImmutableCurriculumError(
                f"curriculum version {parsed.semantic_version} is {existing.status.value} "
                f"but its source changed (expected hash {existing.source_hash}, "
                f"got {parsed.source_hash}). Bump `version` in framework.yml instead."
            )
        _delete_version_contents(session, existing)
        session.delete(existing)
        session.flush()

    version = CurriculumVersion(
        semantic_version=parsed.semantic_version,
        source_hash=parsed.source_hash,
        status=CurriculumStatus.PUBLISHED if publish else CurriculumStatus.DRAFT,
        published_at=utcnow() if publish else None,
        metadata_json={
            "domains": sorted({obj.domain.value for obj in parsed.objectives}),
            "objective_count": len(parsed.objectives),
            # Thresholds live with the curriculum version so a change to them
            # cannot silently reinterpret evidence collected earlier.
            "mastery": parsed.framework.get("mastery", {}),
            "evidence_types": parsed.framework.get("evidence_types", []),
        },
    )
    session.add(version)

    nodes = _build_nodes(version, parsed)
    session.add_all(nodes.values())
    session.flush()

    edges = _build_edges(graph, nodes)
    session.add_all(edges)
    session.flush()

    return LoadResult(
        version=version,
        created=True,
        skill_nodes=len(nodes),
        objectives=len(parsed.objectives),
        edges=len(edges),
    )


def _count_edges(session: Session, version: CurriculumVersion) -> int:
    node_ids = [node.id for node in version.skill_nodes]
    if not node_ids:
        return 0
    return len(
        session.execute(select(SkillEdge.id).where(SkillEdge.from_skill_id.in_(node_ids)))
        .scalars()
        .all()
    )


def _delete_version_contents(session: Session, version: CurriculumVersion) -> None:
    """Remove edges before nodes: edges are not owned by the version row."""
    node_ids = [node.id for node in version.skill_nodes]
    if not node_ids:
        return
    edges = (
        session.execute(select(SkillEdge).where(SkillEdge.from_skill_id.in_(node_ids)))
        .scalars()
        .all()
    )
    for edge in edges:
        session.delete(edge)
    session.flush()


def active_curriculum_version(session: Session) -> CurriculumVersion | None:
    """The newest published version, falling back to the newest draft."""
    published = session.execute(
        select(CurriculumVersion)
        .where(CurriculumVersion.status == CurriculumStatus.PUBLISHED)
        .order_by(CurriculumVersion.published_at.desc())
    ).scalars()
    newest = next(iter(published), None)
    if newest is not None:
        return newest
    drafts = session.execute(
        select(CurriculumVersion).order_by(CurriculumVersion.created_at.desc())
    ).scalars()
    return next(iter(drafts), None)
