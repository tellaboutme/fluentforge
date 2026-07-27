"""Parse and validate the hand-authored skill graph in `curriculum/graph.yml`.

Edges used to be derived — level N in a domain depends on level N-1, and
nothing else. That is one true claim repeated 45 times. It cannot express
that vocabulary gates production, that interaction is listening and speaking
at once, or that pronunciation deliberately gates nothing.

This module reads the authored claims and refuses the graph outright if it
would mislead the planner. Each check exists because the failure it catches
is silent: a cycle makes two skills permanently unstartable, a backwards
prerequisite inverts the plan, an orphan is content a learner can never be
offered, and a rule that matches nothing is a claim the author believes is
in force when it is not.

No database dependency, so `make test-curriculum` runs it in CI without
infrastructure.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from ..learning.skill_graph import Edge, find_cycle
from ..models.enums import CefrLevel, SkillRelation
from .parser import DOMAIN_PREFIXES, CurriculumError, ParsedObjective

#: A `why` shorter than this is not a reason, it is a restatement.
MIN_REASON_CHARS = 40

__all__ = [
    "MIN_REASON_CHARS",
    "GraphEdge",
    "ParsedGraph",
    "parse_graph",
    "prerequisite_edges",
]


@dataclass(frozen=True)
class GraphEdge:
    """One expanded claim about two concrete objectives."""

    source: str
    target: str
    relation: SkillRelation
    weight: float
    #: Why the author believes it. Kept so a reviewer can disagree with the
    #: claim rather than only with the number.
    why: str
    #: Which block of `graph.yml` produced it: `ladder`, `same_level`, `edge`.
    origin: str

    @property
    def is_prerequisite(self) -> bool:
        return self.relation is SkillRelation.PREREQUISITE


@dataclass(frozen=True)
class ParsedGraph:
    edges: tuple[GraphEdge, ...]

    def prerequisites_of(self, key: str) -> tuple[GraphEdge, ...]:
        return tuple(e for e in self.edges if e.target == key and e.is_prerequisite)

    def dependents_of(self, key: str) -> tuple[GraphEdge, ...]:
        return tuple(e for e in self.edges if e.source == key and e.is_prerequisite)


def prerequisite_edges(graph: ParsedGraph) -> list[Edge]:
    """The prerequisite subgraph, in the form the pure algorithms take."""
    return [
        Edge(source=e.source, target=e.target, weight=e.weight)
        for e in graph.edges
        if e.is_prerequisite
    ]


def _weight_of(raw: Any, where: str, errors: list[str]) -> float | None:
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        errors.append(f"{where}: weight must be a number (got {raw!r})")
        return None
    value = float(raw)
    if not 0.0 < value <= 1.0:
        errors.append(f"{where}: weight must be in (0, 1] (got {value})")
        return None
    return value


def _relation_of(raw: Any, where: str, errors: list[str]) -> SkillRelation | None:
    try:
        return SkillRelation(raw)
    except ValueError:
        errors.append(
            f"{where}: unknown relation {raw!r} "
            f"(expected one of {sorted(r.value for r in SkillRelation)})"
        )
        return None


def _reason_of(raw: Any, where: str, errors: list[str]) -> str | None:
    if not isinstance(raw, str) or len(raw.strip()) < MIN_REASON_CHARS:
        errors.append(
            f"{where}: needs a `why` of at least {MIN_REASON_CHARS} characters. "
            f"An edge nobody can justify in a sentence is a guess with a weight on it"
        )
        return None
    return " ".join(raw.split())


def _by_domain_and_level(
    objectives: Iterable[ParsedObjective],
) -> dict[str, dict[CefrLevel, list[str]]]:
    """Objective keys indexed by their *authoring* prefix, not their domain enum.

    `graph.yml` names domains the way the level files do — `speaking`, not
    `spoken_production` — so an author never has to translate between two
    vocabularies for the same thing.
    """
    out: dict[str, dict[CefrLevel, list[str]]] = {}
    for objective in objectives:
        prefix = objective.key.split(".", 1)[0]
        out.setdefault(prefix, {}).setdefault(objective.level, []).append(objective.key)
    for levels in out.values():
        for keys in levels.values():
            keys.sort()
    return out


def _expand_ladders(
    raw: Any,
    index: dict[str, dict[CefrLevel, list[str]]],
    errors: list[str],
) -> list[GraphEdge]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append("graph.yml: `ladders` must be a list")
        return []

    edges: list[GraphEdge] = []
    ordered = list(CefrLevel)

    for entry in raw:
        if not isinstance(entry, dict):
            errors.append("graph.yml: each ladder must be a mapping")
            continue
        domain = entry.get("domain")
        where = f"graph.yml: ladder {domain!r}"
        if not isinstance(domain, str) or domain not in DOMAIN_PREFIXES:
            errors.append(f"{where}: unknown domain (expected one of {sorted(DOMAIN_PREFIXES)})")
            continue
        if domain not in index:
            errors.append(f"{where}: no objective uses this domain, so the ladder is dead")
            continue

        weight = _weight_of(entry.get("weight", 1.0), where, errors)
        why = _reason_of(entry.get("why"), where, errors)
        if weight is None or why is None:
            continue

        # Adjacent *populated* levels, not adjacent CEFR bands: mediation
        # starts at B1 and pragmatics at B2, and a gap would silently break
        # the chain rather than skipping it.
        populated = [level for level in ordered if index[domain].get(level)]
        for lower, higher in pairwise(populated):
            for source in index[domain][lower]:
                for target in index[domain][higher]:
                    edges.append(
                        GraphEdge(
                            source=source,
                            target=target,
                            relation=SkillRelation.PREREQUISITE,
                            weight=weight,
                            why=why,
                            origin="ladder",
                        )
                    )

        if len(populated) < 2:
            errors.append(f"{where}: only one level exists, so the ladder expands to nothing")

    return edges


def _expand_same_level(
    raw: Any,
    index: dict[str, dict[CefrLevel, list[str]]],
    errors: list[str],
) -> list[GraphEdge]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append("graph.yml: `same_level` must be a list")
        return []

    edges: list[GraphEdge] = []

    for entry in raw:
        if not isinstance(entry, dict):
            errors.append("graph.yml: each same_level rule must be a mapping")
            continue
        source_domain = entry.get("from")
        target_domain = entry.get("to")
        where = f"graph.yml: same_level {source_domain!r} -> {target_domain!r}"

        unknown = [d for d in (source_domain, target_domain) if d not in DOMAIN_PREFIXES]
        if unknown:
            errors.append(f"{where}: unknown domain(s) {unknown}")
            continue
        if source_domain == target_domain:
            errors.append(f"{where}: a domain cannot be its own prerequisite; use a ladder")
            continue

        relation = _relation_of(entry.get("relation", "prerequisite"), where, errors)
        weight = _weight_of(entry.get("weight", 1.0), where, errors)
        why = _reason_of(entry.get("why"), where, errors)
        if relation is None or weight is None or why is None:
            continue

        assert isinstance(source_domain, str)
        assert isinstance(target_domain, str)
        produced = 0
        for level in CefrLevel:
            sources = index.get(source_domain, {}).get(level, [])
            targets = index.get(target_domain, {}).get(level, [])
            for source in sources:
                for target in targets:
                    produced += 1
                    edges.append(
                        GraphEdge(
                            source=source,
                            target=target,
                            relation=relation,
                            weight=weight,
                            why=why,
                            origin="same_level",
                        )
                    )

        if produced == 0:
            errors.append(
                f"{where}: matched no level where both domains exist, so the rule is dead. "
                f"A rule the author believes is in force but is not is worse than no rule"
            )

    return edges


def _parse_edges(raw: Any, known: set[str], errors: list[str]) -> list[GraphEdge]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append("graph.yml: `edges` must be a list")
        return []

    edges: list[GraphEdge] = []

    for entry in raw:
        if not isinstance(entry, dict):
            errors.append("graph.yml: each edge must be a mapping")
            continue
        source = entry.get("from")
        target = entry.get("to")
        where = f"graph.yml: edge {source!r} -> {target!r}"

        missing = [k for k in (source, target) if not isinstance(k, str) or k not in known]
        if missing:
            errors.append(f"{where}: names unknown objective(s) {missing}")
            continue
        if source == target:
            errors.append(f"{where}: an objective cannot be its own prerequisite")
            continue

        relation = _relation_of(entry.get("relation", "prerequisite"), where, errors)
        weight = _weight_of(entry.get("weight", 1.0), where, errors)
        why = _reason_of(entry.get("why"), where, errors)
        if relation is None or weight is None or why is None:
            continue

        assert isinstance(source, str)
        assert isinstance(target, str)
        edges.append(
            GraphEdge(
                source=source,
                target=target,
                relation=relation,
                weight=weight,
                why=why,
                origin="edge",
            )
        )

    return edges


def _check_direction(
    edges: Sequence[GraphEdge],
    levels: dict[str, CefrLevel],
    errors: list[str],
) -> None:
    """A prerequisite may not run downhill.

    B2 grammar cannot be required before A1 grammar. Caught explicitly rather
    than left to the cycle check, because a backwards edge that happens not to
    close a loop would load cleanly and quietly invert the plan.
    """
    for edge in edges:
        if not edge.is_prerequisite:
            continue
        source = levels.get(edge.source)
        target = levels.get(edge.target)
        if source is None or target is None:
            continue
        if source.rank > target.rank:
            errors.append(
                f"graph.yml: prerequisite {edge.source} -> {edge.target} runs from "
                f"{source.value} down to {target.value}. A prerequisite cannot be "
                f"harder than what it unlocks"
            )


def _check_duplicates(edges: Sequence[GraphEdge], errors: list[str]) -> None:
    seen: set[tuple[str, str, SkillRelation]] = set()
    for edge in edges:
        triple = (edge.source, edge.target, edge.relation)
        if triple in seen:
            errors.append(
                f"graph.yml: duplicate {edge.relation.value} {edge.source} -> {edge.target} "
                f"(from {edge.origin}). Two rules claiming the same edge disagree about "
                f"its weight and the database will reject the second"
            )
        seen.add(triple)


def _check_orphans(
    edges: Sequence[GraphEdge],
    index: dict[str, dict[CefrLevel, list[str]]],
    errors: list[str],
) -> None:
    """Everything above the floor of its domain needs a way in.

    An objective with no prerequisite at all is either a starting point or
    content no plan will ever build towards. The floor of each domain is the
    former; anything above it with nothing pointing at it is the latter, and
    that is a content bug rather than a design choice.
    """
    reachable = {edge.target for edge in edges if edge.is_prerequisite}
    for domain, levels in sorted(index.items()):
        populated = [level for level in CefrLevel if levels.get(level)]
        for level in populated[1:]:
            for key in levels[level]:
                if key not in reachable:
                    errors.append(
                        f"graph.yml: {key} sits above the floor of {domain} but nothing "
                        f"leads to it, so no plan can ever build towards it"
                    )


def parse_graph(
    curriculum_dir: Path,
    objectives: Sequence[ParsedObjective],
) -> ParsedGraph:
    """Read `graph.yml` and expand it against the parsed objectives.

    Raises:
        CurriculumError: with every problem found, not just the first.
    """
    path = curriculum_dir / "graph.yml"
    errors: list[str] = []

    if not path.is_file():
        raise CurriculumError(
            [
                f"{path.name} not found. The skill graph is authored, not derived: "
                f"without it the planner has no dependency information at all"
            ]
        )

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"graph.yml: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError(["graph.yml: expected a mapping at the top level"])

    index = _by_domain_and_level(objectives)
    known = {objective.key for objective in objectives}
    levels = {objective.key: objective.level for objective in objectives}

    edges: list[GraphEdge] = []
    edges += _expand_ladders(document.get("ladders"), index, errors)
    edges += _expand_same_level(document.get("same_level"), index, errors)
    edges += _parse_edges(document.get("edges"), known, errors)

    if not edges and not errors:
        errors.append("graph.yml: defines no edges")

    _check_duplicates(edges, errors)
    _check_direction(edges, levels, errors)
    _check_orphans(edges, index, errors)

    cycle = find_cycle(prerequisite_edges(ParsedGraph(edges=tuple(edges))))
    if cycle is not None:
        errors.append(
            f"graph.yml: prerequisite cycle {' -> '.join(cycle)}. "
            f"Every skill in it would need every other one first, so none could be started"
        )

    if errors:
        raise CurriculumError(errors)

    # Sorted so the same source always loads in the same order, which keeps
    # the captured API fixture and the database row order reproducible.
    return ParsedGraph(
        edges=tuple(sorted(edges, key=lambda e: (e.source, e.target, e.relation.value)))
    )
