"""Taking your data with you, and making it stop existing.

`docs/PRIVACY_SAFETY.md` has listed "Provide export and deletion" under data
minimisation since the beginning, and nothing implemented either. That is a
worse gap than an ordinary missing feature: this product stores what a person
wrote and said -- every piece of writing, every transcript of their own
speech, every mistake it noticed -- and they had no way to take it with them
or make it stop existing.

The tests fall into three groups.

- **The export is the rows.** A learner's own words come back verbatim, and
  the reasoning behind every estimate comes with them, because someone who
  disagrees with a judgement can only check the working if they have it.
- **The export says what it leaves out.** An export that silently omits
  something invites the reader to conclude they received everything.
- **Deletion is real and hard to do by accident.** Nothing is left behind in
  any table, and it takes both the password and a typed phrase.
"""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.models.curriculum import SkillNode
from apps.api.app.models.enums import EvidenceType, SessionStatus
from apps.api.app.models.identity import User
from apps.api.app.models.learning import (
    Attempt,
    ErrorPattern,
    EvidenceEvent,
    LearningSession,
    SkillState,
)
from apps.api.app.models.planning import Plan, PlanItem, ReviewQueueItem
from apps.api.app.routers.account import CONFIRM_PHRASE
from apps.api.tests.helpers import VALID_PASSWORD, register

WRITING = "Last weekend I visited my sister in Kraków. We walked by the river."


def _account(client: TestClient, email: str) -> tuple[dict[str, str], uuid.UUID]:
    headers = register(client, email)
    user_id = uuid.UUID(client.get("/api/v1/profile", headers=headers).json()["user_id"])
    return headers, user_id


def _history(session: Session, user_id: uuid.UUID) -> None:
    """A learner with something worth exporting."""
    node = session.execute(select(SkillNode).order_by(SkillNode.key)).scalars().first()

    learning_session = LearningSession(
        user_id=user_id, status=SessionStatus.COMPLETED, context={"kind": "writing_lab"}
    )
    session.add(learning_session)
    session.flush()

    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key="write:weekend",
        activity_type="writing_task",
        attempt_number=1,
        response={"text": WRITING, "score": 0.8, "checks": [{"code": "length", "passed": True}]},
        submitted_at=utcnow(),
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id="deterministic/0.1.0",
    )
    session.add(attempt)
    session.flush()

    session.add(
        EvidenceEvent(
            user_id=user_id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=EvidenceType.CONTEXTUAL_PRODUCTION,
            score=0.8,
            context_key="task:weekend",
        )
    )
    session.add(
        SkillState(
            user_id=user_id,
            skill_node_id=node.id,
            mastery_probability=0.6,
            confidence=0.4,
            distinct_contexts=2,
            evidence_count=3,
            last_observed_at=utcnow(),
        )
    )
    session.add(
        ErrorPattern(
            user_id=user_id,
            taxonomy_code="grammar.tense.past_simple_form",
            canonical_description="Past simple forms",
            occurrence_count=3,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
            blocks_meaning=True,
            examples=["I go to the shop yesterday"],
        )
    )

    plan = Plan(user_id=user_id, plan_date=utcnow().date(), requested_minutes=40)
    session.add(plan)
    session.flush()
    session.add(
        PlanItem(
            plan_id=plan.id,
            sequence=1,
            activity_key="write:weekend",
            activity_type="writing_task",
            estimated_minutes=15,
            reason_codes=["EXPECTED_GAIN"],
            priority_components={"components": {"expected_gain": 0.3, "goal_relevance": 0.0}},
        )
    )
    session.commit()


