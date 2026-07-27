"""Every plan item must go somewhere.

This is the invariant the study and output activities were built to satisfy.
A plan that lists six things and links two of them is not a plan the learner
can trust, and `docs/PRODUCT_SPEC.md` treats an unopenable row as a defect
rather than a missing feature.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.app.services import activities as service
from apps.api.tests.helpers import register

#: Slots that must resolve to something a learner can start. Speaking and
#: reflection have no activity behind them yet, and say so honestly rather
#: than linking somewhere wrong.
OPENABLE_KINDS = {"input", "study", "output"}

PAST_SIMPLE = "study.a2.past_simple"


def _plan(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/api/v1/plans/today", headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_every_prefixed_item_actually_opens(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "openable1@example.com")
    plan = _plan(seeded_client, headers)

    prefixed = [
        item
        for item in plan["items"]
        if service.activity_type_for(item["activity_key"]) is not None
    ]
    assert prefixed, "the plan offered nothing openable at all"

    for item in prefixed:
        response = seeded_client.get(f"/api/v1/activities/{item['activity_key']}", headers=headers)
        assert response.status_code == 200, item["activity_key"]


def test_a_new_learner_gets_an_openable_item_in_every_working_slot(
    seeded_client: TestClient,
) -> None:
    """Reading, study, and written output all resolve.

    Scoped to a new learner deliberately. With no evidence yet every
    candidate scores identically, so the planner's tie-break — prefer what a
    learner can actually start — is the only thing deciding, and this is
    where it has to hold.
    """
    headers = register(seeded_client, "openable2@example.com")
    plan = _plan(seeded_client, headers)

    filled = {item["kind"] for item in plan["items"]}
    assert filled >= OPENABLE_KINDS, f"slots left empty: {OPENABLE_KINDS - filled}"

    for item in plan["items"]:
        if item["kind"] not in OPENABLE_KINDS:
            continue
        assert service.activity_type_for(item["activity_key"]) is not None, (
            f"{item['kind']} slot fell back to a placeholder: {item['activity_key']}"
        )


def test_each_slot_is_filled_from_its_own_source(seeded_client: TestClient) -> None:
    """A study slot must not be filled with a reading text.

    Silently substituting input for study would dismantle the
    receptive/productive balance the session template exists to enforce.
    """
    headers = register(seeded_client, "openable3@example.com")
    plan = _plan(seeded_client, headers)

    expected = {
        "input": service.READING_TYPE,
        "study": service.STUDY_TYPE,
        "output": service.WRITING_TYPE,
    }
    for item in plan["items"]:
        kind = item["kind"]
        if kind not in expected:
            continue
        assert service.activity_type_for(item["activity_key"]) == expected[kind], (
            f"{kind} slot was filled with {item['activity_key']}"
        )


def test_the_plan_is_still_openable_after_a_diagnostic(seeded_client: TestClient) -> None:
    """Evidence changes the ranking; it must not reintroduce dead rows."""
    from apps.api.app.learning.items import ItemType
    from apps.api.app.services.diagnostics import items_by_key

    headers = register(seeded_client, "openable4@example.com")

    bank = items_by_key()
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]
    for _ in range(40):
        nxt = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
        if nxt["finished"]:
            break
        item = bank[nxt["item"]["key"]]
        if item.item_type is ItemType.SELF_ASSESSMENT:
            answer = "3"
        elif item.item_type is ItemType.WRITTEN_RESPONSE:
            answer = "I went to the coast last weekend and it was warm, so we swam."
        else:
            answer = item.answer_key[0]
        seeded_client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": item.key, "response": answer},
        )
    seeded_client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)

    plan = seeded_client.post(
        "/api/v1/plans/generate", headers=headers, json={"regenerate": True}
    ).json()

    for item in plan["items"]:
        if service.activity_type_for(item["activity_key"]) is None:
            continue
        response = seeded_client.get(f"/api/v1/activities/{item['activity_key']}", headers=headers)
        assert response.status_code == 200, item["activity_key"]


def test_a_recurring_error_is_answered_with_the_unit_that_drills_it(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """An error that names a feature should offer practice on that feature,
    not a note repeating that the learner keeps getting it wrong."""
    import uuid as _uuid

    from apps.api.app.models.identity import LearnerProfile, User
    from apps.api.app.services.plans import collect_candidates

    user = User(email=f"err-{_uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Learner")
    db_session.add(user)
    db_session.commit()

    unit = service.study_by_key()[PAST_SIMPLE]
    wrong = {item.key: "definitely not the answer" for item in unit.items}
    service.complete_study(
        db_session, user.id, activity_key=service.study_key_for(unit), answers=wrong
    )
    db_session.commit()

    candidates = collect_candidates(db_session, user.id)
    error_driven = [c for c in candidates if c.error_pressure > 0]
    assert error_driven, "a logged error produced no candidate"

    # Every error naming a real feature must point at a real study unit.
    for candidate in error_driven:
        assert candidate.is_openable, candidate.activity_key
        assert service.activity_type_for(candidate.activity_key) == service.STUDY_TYPE


def test_an_unnameable_error_is_not_given_a_fake_remedy(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Legacy `item.<skill>` codes name no feature, so no unit can honestly
    claim to fix them. The candidate stays unopenable rather than linking to
    something merely adjacent."""
    import uuid as _uuid

    from apps.api.app.models.identity import LearnerProfile, User
    from apps.api.app.services.errors_log import record_error
    from apps.api.app.services.plans import collect_candidates

    user = User(email=f"legacy-{_uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Learner")
    db_session.add(user)
    db_session.commit()

    record_error(
        db_session,
        user.id,
        taxonomy_code="item.grammar.past_future_basic",
        description="Difficulty with an item.",
    )
    db_session.commit()

    candidates = collect_candidates(db_session, user.id)
    legacy = next(c for c in candidates if c.activity_key == "error:item.grammar.past_future_basic")
    assert legacy.is_openable is False
