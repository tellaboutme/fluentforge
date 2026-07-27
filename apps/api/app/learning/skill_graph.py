"""Pure algorithms over the skill graph.

No database, no curriculum parsing, no I/O: the curriculum validator uses
these to reject a bad graph before it can be loaded, and the planner uses
them to decide what is holding a learner back. Keeping them here means both
answer the same question the same way.

An edge means "`source` is needed for `target`". Weight is how strongly the
claim is believed, from `curriculum/graph.yml`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "Edge",
    "downstream_reach",
    "find_cycle",
    "gated_by",
    "roots",
    "transitive_dependents",
]


@dataclass(frozen=True)
class Edge:
    """One claim: `source` is needed for `target`, believed this strongly."""

    source: str
    target: str
    weight: float = 1.0


def _adjacency(edges: Iterable[Edge]) -> dict[str, list[Edge]]:
    out: dict[str, list[Edge]] = {}
    for edge in edges:
        out.setdefault(edge.source, []).append(edge)
    return out


def find_cycle(edges: Sequence[Edge]) -> list[str] | None:
    """The first cycle found, as the path around it, or `None`.

    A cycle in a prerequisite graph is not a subtle modelling error: it says
    a learner must master A before B and B before A, so neither can ever be
    started. The curriculum validator refuses one outright.

    Iterative rather than recursive — a curriculum is small, but a stack
    overflow is a bad way to report a content bug. Nodes are visited in
    sorted order so the same broken graph always names the same cycle.
    """
    adjacency = _adjacency(edges)
    nodes = sorted({edge.source for edge in edges} | {edge.target for edge in edges})

    UNSEEN, OPEN, DONE = 0, 1, 2
    state = dict.fromkeys(nodes, UNSEEN)

    for start in nodes:
        if state[start] != UNSEEN:
            continue

        # Each frame is a node and how far through its successors we are.
        path: list[str] = [start]
        cursor: list[int] = [0]
        state[start] = OPEN

        while path:
            node = path[-1]
            successors = sorted(edge.target for edge in adjacency.get(node, ()))

            if cursor[-1] >= len(successors):
                state[node] = DONE
                path.pop()
                cursor.pop()
                continue

            nxt = successors[cursor[-1]]
            cursor[-1] += 1

            if state[nxt] == OPEN:
                # `nxt` is on the current path, so the loop closes here.
                return [*path[path.index(nxt) :], nxt]
            if state[nxt] == UNSEEN:
                state[nxt] = OPEN
                path.append(nxt)
                cursor.append(0)

    return None


def roots(edges: Sequence[Edge], nodes: Iterable[str]) -> set[str]:
    """Nodes nothing depends on — the places a learner can start."""
    has_incoming = {edge.target for edge in edges}
    return {node for node in nodes if node not in has_incoming}


def gated_by(edges: Sequence[Edge], node: str) -> list[Edge]:
    """The edges that must be satisfied before `node` can be attempted."""
    return sorted(
        (edge for edge in edges if edge.target == node),
        key=lambda edge: (-edge.weight, edge.source),
    )


def transitive_dependents(edges: Sequence[Edge], node: str) -> set[str]:
    """Everything downstream of `node`, however far.

    Assumes an acyclic graph, which the validator guarantees; a cycle would
    still terminate here thanks to the visited set, it would simply mean the
    answer describes a graph that should never have loaded.
    """
    adjacency = _adjacency(edges)
    seen: set[str] = set()
    stack = [edge.target for edge in adjacency.get(node, ())]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(edge.target for edge in adjacency.get(current, ()))
    return seen


def downstream_reach(edges: Sequence[Edge], nodes: Iterable[str]) -> Mapping[str, float]:
    """How much each skill gates, normalised to 0..1.

    This replaces the difficulty proxy the planner used before, which assumed
    "lower level" meant "blocks more". Within one domain that is nearly true;
    across domains it is not. Vocabulary at A2 gates speaking, writing and —
    through them — interaction and mediation. Pronunciation at A2 gates
    almost nothing, because the graph deliberately declines to let
    intelligibility block production. The old proxy scored them identically.

    A path's contribution is the product of its edge weights, so a chain of
    tentative claims counts for less than a chain of definitional ones, and
    the strongest path to each dependent is the one that counts. The result
    is divided by the largest raw score, so the most load-bearing skill in
    the curriculum scores 1.0 and everything else is read against it.

    Returns 0.0 for every node when the graph has no edges, rather than
    dividing by zero: an empty graph gates nothing.
    """
    adjacency = _adjacency(edges)
    all_nodes = list(nodes)

    raw: dict[str, float] = {}
    for node in all_nodes:
        # Best (highest-product) path weight to each reachable dependent.
        best: dict[str, float] = {}
        frontier: list[tuple[str, float]] = [(node, 1.0)]
        while frontier:
            current, carried = frontier.pop()
            for edge in adjacency.get(current, ()):
                value = carried * edge.weight
                if value <= best.get(edge.target, 0.0):
                    continue
                best[edge.target] = value
                frontier.append((edge.target, value))
        best.pop(node, None)
        raw[node] = sum(best.values())

    largest = max(raw.values(), default=0.0)
    if largest <= 0.0:
        return dict.fromkeys(all_nodes, 0.0)
    return {node: round(value / largest, 6) for node, value in raw.items()}