def _export(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get("/api/v1/account/export", headers=headers)
    assert response.status_code == 200, response.text
    return json.loads(response.content)


# --- What the export contains -----------------------------------------------


def test_the_learner_s_own_words_come_back_verbatim(
    seeded_client: TestClient, db_session: Session
) -> None:
    """A summary would be the product deciding which parts of a person's own
    work they are allowed to have."""
    headers, user_id = _account(seeded_client, "export-words@example.com")
    _history(db_session, user_id)

    body = _export(seeded_client, headers)

    assert body["attempts"][0]["response"]["text"] == WRITING


def test_the_feedback_is_included_as_it_was_recorded(
    seeded_client: TestClient, db_session: Session
) -> None:
    """Never recomputed, for the same reason the history endpoint refuses to
    recompute it."""
    headers, user_id = _account(seeded_client, "export-feedback@example.com")
    _history(db_session, user_id)

    body = _export(seeded_client, headers)

    assert body["attempts"][0]["response"]["checks"] == [{"code": "length", "passed": True}]


def test_the_evidence_behind_the_profile_is_included(
    seeded_client: TestClient, db_session: Session
) -> None:
    """Someone who disagrees with an estimate can only check the working if
    they can see the observations behind it."""
    headers, user_id = _account(seeded_client, "export-evidence@example.com")
    _history(db_session, user_id)

    body = _export(seeded_client, headers)

    assert len(body["evidence"]) == 1
    assert body["evidence"][0]["score"] == 0.8
    assert body["evidence"][0]["context_key"] == "task:weekend"


def test_the_plan_reasoning_is_included(seeded_client: TestClient, db_session: Session) -> None:
    """Including components that scored zero. The learner is entitled to the
    reasoning, not only the outcome."""
    headers, user_id = _account(seeded_client, "export-plans@example.com")
    _history(db_session, user_id)

    body = _export(seeded_client, headers)
    item = body["plans"][0]["items"][0]

    assert item["reason_codes"] == ["EXPECTED_GAIN"]
    assert item["priority_components"]["components"]["goal_relevance"] == 0.0


def test_errors_and_review_cards_are_included(
    seeded_client: TestClient, db_session: Session
) -> None:
    headers, user_id = _account(seeded_client, "export-errors@example.com")
    _history(db_session, user_id)

    body = _export(seeded_client, headers)

    assert body["error_patterns"][0]["taxonomy_code"] == "grammar.tense.past_simple_form"
    assert body["error_patterns"][0]["examples"] == ["I go to the shop yesterday"]
    assert isinstance(body["review_queue"], list)


def test_the_password_hash_is_never_exported(
    seeded_client: TestClient, db_session: Session
) -> None:
    headers, user_id = _account(seeded_client, "export-secret@example.com")
    _history(db_session, user_id)

    raw = seeded_client.get("/api/v1/account/export", headers=headers).text

    assert "password" not in raw.lower() or "No password" in raw
    assert VALID_PASSWORD not in raw


def test_it_says_what_it_does_not_contain(seeded_client: TestClient) -> None:
    """An export that silently omits something is worse than none at all: it
    invites the reader to conclude they received everything."""
    headers, _ = _account(seeded_client, "export-gaps@example.com")

    body = _export(seeded_client, headers)

    assert body["not_included"]
    assert any("audio" in note.lower() for note in body["not_included"])


def test_it_is_returned_as_a_file_and_never_cached(seeded_client: TestClient) -> None:
    """The most sensitive response the product produces. A shared or proxy
    cache holding it would be a straightforward leak."""
    headers, _ = _account(seeded_client, "export-headers@example.com")

    response = seeded_client.get("/api/v1/account/export", headers=headers)

    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"


def test_a_new_learner_gets_an_export_rather_than_an_error(
    seeded_client: TestClient,
) -> None:
    """Someone checking what is held about them on day one should get an
    honest empty answer, not a failure."""
    headers, _ = _account(seeded_client, "export-empty@example.com")

    body = _export(seeded_client, headers)

    assert body["attempts"] == []
    assert body["profile"]["display_name"]
    assert body["not_included"]


def test_one_learner_never_exports_another(seeded_client: TestClient, db_session: Session) -> None:
    headers, _ = _account(seeded_client, "export-mine@example.com")
    _, theirs = _account(seeded_client, "export-theirs@example.com")
    _history(db_session, theirs)

    body = _export(seeded_client, headers)

    assert body["attempts"] == []
    assert body["evidence"] == []


def test_export_needs_an_account(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/v1/account/export").status_code == 401


# --- Deletion ---------------------------------------------------------------


def _delete(
    client: TestClient,
    headers: dict[str, str],
    *,
    password: str = VALID_PASSWORD,
    confirm: str = CONFIRM_PHRASE,
):
    return client.post(
        "/api/v1/account/delete",
        json={"password": password, "confirm": confirm},
        headers=headers,
    )


def test_deleting_removes_the_account(seeded_client: TestClient, db_session: Session) -> None:
    headers, user_id = _account(seeded_client, "delete-me@example.com")
    _history(db_session, user_id)

    assert _delete(seeded_client, headers).status_code == 204

    db_session.expire_all()
    assert db_session.get(User, user_id) is None


def test_nothing_is_left_behind_in_any_table(
    seeded_client: TestClient, db_session: Session
) -> None:
    """The load-bearing test. A hand-written cascade drifts from the schema
    the first time a table is added, and the failure mode is a table quietly
    still holding somebody's writing."""
    headers, user_id = _account(seeded_client, "delete-clean@example.com")
    _history(db_session, user_id)

    _delete(seeded_client, headers)
    db_session.expire_all()

    for model in (
        LearningSession,
        Attempt,
        EvidenceEvent,
        SkillState,
        ErrorPattern,
        Plan,
        ReviewQueueItem,
    ):
        remaining = (
            db_session.execute(select(model).where(model.user_id == user_id)).scalars().all()
        )
        assert remaining == [], f"{model.__name__} still holds rows for a deleted learner"


def test_plan_items_go_with_their_plan(seeded_client: TestClient, db_session: Session) -> None:
    """`plan_items` has no `user_id`, so it can only be reached through the
    plan -- exactly the shape a hand-written cascade forgets."""
    headers, user_id = _account(seeded_client, "delete-planitems@example.com")
    _history(db_session, user_id)
    plan_id = db_session.execute(select(Plan.id).where(Plan.user_id == user_id)).scalars().one()

    _delete(seeded_client, headers)
    db_session.expire_all()

    assert (
        db_session.execute(select(PlanItem).where(PlanItem.plan_id == plan_id)).scalars().all()
        == []
    )


def test_the_wrong_password_deletes_nothing(seeded_client: TestClient, db_session: Session) -> None:
    """A session token is not enough authorisation to destroy a year of
    somebody's work."""
    headers, user_id = _account(seeded_client, "delete-wrongpass@example.com")

    response = _delete(seeded_client, headers, password="not-the-password")

    assert response.status_code == 401
    db_session.expire_all()
    assert db_session.get(User, user_id) is not None


def test_a_mistyped_confirmation_is_not_reported_as_a_bad_password(
    seeded_client: TestClient, db_session: Session
) -> None:
    """Telling someone their password was wrong when they mistyped a
    confirmation sends them to reset a password that was fine."""
    headers, user_id = _account(seeded_client, "delete-confirm@example.com")

    response = _delete(seeded_client, headers, confirm="delete")

    assert response.status_code == 422
    assert "not_confirmed" in response.text
    db_session.expire_all()
    assert db_session.get(User, user_id) is not None


def test_the_confirmation_is_case_and_space_forgiving(
    seeded_client: TestClient, db_session: Session
) -> None:
    """It exists to stop an accidental click, not to test typing. Refusing
    `Delete My Account ` would be pedantry at someone's most stressed
    moment."""
    headers, user_id = _account(seeded_client, "delete-loose@example.com")

    assert _delete(seeded_client, headers, confirm="  Delete My Account ").status_code == 204

    db_session.expire_all()
    assert db_session.get(User, user_id) is None


def test_deletion_needs_an_account(seeded_client: TestClient) -> None:
    assert (
        seeded_client.post(
            "/api/v1/account/delete",
            json={"password": VALID_PASSWORD, "confirm": CONFIRM_PHRASE},
        ).status_code
        == 401
    )


def test_deleting_one_learner_leaves_another_alone(
    seeded_client: TestClient, db_session: Session
) -> None:
    mine, _ = _account(seeded_client, "delete-a@example.com")
    _, theirs = _account(seeded_client, "delete-b@example.com")
    _history(db_session, theirs)

    _delete(seeded_client, mine)
    db_session.expire_all()

    assert db_session.get(User, theirs) is not None
    assert (
        db_session.execute(select(Attempt).where(Attempt.user_id == theirs)).scalars().all() != []
    )


def test_the_token_stops_working_afterwards(seeded_client: TestClient) -> None:
    """The account is gone, so the session must be too. A token that still
    resolved would be authenticating as nobody."""
    headers, _ = _account(seeded_client, "delete-token@example.com")

    _delete(seeded_client, headers)

    assert seeded_client.get("/api/v1/profile", headers=headers).status_code in (401, 404)
