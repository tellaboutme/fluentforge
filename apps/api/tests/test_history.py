"""A learner's own past work.

`GET /attempts/{id}/feedback` sat in the API contract from the beginning and
unimplemented. Everything a learner produced was stored and unreachable: they
saw their feedback once, on the screen that produced it, and then it was
gone — which is a strange arrangement for a product whose central claim is
that the profile is made of evidence the learner actually produced.

Three properties are worth defending, and each is a refusal:

- **Nothing is recomputed.** The stored response comes back verbatim. The
  checks, the curriculum version and the evaluator may all have moved since,
  and re-deriving would show the learner a verdict nobody ever gave them.
- **Reading your history is not an attempt.** No evidence, no re-scoring. A
  system that recorded it would be counting rereading as practice.
- **Another learner's attempt is indistinguishable from a missing one.**
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.models.enums import SessionStatus
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import Attempt, EvidenceEvent, LearningSession
from apps.api.app.services import history as service
from apps.api.tests.helpers import register


def _learner(session: Session) -> User:
    user = User(email=f"hist-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Historian")
    session.add(user)
    session.commit()
    return user


def _attempt(
    session: Session,
    user: User,
    *,
    key: str = "write:x",
    activity_type: str = "writing_task",
    response: dict | None = None,
    minutes_ago: int = 0,
    evaluator: str = "deterministic/0.1.0",
) -> Attempt:
    learning_session = LearningSession(
        user_id=user.id, status=SessionStatus.COMPLETED, context={"kind": "writing_lab"}
    )
    session.add(learning_session)
    session.flush()
    attempt = Attempt(
        user_id=user.id,
        session_id=learning_session.id,
        activity_key=key,
        activity_type=activity_type,
        attempt_number=1,
        response=response if response is not None else {"text": "Some writing.", "score": 0.75},
        submitted_at=utcnow() - timedelta(minutes=minutes_ago),
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id=evaluator,
    )
    session.add(attempt)
    session.commit()
    return attempt


# --- The list ---------------------------------------------------------------


def test_a_new_learner_has_no_history(loaded_curriculum: Session, db_session: Session) -> None:
    user = _learner(db_session)
    assert service.recent(db_session, user.id) == []


def test_newest_first(loaded_curriculum: Session, db_session: Session) -> None:
    user = _learner(db_session)
    _attempt(db_session, user, key="write:old", minutes_ago=60)
    _attempt(db_session, user, key="write:new", minutes_ago=1)

    keys = [entry.activity_key for entry in service.recent(db_session, user.id)]
    assert keys == ["write:new", "write:old"]


def test_the_summary_uses_the_learner_s_own_words(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A list of scores does not tell someone which piece of work they are
    looking at."""
    user = _learner(db_session)
    _attempt(db_session, user, response={"text": "Last weekend I visited my sister.", "score": 1.0})

    assert "visited my sister" in service.recent(db_session, user.id)[0].summary


def test_a_long_answer_is_shortened_for_the_list(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)
    _attempt(db_session, user, response={"text": "word " * 400, "score": 1.0})

    assert len(service.recent(db_session, user.id)[0].summary) <= 120


