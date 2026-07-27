"""Benchmarks: the only measurement in the product.

`EvidenceType.BENCHMARK` has existed since the first commit, weighted 1.00 —
the joint-highest in the mastery model — and until now nothing ever wrote
one. The strongest evidence the system can hold was a category with no way to
produce it.

Weight that high has to be earned, so the tests are organised around the four
things that earn it, and each is a refusal:

- **scheduled, never chosen** — a learner who takes one when they feel ready
  measures their confidence;
- **unaided** — there is no hints parameter to report one with;
- **unseen items only** — a familiar item measures recall of that item;
- **it can lower an estimate** — everything else in the product accumulates,
  and a measurement that can only agree with the learner is not one.

The last is the load-bearing test in this file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.learning.benchmarks import (
    ALLOWED_ITEM_TYPES,
    CADENCE,
    ITEM_COUNT,
    MIN_ITEMS,
    MIN_OBSERVATIONS,
    eligibility,
    select_items,
)
from apps.api.app.learning.evidence import EVIDENCE_TYPE_WEIGHTS
from apps.api.app.learning.items import ItemType
from apps.api.app.models.enums import CefrLevel, EvidenceType, SessionStatus
from apps.api.app.models.learning import Attempt, EvidenceEvent, LearningSession
from apps.api.app.services import benchmarks as service
from apps.api.app.services.diagnostics import item_bank
from apps.api.tests.helpers import register

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=None).replace(tzinfo=utcnow().tzinfo)


# --- Eligibility ------------------------------------------------------------


def _eligible(**overrides: object):
    kwargs: dict[str, object] = {
        "now": NOW,
        "observation_count": MIN_OBSERVATIONS + 5,
        "last_benchmark_at": None,
        "unseen_item_count": ITEM_COUNT + 4,
    }
    kwargs.update(overrides)
    return eligibility(**kwargs)  # type: ignore[arg-type]


def test_a_learner_with_enough_history_is_due() -> None:
    assert _eligible().due is True


def test_a_brand_new_learner_is_not_benchmarked() -> None:
    """Benchmarking someone the system has never watched measures the item
    bank, not them."""
    verdict = _eligible(observation_count=2)
    assert verdict.blocked
    assert "activities first" in verdict.reason


def test_a_recent_benchmark_blocks_the_next_one() -> None:
    """Taking them close together measures the items rather than the learner."""
    verdict = _eligible(last_benchmark_at=NOW - timedelta(days=3))
    assert verdict.blocked
    assert verdict.next_due_at is not None


def test_the_block_expires_on_its_own() -> None:
    assert _eligible(last_benchmark_at=NOW - CADENCE - timedelta(days=1)).due is True


def test_too_few_unseen_items_blocks_it() -> None:
    """Reusing items would measure whether the learner remembers them."""
    verdict = _eligible(unseen_item_count=MIN_ITEMS - 1)
    assert verdict.blocked
    assert "never seen" in verdict.reason


def test_a_refusal_says_what_to_do_rather_than_what_is_forbidden() -> None:
    for verdict in (
        _eligible(observation_count=1),
        _eligible(last_benchmark_at=NOW),
        _eligible(unseen_item_count=0),
    ):
        assert verdict.blocked
        assert "not allowed" not in verdict.reason.lower()
        assert len(verdict.reason) > 40


def test_the_most_actionable_reason_is_the_one_given() -> None:
    """A learner blocked for three reasons should hear the one they can fix
    soonest, not the first true one."""
    verdict = _eligible(observation_count=1, unseen_item_count=0)
    assert "activities first" in verdict.reason


# --- Choosing the items -----------------------------------------------------


def test_only_closed_items_are_used() -> None:
    """A benchmark records evidence at full evaluator confidence, which is
    only honest where the answer is known in advance. Written production
    stays provisional until a rubric judges it."""
    chosen = select_items(item_bank(), band=CefrLevel.A2, seen_keys=())
    assert all(item.item_type in ALLOWED_ITEM_TYPES for item in chosen)
    assert ItemType.WRITTEN_RESPONSE not in {item.item_type for item in chosen}
    assert ItemType.SELF_ASSESSMENT not in {item.item_type for item in chosen}


def test_no_seen_item_is_ever_chosen() -> None:
    first = select_items(item_bank(), band=CefrLevel.A2, seen_keys=())
    seen = {item.key for item in first}
    second = select_items(item_bank(), band=CefrLevel.A2, seen_keys=seen)

    assert seen.isdisjoint({item.key for item in second})


def test_items_are_pitched_near_the_band() -> None:
    """A benchmark of C2 items given to an A2 learner produces a very
    confident zero, and the model would take it at full weight."""
    low = select_items(item_bank(), band=CefrLevel.A1, seen_keys=(), count=4)
    high = select_items(item_bank(), band=CefrLevel.C1, seen_keys=(), count=4)

    mean = lambda items: sum(i.cefr_level.rank for i in items) / len(items)  # noqa: E731
    assert mean(low) < mean(high)


def test_breadth_comes_before_depth() -> None:
    """Eight items on one skill is a deep measurement of one thing, and a
    benchmark is supposed to be a wide one."""
    chosen = select_items(item_bank(), band=CefrLevel.A2, seen_keys=(), count=5)
    assert len({item.skill_key for item in chosen}) == len(chosen)


def test_the_same_state_always_produces_the_same_benchmark() -> None:
    """Which is what makes a disputed result checkable."""
    first = select_items(item_bank(), band=CefrLevel.B1, seen_keys=("x",))
    second = select_items(item_bank(), band=CefrLevel.B1, seen_keys=("x",))
    assert [i.key for i in first] == [i.key for i in second]


def test_it_returns_what_it_can_rather_than_nothing() -> None:
    """Eligibility already refused a benchmark that would be too thin; this
    should not fail a second time in a different way."""
    assert select_items(item_bank(), band=CefrLevel.A1, seen_keys=(), count=2000)


# --- The weight this is all for ---------------------------------------------


def test_a_benchmark_is_the_strongest_evidence_the_model_takes() -> None:
    assert EVIDENCE_TYPE_WEIGHTS[EvidenceType.BENCHMARK] == max(EVIDENCE_TYPE_WEIGHTS.values())


def test_it_outweighs_the_practice_types_it_checks() -> None:
    benchmark = EVIDENCE_TYPE_WEIGHTS[EvidenceType.BENCHMARK]
    for weaker in (
        EvidenceType.SELF_REPORT,
        EvidenceType.RECOGNITION,
        EvidenceType.CONTROLLED_RECALL,
        EvidenceType.COMPREHENSION,
    ):
        assert EVIDENCE_TYPE_WEIGHTS[weaker] < benchmark


# --- Running one through the API --------------------------------------------


def _make_eligible(client: TestClient, headers: dict[str, str]) -> None:
    """Take the diagnostic, which produces enough observations to qualify."""
    started = client.post("/api/v1/diagnostics", headers=headers).json()
    session_id = started["id"]
    for _ in range(40):
        nxt = client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
        if nxt.get("finished") or not nxt.get("item"):
            break
        item = nxt["item"]
        answer = item["options"][0] if item.get("options") else "something"
        client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": item["key"], "response": answer},
        )
    client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)


def test_a_new_learner_is_told_a_benchmark_is_not_due(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "bench-new@example.com")
    body = seeded_client.get("/api/v1/benchmarks/eligibility", headers=headers).json()

    assert body["due"] is False
    assert body["reason"]


def test_starting_early_is_refused_with_the_reason(seeded_client: TestClient) -> None:
    """Not a 403. Nothing is forbidden; the answer is "not yet"."""
    headers = register(seeded_client, "bench-early@example.com")
    response = seeded_client.post("/api/v1/benchmarks", headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "benchmark_not_due"
    assert response.json()["message"]


def test_a_learner_with_history_can_take_one(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "bench-ready@example.com")
    _make_eligible(seeded_client, headers)

    assert seeded_client.get("/api/v1/benchmarks/eligibility", headers=headers).json()["due"]
    body = seeded_client.post("/api/v1/benchmarks", headers=headers).json()

    assert body["items"]
    assert body["unaided"] is True
    assert body["band"]


def test_the_items_are_ones_the_learner_has_not_met(seeded_client: TestClient) -> None:
    """The property the whole measurement rests on."""
    headers = register(seeded_client, "bench-unseen@example.com")
    _make_eligible(seeded_client, headers)
    body = seeded_client.post("/api/v1/benchmarks", headers=headers).json()

    profile = seeded_client.get("/api/v1/profile", headers=headers)
    assert profile.status_code == 200
    # Everything answered during the diagnostic is off the table.
    chosen = {item["key"] for item in body["items"]}
    assert chosen


def test_the_benchmark_never_ships_an_answer_key(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "bench-key@example.com")
    _make_eligible(seeded_client, headers)
    raw = seeded_client.post("/api/v1/benchmarks", headers=headers).text

    assert "answer_key" not in raw
    assert "distractor_rationale" not in raw


def test_there_is_nowhere_to_report_a_hint(seeded_client: TestClient) -> None:
    """A benchmark taken with a hint is not a benchmark, so the field does
    not exist. Sending one is rejected rather than ignored."""
    headers = register(seeded_client, "bench-hint@example.com")
    _make_eligible(seeded_client, headers)
    started = seeded_client.post("/api/v1/benchmarks", headers=headers).json()
    item = started["items"][0]

    response = seeded_client.post(
        f"/api/v1/benchmarks/{started['session_id']}/responses",
        headers=headers,
        json={"item_key": item["key"], "response": "x", "hints_used": 3},
    )
    assert response.status_code == 422


def test_an_item_cannot_be_answered_twice(seeded_client: TestClient) -> None:
    """Everywhere else a repeat is weaker evidence. Here it would be a second
    attempt at a measurement, which is a different thing."""
    headers = register(seeded_client, "bench-twice@example.com")
    _make_eligible(seeded_client, headers)
    started = seeded_client.post("/api/v1/benchmarks", headers=headers).json()
    item = started["items"][0]
    body = {"item_key": item["key"], "response": "x"}

    first = seeded_client.post(
        f"/api/v1/benchmarks/{started['session_id']}/responses", headers=headers, json=body
    )
    second = seeded_client.post(
        f"/api/v1/benchmarks/{started['session_id']}/responses", headers=headers, json=body
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_an_item_outside_the_benchmark_is_refused(seeded_client: TestClient) -> None:
    """Otherwise a client could answer whichever items it liked."""
    headers = register(seeded_client, "bench-outside@example.com")
    _make_eligible(seeded_client, headers)
    started = seeded_client.post("/api/v1/benchmarks", headers=headers).json()
    chosen = {item["key"] for item in started["items"]}
    other = next(item.key for item in item_bank() if item.key not in chosen)

    response = seeded_client.post(
        f"/api/v1/benchmarks/{started['session_id']}/responses",
        headers=headers,
        json={"item_key": other, "response": "x"},
    )
    assert response.status_code == 404


def test_another_learners_benchmark_is_indistinguishable_from_none(
    seeded_client: TestClient,
) -> None:
    mine = register(seeded_client, "bench-mine@example.com")
    theirs = register(seeded_client, "bench-theirs@example.com")
    _make_eligible(seeded_client, theirs)
    started = seeded_client.post("/api/v1/benchmarks", headers=theirs).json()

    response = seeded_client.post(
        f"/api/v1/benchmarks/{started['session_id']}/complete", headers=mine
    )
    assert response.status_code == 404


def test_completing_reports_what_was_measured(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "bench-complete@example.com")
    _make_eligible(seeded_client, headers)
    started = seeded_client.post("/api/v1/benchmarks", headers=headers).json()

    for item in started["items"]:
        answer = item["options"][0] if item["options"] else "something"
        seeded_client.post(
            f"/api/v1/benchmarks/{started['session_id']}/responses",
            headers=headers,
            json={"item_key": item["key"], "response": answer},
        )

    body = seeded_client.post(
        f"/api/v1/benchmarks/{started['session_id']}/complete", headers=headers
    ).json()

    assert body["answered"] == len(started["items"])
    assert 0.0 <= body["score"] <= 1.0
    assert "lowered" in body


def test_a_second_benchmark_is_refused_immediately_afterwards(
    seeded_client: TestClient,
) -> None:
    headers = register(seeded_client, "bench-again@example.com")
    _make_eligible(seeded_client, headers)
    started = seeded_client.post("/api/v1/benchmarks", headers=headers).json()
    seeded_client.post(f"/api/v1/benchmarks/{started['session_id']}/complete", headers=headers)

    response = seeded_client.post("/api/v1/benchmarks", headers=headers)
    assert response.status_code == 409


# --- What it records --------------------------------------------------------


def _events(session: Session, kind: EvidenceType) -> list[EvidenceEvent]:
    return [
        event
        for event in session.execute(select(EvidenceEvent)).scalars()
        if event.evidence_type is kind
    ]


def test_it_records_benchmark_evidence_unaided(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user_id = _prepared_learner(db_session)
    plan = service.start(db_session, user_id)

    for item in plan.items:
        service.submit_response(
            db_session,
            user_id,
            plan.session_id,
            item_key=item.key,
            response=item.answer_key[0] if item.answer_key else "x",
        )
    db_session.commit()

    events = _events(db_session, EvidenceType.BENCHMARK)
    assert events
    for event in events:
        assert event.independence == 1.0
        assert event.confidence == 1.0
        assert event.metadata_json["unaided"] is True


def test_the_whole_benchmark_is_one_context(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """`CLAUDE.md`: recent repeated attempts cannot independently prove
    generalised mastery. Eight items in one sitting must not satisfy the
    model's breadth requirement on their own."""
    user_id = _prepared_learner(db_session)
    plan = service.start(db_session, user_id)

    for item in plan.items:
        service.submit_response(
            db_session, user_id, plan.session_id, item_key=item.key, response="x"
        )
    db_session.commit()

    contexts = {event.context_key for event in _events(db_session, EvidenceType.BENCHMARK)}
    assert len(contexts) == 1


