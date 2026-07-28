"""The skill graph, as the learner sees it.

`curriculum/graph.yml` holds 119 authored claims about what depends on what,
and until now the only thing that read them was the planner. A learner could
be told a prerequisite was weak and had no way to see which, or why the claim
was made.

`docs/ADAPTIVE_ENGINE.md` forbids an opaque priority score so that a learner
can disagree with the reasoning rather than merely receive it. The graph was
the largest piece of reasoning they could not inspect.

Two properties carry the weight here, and both are about not overclaiming:
the map says the graph is judgement rather than measurement, and it shows no
CEFR level a learner has not earned.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.curriculum import SkillNode
from apps.api.app.models.enums import SkillRelation
from apps.api.app.models.learning import SkillState
from apps.api.app.routers.skill_map import WEAK_BELOW
from apps.api.tests.helpers import register


def _map(client: TestClient, headers: dict[str, str]) -> dict:
    return client.get("/api/v1/profile/skill-map", headers=headers).json()


def test_the_map_lists_every_skill(seeded_client: TestClient) -> None:
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    body = _map(seeded_client, headers)

    assert len(body["nodes"]) > 0
    assert len(body["edges"]) > 0


def test_it_says_the_graph_is_judgement_rather_than_measurement(
    seeded_client: TestClient,
) -> None:
    """The load-bearing caveat. A map drawn without it reads as a discovered
    structure, and it is 119 authored claims none of which has been checked
    against how people actually learn."""
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    caveats = " ".join(_map(seeded_client, headers)["caveats"]).lower()

    assert "judgement" in caveats
    assert "not measurement" in caveats or "measurement" in caveats


def test_caveats_are_never_empty(seeded_client: TestClient) -> None:
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    assert _map(seeded_client, headers)["caveats"]


def test_a_new_learner_sees_no_levels_at_all(seeded_client: TestClient) -> None:
    """The same rule as the profile, and a skill map is a tempting place to
    relax it: a grid of blanks looks unfinished. A grid of invented levels
    would be worse."""
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    body = _map(seeded_client, headers)

    assert all(node["cefr_estimate"] is None for node in body["nodes"])


def test_unmeasured_skills_are_not_reported_as_weak(
    seeded_client: TestClient,
) -> None:
    """ "We have never looked" and "you cannot do this" are different claims,
    and the caveat says so in as many words."""
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    body = _map(seeded_client, headers)

    assert all(node["status"] == "unobserved" for node in body["nodes"])
    assert any("no evidence at all" in caveat for caveat in body["caveats"])


def test_only_prerequisites_block(seeded_client: TestClient) -> None:
    """`supports` is a real relation and never gates. Reporting it as
    blocking would tell a learner they are held back by something that only
    helps — and pronunciation supports speaking, so that mistake would put an
    accent standard back into the product through the side door."""
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    body = _map(seeded_client, headers)

    supports = {
        (edge["source"], edge["target"])
        for edge in body["edges"]
        if edge["relation"] == SkillRelation.SUPPORTS.value
    }
    assert supports, "the fixture graph should contain supporting edges"

    for node in body["nodes"]:
        for blocker in node["blocked_by"]:
            assert (blocker, node["key"]) not in supports


def test_a_weak_prerequisite_is_named_as_blocking(
    seeded_client: TestClient, session_factory
) -> None:
    """The answer to "why can I not get anywhere with this?", which the
    planner has always known and the learner could not see."""
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    body = _map(seeded_client, headers)

    # Everything is unmeasured, so every prerequisite counts as weak: any
    # skill with an incoming prerequisite edge should name it.
    prerequisites = {
        (edge["source"], edge["target"])
        for edge in body["edges"]
        if edge["relation"] == SkillRelation.PREREQUISITE.value
    }
    assert prerequisites

    by_key = {node["key"]: node for node in body["nodes"]}
    source, target = next(iter(sorted(prerequisites)))
    assert source in by_key[target]["blocked_by"]
    assert target in by_key[source]["blocking"]


def test_a_strong_skill_blocks_nothing(seeded_client: TestClient, session_factory) -> None:
    """Listing what a skill gates regardless of the learner's state would
    tell them their strongest skills are holding them back."""
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    me = seeded_client.get("/api/v1/auth/me", headers=headers).json()

    session: Session = session_factory()
    try:
        from apps.api.app.models.identity import User

        user = session.execute(select(User).where(User.email == me["email"])).scalar_one()
        nodes = session.execute(select(SkillNode)).scalars().all()
        for node in nodes:
            session.add(
                SkillState(
                    user_id=user.id,
                    skill_node_id=node.id,
                    mastery_probability=WEAK_BELOW + 0.2,
                    confidence=0.9,
                    distinct_contexts=3,
                    evidence_count=10,
                )
            )
        session.commit()
    finally:
        session.close()

    body = _map(seeded_client, headers)
    assert all(node["blocking"] == [] for node in body["nodes"])
    assert all(node["blocked_by"] == [] for node in body["nodes"])


def test_edge_weights_are_carried(seeded_client: TestClient) -> None:
    """Weight is how strongly the claim is believed, not how important the
    skill is, and a learner reading the map should be able to tell a
    definitional dependency from a tentative one."""
    headers = register(seeded_client, f"map-{uuid.uuid4().hex[:6]}@example.com")
    weights = {edge["weight"] for edge in _map(seeded_client, headers)["edges"]}

    assert len(weights) > 1
    assert all(0 < weight <= 1 for weight in weights)


def test_the_map_needs_a_learner(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/v1/profile/skill-map").status_code == 401