def test_a_closed_activity_is_summarised_by_its_answers(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """There are no words of the learner's own to show."""
    user = _learner(db_session)
    _attempt(
        db_session,
        user,
        key="read:x",
        activity_type="reading_task",
        response={"answers": {"a": "1", "b": "2"}, "score": 0.5},
    )

    assert service.recent(db_session, user.id)[0].summary == "2 answers"


def test_a_reflection_appears_but_is_marked_unjudged(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Hiding it would leave a gap in the learner's own record with no
    explanation; showing it with a score would invent one."""
    user = _learner(db_session)
    _attempt(
        db_session,
        user,
        key="reflect:daily",
        activity_type="reflection",
        response={"note": "Reading is slow.", "scored": False},
    )

    entry = service.recent(db_session, user.id)[0]
    assert entry.was_judged is False
    assert entry.score is None
    assert "Reading is slow" in entry.summary


def test_the_page_is_capped(loaded_curriculum: Session, db_session: Session) -> None:
    user = _learner(db_session)
    for index in range(service.PAGE_SIZE + 10):
        _attempt(db_session, user, key=f"write:{index}", minutes_ago=index)

    assert len(service.recent(db_session, user.id)) == service.PAGE_SIZE


def test_paging_uses_a_cursor_rather_than_an_offset(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A learner scrolling back while new attempts arrive would otherwise see
    items shift between pages."""
    user = _learner(db_session)
    for index in range(6):
        _attempt(db_session, user, key=f"write:{index}", minutes_ago=index)

    first = service.recent(db_session, user.id, limit=3)
    second = service.recent(db_session, user.id, limit=3, before=first[-1].submitted_at)

    assert {entry.activity_key for entry in first}.isdisjoint(
        entry.activity_key for entry in second
    )


def test_one_learner_never_sees_another_s_history(
    loaded_curriculum: Session, db_session: Session
) -> None:
    mine = _learner(db_session)
    theirs = _learner(db_session)
    _attempt(db_session, theirs, key="write:private")

    assert service.recent(db_session, mine.id) == []


# --- One attempt in full ----------------------------------------------------


def test_the_stored_response_comes_back_verbatim(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The load-bearing property. Recomputing would show a verdict nobody
    ever gave, whenever the checks or the evaluator have moved since."""
    user = _learner(db_session)
    stored = {
        "text": "Some writing.",
        "score": 0.75,
        "checks": [{"code": "length", "passed": True}],
    }
    attempt = _attempt(db_session, user, response=stored)

    found = service.feedback(db_session, user.id, attempt.id)
    assert found.response == stored


def test_it_says_which_evaluator_produced_the_feedback(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A learner comparing two pieces of feedback deserves to know whether
    the same thing judged them."""
    user = _learner(db_session)
    attempt = _attempt(db_session, user, evaluator="cloud/0.2.0")

    assert service.feedback(db_session, user.id, attempt.id).evaluator_id == "cloud/0.2.0"


def test_judged_feedback_is_marked_as_a_record_rather_than_a_current_verdict(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)
    attempt = _attempt(db_session, user)

    assert service.feedback(db_session, user.id, attempt.id).is_stale is True


def test_a_reflection_is_not_marked_stale(loaded_curriculum: Session, db_session: Session) -> None:
    """Nothing judged it, so there is no verdict that could have aged."""
    user = _learner(db_session)
    attempt = _attempt(
        db_session,
        user,
        key="reflect:daily",
        activity_type="reflection",
        response={"note": "x", "scored": False},
    )

    found = service.feedback(db_session, user.id, attempt.id)
    assert found.was_judged is False
    assert found.is_stale is False


def test_reading_history_records_no_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A system that recorded it would be counting rereading as practice."""
    user = _learner(db_session)
    attempt = _attempt(db_session, user)
    before = len(db_session.execute(select(EvidenceEvent)).scalars().all())

    service.recent(db_session, user.id)
    service.feedback(db_session, user.id, attempt.id)
    db_session.commit()

    after = len(db_session.execute(select(EvidenceEvent)).scalars().all())
    assert after == before


def test_reading_history_creates_no_new_attempt(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)
    attempt = _attempt(db_session, user)

    service.feedback(db_session, user.id, attempt.id)
    db_session.commit()

    assert len(db_session.execute(select(Attempt)).scalars().all()) == 1


# --- API --------------------------------------------------------------------


def test_the_history_endpoint_returns_a_page(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "hist-api@example.com")
    body = seeded_client.get("/api/v1/attempts", headers=headers).json()

    assert body["items"] == []
    assert body["next_before"] is None


def test_feedback_is_reachable_after_completing_something(
    seeded_client: TestClient,
) -> None:
    """The whole point: a learner can look at their own work again."""
    headers = register(seeded_client, "hist-flow@example.com")
    seeded_client.post("/api/v1/reflection", headers=headers, json={"note": "Questions are hard."})

    page = seeded_client.get("/api/v1/attempts", headers=headers).json()
    assert len(page["items"]) == 1

    detail = seeded_client.get(
        f"/api/v1/attempts/{page['items'][0]['attempt_id']}/feedback", headers=headers
    ).json()
    assert detail["response"]["note"] == "Questions are hard."
    assert detail["was_judged"] is False


def test_another_learners_attempt_is_indistinguishable_from_a_missing_one(
    seeded_client: TestClient,
) -> None:
    """A different status code for "someone else's" would leak which
    attempts exist."""
    mine = register(seeded_client, "hist-mine@example.com")
    theirs = register(seeded_client, "hist-theirs@example.com")
    seeded_client.post("/api/v1/reflection", headers=theirs, json={"note": "private"})
    page = seeded_client.get("/api/v1/attempts", headers=theirs).json()
    attempt_id = page["items"][0]["attempt_id"]

    mine_response = seeded_client.get(f"/api/v1/attempts/{attempt_id}/feedback", headers=mine)
    missing = seeded_client.get(f"/api/v1/attempts/{uuid.uuid4()}/feedback", headers=mine)

    assert mine_response.status_code == missing.status_code == 404
    assert mine_response.json()["code"] == missing.json()["code"]


def test_history_requires_a_learner(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/v1/attempts").status_code == 401


def test_the_page_size_cannot_be_pushed_past_the_cap(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "hist-cap@example.com")
    assert (
        seeded_client.get(
            f"/api/v1/attempts?limit={service.PAGE_SIZE + 1}", headers=headers
        ).status_code
        == 422
    )