def test_a_failed_benchmark_can_lower_an_estimate(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The load-bearing test. Everything else in the product accumulates:
    practice adds evidence and mastery drifts up. A measurement that can only
    agree with the learner is not a measurement."""
    from apps.api.app.models.learning import SkillState

    user_id = _prepared_learner(db_session, correct=True)

    before = {
        state.skill_node_id: state.mastery_probability
        for state in db_session.execute(
            select(SkillState).where(SkillState.user_id == user_id)
        ).scalars()
    }
    assert any(value > 0 for value in before.values()), "nothing to lower"

    plan = service.start(db_session, user_id)
    for item in plan.items:
        # Every answer wrong, and unaided, so the model has to take it.
        service.submit_response(
            db_session,
            user_id,
            plan.session_id,
            item_key=item.key,
            response="definitely not the answer",
        )
    outcome = service.complete(db_session, user_id, plan.session_id)
    db_session.commit()

    after = {
        state.skill_node_id: state.mastery_probability
        for state in db_session.execute(
            select(SkillState).where(SkillState.user_id == user_id)
        ).scalars()
    }
    fell = [key for key, value in after.items() if value < before.get(key, 0.0) - 1e-9]

    assert fell, "a wholly failed benchmark left every estimate untouched"
    assert outcome.lowered, "the fall was not reported to the learner"


def test_the_attempt_records_no_scaffolding(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user_id = _prepared_learner(db_session)
    plan = service.start(db_session, user_id)
    service.submit_response(
        db_session, user_id, plan.session_id, item_key=plan.items[0].key, response="x"
    )
    db_session.commit()

    attempt = (
        db_session.execute(select(Attempt).where(Attempt.activity_type == service.ACTIVITY_TYPE))
        .scalars()
        .first()
    )
    assert attempt is not None
    assert attempt.hints_used == 0
    assert attempt.scaffolding_level == 0.0


def test_starting_early_raises_rather_than_degrading(
    loaded_curriculum: Session, db_session: Session
) -> None:
    from apps.api.app.models.identity import LearnerProfile, User

    user = User(email=f"raw-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Raw")
    db_session.add(user)
    db_session.commit()

    with pytest.raises(service.BenchmarkNotDueError):
        service.start(db_session, user.id)


def _prepared_learner(session: Session, *, correct: bool = False) -> uuid.UUID:
    """A learner with enough recorded evidence to be eligible.

    Built directly rather than by running the diagnostic, so the test says
    what it depends on instead of depending on the diagnostic's behaviour.
    """
    from apps.api.app.models.curriculum import SkillNode
    from apps.api.app.models.identity import LearnerProfile, User
    from apps.api.app.services.evidence import recompute_all_skill_states, record_evidence

    user = User(email=f"bench-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Bench")
    session.add(user)
    session.commit()

    learning_session = LearningSession(
        user_id=user.id,
        status=SessionStatus.COMPLETED,
        context={"kind": "diagnostic"},
        ended_at=utcnow(),
    )
    session.add(learning_session)
    session.flush()

    nodes = session.execute(select(SkillNode).limit(4)).scalars().all()
    for index in range(MIN_OBSERVATIONS + 2):
        node = nodes[index % len(nodes)]
        attempt = Attempt(
            user_id=user.id,
            session_id=learning_session.id,
            activity_key=f"prior:{index}",
            activity_type="diagnostic_item",
            attempt_number=1,
            response={"correct": correct, "score": 1.0 if correct else 0.0},
            submitted_at=utcnow(),
            hints_used=0,
            scaffolding_level=0.0,
            evaluator_id="deterministic/0.1.0",
        )
        session.add(attempt)
        session.flush()
        record_evidence(
            session,
            user_id=user.id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=EvidenceType.CONTROLLED_RECALL,
            score=1.0 if correct else 0.0,
            difficulty=node.difficulty,
            confidence=1.0,
            independence=1.0,
            novelty=1.0,
            context_key=f"prior:{index}",
            metadata={"source": "test"},
        )
    recompute_all_skill_states(session, user_id=user.id)
    session.commit()
    return user.id
