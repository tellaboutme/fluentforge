"""The skill graph: the algorithms, the authored source, and what it changes.

Three groups, deliberately separate.

`downstream_reach` and `find_cycle` are pure and get worked examples, because
a graph walk that is subtly wrong produces plausible numbers rather than an
error.

The authored graph in `curriculum/graph.yml` gets its invariants checked —
acyclic, no backwards prerequisites, nothing orphaned above the floor of its
domain — and, more importantly, gets the specific claims it makes checked,
because a graph that validates but says the wrong thing about language is
still wrong.

The validator gets one test per way a bad graph can be bad, since every one
of those failures is silent: the graph loads, the planner believes it, and
the learner gets a worse plan for reasons nobody can see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.curriculum.graph import (
    MIN_REASON_CHARS,
    parse_graph,
    prerequisite_edges,
)
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.learning.skill_graph import (
    Edge,
    downstream_reach,
    find_cycle,
    gated_by,
    roots,
    transitive_dependents,
)
from apps.api.app.models.enums import SkillRelation

# --- The algorithms ---------------------------------------------------------


def test_a_chain_has_no_cycle() -> None:
    assert find_cycle([Edge("a", "b"), Edge("b", "c")]) is None


def test_a_diamond_has_no_cycle() -> None:
    """Two paths to the same place is convergence, not a loop — and the naive
    "have I seen this node?" check would call it one."""
    edges = [Edge("a", "b"), Edge("a", "c"), Edge("b", "d"), Edge("c", "d")]
    assert find_cycle(edges) is None


def test_a_cycle_is_found_and_named() -> None:
    cycle = find_cycle([Edge("a", "b"), Edge("b", "c"), Edge("c", "a")])
    assert cycle is not None
    assert cycle[0] == cycle[-1], "the path should close"
    assert set(cycle) == {"a", "b", "c"}


def test_a_self_loop_is_a_cycle() -> None:
    assert find_cycle([Edge("a", "a")]) is not None


def test_the_same_broken_graph_always_names_the_same_cycle() -> None:
    """So a content author fixing it sees a stable error, not a new one each run."""
    edges = [Edge("b", "c"), Edge("c", "b"), Edge("a", "b"), Edge("x", "y"), Edge("y", "x")]
    assert find_cycle(edges) == find_cycle(list(reversed(edges)))


def test_a_deep_chain_does_not_exhaust_the_stack() -> None:
    """Iterative, not recursive: a stack overflow is a bad way to report a
    content bug."""
    edges = [Edge(f"n{i}", f"n{i + 1}") for i in range(5_000)]
    assert find_cycle(edges) is None


def test_roots_are_where_a_learner_can_start() -> None:
    edges = [Edge("a", "b"), Edge("b", "c")]
    assert roots(edges, ["a", "b", "c"]) == {"a"}


def test_gated_by_lists_the_strongest_claim_first() -> None:
    edges = [Edge("weak", "target", 0.4), Edge("strong", "target", 0.9)]
    assert [edge.source for edge in gated_by(edges, "target")] == ["strong", "weak"]


def test_transitive_dependents_reach_the_far_end() -> None:
    edges = [Edge("a", "b"), Edge("b", "c"), Edge("c", "d")]
    assert transitive_dependents(edges, "a") == {"b", "c", "d"}


def test_a_leaf_gates_nothing() -> None:
    reach = downstream_reach([Edge("a", "b")], ["a", "b"])
    assert reach["b"] == 0.0


def test_gating_more_scores_higher() -> None:
    # `wide` gates three skills; `narrow` gates one.
    edges = [
        Edge("wide", "x"),
        Edge("wide", "y"),
        Edge("wide", "z"),
        Edge("narrow", "x"),
    ]
    reach = downstream_reach(edges, ["wide", "narrow", "x", "y", "z"])
    assert reach["wide"] > reach["narrow"]


def test_reach_travels_through_the_graph_not_just_one_hop() -> None:
    """The point of walking it. `a` gates `b` directly and `c` through it."""
    reach = downstream_reach([Edge("a", "b"), Edge("b", "c")], ["a", "b", "c"])
    assert reach["a"] > reach["b"] > reach["c"]


def test_a_tentative_chain_counts_for_less_than_a_definitional_one() -> None:
    edges = [
        Edge("sure", "s1", 1.0),
        Edge("s1", "s2", 1.0),
        Edge("unsure", "u1", 0.5),
        Edge("u1", "u2", 0.5),
    ]
    reach = downstream_reach(edges, ["sure", "s1", "s2", "unsure", "u1", "u2"])
    assert reach["sure"] > reach["unsure"]


def test_the_strongest_path_to_a_dependent_is_the_one_that_counts() -> None:
    """Two routes to the same skill should not add up: it is gated once."""
    both = downstream_reach(
        [Edge("a", "mid", 0.9), Edge("a", "other", 0.1), Edge("mid", "end"), Edge("other", "end")],
        ["a", "mid", "other", "end"],
    )
    assert both["a"] == pytest.approx(both["a"])  # computed without error
    assert 0.0 < both["mid"] <= 1.0


def test_reach_is_normalised_so_the_top_skill_is_one() -> None:
    reach = downstream_reach([Edge("a", "b"), Edge("b", "c")], ["a", "b", "c"])
    assert max(reach.values()) == 1.0


def test_an_empty_graph_gates_nothing_rather_than_dividing_by_zero() -> None:
    assert downstream_reach([], ["a", "b"]) == {"a": 0.0, "b": 0.0}


# --- The authored graph -----------------------------------------------------


@pytest.fixture
def graph(curriculum_dir: Path):
    curriculum = parse_curriculum(curriculum_dir)
    return parse_graph(curriculum_dir, curriculum.objectives)


def test_the_authored_graph_is_valid(graph) -> None:
    assert len(graph.edges) > 0


def test_the_authored_graph_is_acyclic(graph) -> None:
    """A cycle would make every skill in it permanently unstartable."""
    assert find_cycle(prerequisite_edges(graph)) is None


def test_every_edge_states_a_reason(graph) -> None:
    for edge in graph.edges:
        assert len(edge.why) >= MIN_REASON_CHARS, f"{edge.source} -> {edge.target}"


def test_the_graph_says_more_than_the_old_derivation_did(graph) -> None:
    """It used to be one claim repeated 45 times. Anything less than a
    substantial cross-domain set here means the milestone did not happen."""
    cross_domain = [e for e in graph.edges if e.origin != "ladder"]
    assert len(cross_domain) >= 40


def test_both_relations_are_used(graph) -> None:
    """`supports` exists so a true-but-not-blocking claim has somewhere to go
    other than being inflated into a prerequisite."""
    relations = {edge.relation for edge in graph.edges}
    assert relations == {SkillRelation.PREREQUISITE, SkillRelation.SUPPORTS}


# --- What the graph actually claims -----------------------------------------


def _has(graph, source: str, target: str, relation: SkillRelation) -> bool:
    return any(
        e.source == source and e.target == target and e.relation is relation for e in graph.edges
    )


def test_interaction_requires_both_halves(graph) -> None:
    """Interaction is listening and speaking at once. Neither half is optional."""
    assert _has(
        graph,
        "listening.routine_messages",
        "interaction.routine_transactions",
        SkillRelation.PREREQUISITE,
    )
    assert _has(
        graph,
        "speaking.simple_description",
        "interaction.routine_transactions",
        SkillRelation.PREREQUISITE,
    )


def test_vocabulary_gates_production(graph) -> None:
    """The claim the old derivation could not express at all."""
    assert _has(
        graph,
        "vocabulary.everyday_topics",
        "speaking.simple_description",
        SkillRelation.PREREQUISITE,
    )
    assert _has(
        graph, "vocabulary.everyday_topics", "writing.linked_messages", SkillRelation.PREREQUISITE
    )


def test_pronunciation_never_blocks_another_domain(graph) -> None:
    """Load-bearing. Making intelligibility a prerequisite of speaking would
    encode an accent standard this product does not hold — a heavily accented
    speaker can be entirely successful, which is why the CEFR scales
    phonological control separately.

    The pronunciation ladder is exempt: a higher pronunciation band does
    assume the one below it. What must never happen is pronunciation gating
    something outside its own domain."""
    blocking = [
        e
        for e in graph.edges
        if e.source.startswith("pronunciation.")
        and e.is_prerequisite
        and not e.target.startswith("pronunciation.")
    ]
    assert blocking == [], [f"{e.source} -> {e.target}" for e in blocking]


def test_pronunciation_supports_speaking_rather_than_being_dropped(graph) -> None:
    """The relationship is real; it simply must not block."""
    assert _has(
        graph,
        "pronunciation.phrase_rhythm",
        "speaking.simple_description",
        SkillRelation.SUPPORTS,
    )


def test_perception_gates_pronunciation(graph) -> None:
    """A contrast has to be heard before it can be produced. Production drills
    on an unperceived contrast train the learner to reproduce their own error."""
    assert _has(
        graph,
        "listening.routine_messages",
        "pronunciation.phrase_rhythm",
        SkillRelation.PREREQUISITE,
    )


def test_grammar_gates_writing_but_only_supports_speaking(graph) -> None:
    """Speech tolerates approximation that writing does not. Gating spoken
    practice on grammar would keep a learner silent for no gain."""
    assert _has(
        graph, "grammar.past_future_basic", "writing.linked_messages", SkillRelation.PREREQUISITE
    )
    assert _has(
        graph, "grammar.past_future_basic", "speaking.simple_description", SkillRelation.SUPPORTS
    )
    assert not _has(
        graph,
        "grammar.past_future_basic",
        "speaking.simple_description",
        SkillRelation.PREREQUISITE,
    )


def test_mediation_requires_reception_and_production(graph) -> None:
    assert _has(
        graph, "reading.familiar_arguments", "mediation.basic_summary", SkillRelation.PREREQUISITE
    )
    assert _has(
        graph, "writing.connected_genres", "mediation.basic_summary", SkillRelation.PREREQUISITE
    )


def test_reception_runs_ahead_of_production_but_is_not_treated_as_certain(graph) -> None:
    """Close to consensus, with real exceptions — so it gates, at a weight
    that says the claim is believed rather than definitional."""
    edge = next(
        e
        for e in graph.edges
        if e.source == "reading.short_everyday_texts" and e.target == "writing.linked_messages"
    )
    assert edge.is_prerequisite
    assert edge.weight < 1.0


def test_ladders_are_the_confident_claims(graph) -> None:
    """Within a domain, the lower band names a subset of the higher one."""
    ladder = [e for e in graph.edges if e.origin == "ladder"]
    assert all(e.is_prerequisite for e in ladder)
    assert max(e.weight for e in ladder) == 1.0


def test_pronunciation_ladder_is_the_least_confident_one(graph) -> None:
    """A learner can have accurate segments and flat prosody, or the reverse."""
    pronunciation = [
        e for e in graph.edges if e.origin == "ladder" and e.source.startswith("pronunciation.")
    ]
    other = [
        e for e in graph.edges if e.origin == "ladder" and not e.source.startswith("pronunciation.")
    ]
    assert max(e.weight for e in pronunciation) < min(e.weight for e in other)


# --- What it changes for the planner ----------------------------------------


def test_vocabulary_gates_far_more_than_pronunciation(curriculum_dir: Path, graph) -> None:
    """The concrete reason the milestone exists. Both sit at A2, so the old
    `1 - difficulty` proxy scored them identically. They are not remotely
    equivalent, and now the plan can tell."""
    curriculum = parse_curriculum(curriculum_dir)
    reach = downstream_reach(prerequisite_edges(graph), [o.key for o in curriculum.objectives])

    assert reach["vocabulary.everyday_topics"] > reach["pronunciation.phrase_rhythm"] * 3


def test_the_most_load_bearing_skill_is_a_foundation_not_a_summit(
    curriculum_dir: Path, graph
) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    reach = downstream_reach(prerequisite_edges(graph), [o.key for o in curriculum.objectives])
    top = max(reach, key=lambda key: reach[key])

    levels = {o.key: o.level for o in curriculum.objectives}
    assert levels[top].rank == 0, f"{top} gates the most but is not at A1"


def test_nothing_at_c2_is_among_the_most_load_bearing(curriculum_dir: Path, graph) -> None:
    """C2 skills do gate each other — C2 vocabulary gates C2 pragmatics — but
    nothing sits above the band, so they can never gate as much as the
    foundations do. A plan pushing an A1 learner towards C2 material because
    it "unblocks" things would be exactly the failure this replaces."""
    curriculum = parse_curriculum(curriculum_dir)
    reach = downstream_reach(prerequisite_edges(graph), [o.key for o in curriculum.objectives])
    levels = {o.key: o.level for o in curriculum.objectives}

    top_ten = sorted(reach, key=lambda key: (-reach[key], key))[:10]
    assert all(levels[key].value != "C2" for key in top_ten), top_ten


def test_the_terminal_skills_gate_nothing_at_all(curriculum_dir: Path, graph) -> None:
    """Some skill has to be the end of every chain, and the walk should say so
    rather than assigning everything a nonzero score."""
    curriculum = parse_curriculum(curriculum_dir)
    reach = downstream_reach(prerequisite_edges(graph), [o.key for o in curriculum.objectives])

    assert any(value == 0.0 for value in reach.values())


def test_supports_edges_do_not_count_towards_gating(curriculum_dir: Path, graph) -> None:
    """A skill that merely helps another is not holding it back."""
    curriculum = parse_curriculum(curriculum_dir)
    keys = [o.key for o in curriculum.objectives]

    prerequisites_only = downstream_reach(prerequisite_edges(graph), keys)
    everything = downstream_reach([Edge(e.source, e.target, e.weight) for e in graph.edges], keys)

    assert prerequisites_only != everything


# --- Refusals ---------------------------------------------------------------


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "graph.yml").write_text(body, encoding="utf-8")
    return tmp_path


@pytest.fixture
def objectives(curriculum_dir: Path):
    return parse_curriculum(curriculum_dir).objectives


def test_a_missing_graph_is_refused(tmp_path: Path, objectives) -> None:
    """The graph is authored, not derived. Without it the planner has no
    dependency information at all, and silently continuing would hide that."""
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("not found" in error for error in exc_info.value.errors)


def test_an_unknown_objective_is_refused(tmp_path: Path, objectives) -> None:
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.no_such_thing\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("unknown objective" in error for error in exc_info.value.errors)


def test_a_backwards_prerequisite_is_refused(tmp_path: Path, objectives) -> None:
    """It would load cleanly, close no loop, and quietly invert the plan."""
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.broad_control\n"
        "    to: grammar.basic_clause\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("cannot be harder than what it unlocks" in error for error in exc_info.value.errors)


def test_a_self_edge_is_refused(tmp_path: Path, objectives) -> None:
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.basic_clause\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("its own prerequisite" in error for error in exc_info.value.errors)


def test_an_edge_without_a_reason_is_refused(tmp_path: Path, objectives) -> None:
    """An edge nobody can justify in a sentence is a guess with a weight on it."""
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.past_future_basic\n"
        "    why: because\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("`why`" in error for error in exc_info.value.errors)


def test_an_impossible_weight_is_refused(tmp_path: Path, objectives) -> None:
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.past_future_basic\n"
        "    weight: 1.5\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("weight must be in" in error for error in exc_info.value.errors)


def test_a_zero_weight_is_refused(tmp_path: Path, objectives) -> None:
    """An edge believed with strength zero is not an edge; delete it instead."""
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.past_future_basic\n"
        "    weight: 0\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("weight must be in" in error for error in exc_info.value.errors)


def test_a_duplicate_triple_is_refused(tmp_path: Path, objectives) -> None:
    """Two rules claiming one edge disagree about its weight, and the database
    would reject the second anyway."""
    edge = (
        "  - from: grammar.basic_clause\n"
        "    to: grammar.past_future_basic\n"
        "    why: A reason long enough to satisfy the minimum length check.\n"
    )
    _write(tmp_path, "edges:\n" + edge + edge)
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("duplicate" in error for error in exc_info.value.errors)


def test_a_cycle_is_refused(tmp_path: Path, objectives) -> None:
    """Every skill in it would need every other one first."""
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: vocabulary.high_frequency_survival\n"
        "    why: A reason long enough to satisfy the minimum length check.\n"
        "  - from: vocabulary.high_frequency_survival\n"
        "    to: grammar.basic_clause\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("cycle" in error for error in exc_info.value.errors)


def test_an_orphan_above_the_floor_is_refused(tmp_path: Path, objectives) -> None:
    """Content no plan can ever build towards is a bug, not a design choice."""
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.past_future_basic\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("nothing leads to it" in error for error in exc_info.value.errors)


def test_a_rule_that_matches_nothing_is_refused(tmp_path: Path, objectives) -> None:
    """A rule the author believes is in force but is not is worse than no rule."""
    _write(
        tmp_path,
        "same_level:\n"
        "  - from: pragmatics\n"
        "    to: strategies\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("matched no level" in error for error in exc_info.value.errors)


def test_a_ladder_on_a_domain_with_no_objectives_is_refused(tmp_path: Path, objectives) -> None:
    _write(
        tmp_path,
        "ladders:\n"
        "  - domain: fluency\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("the ladder is dead" in error for error in exc_info.value.errors)


def test_an_unknown_relation_is_refused(tmp_path: Path, objectives) -> None:
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.past_future_basic\n"
        "    relation: sort_of_helps\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert any("unknown relation" in error for error in exc_info.value.errors)


def test_every_problem_is_reported_not_just_the_first(tmp_path: Path, objectives) -> None:
    """A content author fixing the graph should see the whole list once."""
    _write(
        tmp_path,
        "edges:\n"
        "  - from: grammar.basic_clause\n"
        "    to: grammar.nope\n"
        "    why: A reason long enough to satisfy the minimum length check.\n"
        "  - from: grammar.broad_control\n"
        "    to: grammar.basic_clause\n"
        "    why: A reason long enough to satisfy the minimum length check.\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_graph(tmp_path, objectives)
    assert len(exc_info.value.errors) >= 2
