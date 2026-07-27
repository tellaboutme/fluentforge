"""Reflection: the last plan kind to get anything behind it.

Every session template has reserved four minutes for reflection since
Milestone 1, and the slot rendered unlinked the whole time.

Two claims are worth testing, and they pull in opposite directions.

**The material has to be real.** A prompt with nothing concrete in it
produces nothing worth reading, so the page is built from what the system has
actually noticed and never from anything invented.

**Nothing may be recorded from it.** A learner who writes "I need to work on
the past simple" has not demonstrated the past simple. Counting the sentence
would record an intention as an achievement, which is exactly the failure the
whole evidence model exists to prevent — and it would be the easiest one to
introduce, because reflection *feels* like learning.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.models.curriculum import SkillNode
from apps.api.app.models.enums import SessionStatus
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import (
    Attempt,
    ErrorPattern,
    EvidenceEvent,
    LearningSession,
    SkillState,
)
from apps.api.app.services import reflection as service
from apps.api.app.services.errors_log import record_error
from apps.api.tests.helpers import register


def _user(session: Session) -> User:
    user = User(email=f"reflect-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Reflector")
    session.add(user)
    session.commit()
    return user


# --- Nothing is ever recorded -----------------------------------------------


def test_a_reflection_records_no_evidence(loaded_curriculum: Session, db_session: Session) -> None:
    """The load-bearing test. Reflection feels like learning, which is what
    makes counting it the easiest mistake here to make."""
    user = _user(db_session)
    service.record(db_session, user.id, note="I keep forgetting the past simple.")
    db_session.commit()

    assert db_session.execute(select(EvidenceEvent)).scalars().all() == []


def test_it_touches_no_skill_state(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    service.record(db_session, user.id, note="I will read more.")
    db_session.commit()

    assert db_session.execute(select(SkillState)).scalars().all() == []


def test_the_attempt_says_plainly_that_nothing_judged_it(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Explicit rather than absent: a future reader should not have to infer
    it from a missing field."""
    user = _user(db_session)
    service.record(db_session, user.id, note="Slow week.")
    db_session.commit()

    attempt = db_session.execute(select(Attempt)).scalars().one()
    assert attempt.response["scored"] is False
    assert attempt.response["evidence_recorded"] is False
    assert attempt.evaluator_id == "none"


def test_the_note_is_kept_verbatim(loaded_curriculum: Session, db_session: Session) -> None:
    """It is the learner's own record. Nothing normalises or trims it beyond
    surrounding whitespace."""
    user = _user(db_session)
    service.record(db_session, user.id, note="  I don't agree with the plan.  ")
    db_session.commit()

    attempt = db_session.execute(select(Attempt)).scalars().one()
    assert attempt.response["note"] == "I don't agree with the plan."


def test_an_empty_reflection_is_accepted(loaded_curriculum: Session, db_session: Session) -> None:
    """There is no minimum. "Nothing new this week" is a real answer, and so
    is silence — refusing it would make the learner perform reflection."""
    user = _user(db_session)
    service.record(db_session, user.id, note="")
    db_session.commit()

    assert db_session.execute(select(Attempt)).scalars().one() is not None


# --- The material is real ---------------------------------------------------


def test_a_new_learner_is_offered_nothing_invented(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A prompt built from nothing would have to make something up."""
    user = _user(db_session)
    prompt = service.build_prompt(db_session, user.id)

    assert prompt.recurring_errors == ()
    assert prompt.untouched_skills == ()
    assert prompt.unjudged_count == 0
    assert prompt.previous_note is None


def test_recurring_errors_are_offered_with_a_readable_label(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    record_error(
        db_session,
        user.id,
        taxonomy_code="grammar.tense.past_simple_form",
        description="Past simple forms",
        blocks_meaning=True,
    )
    db_session.commit()

    prompt = service.build_prompt(db_session, user.id)
    assert prompt.recurring_errors
    error = prompt.recurring_errors[0]
    assert error.code == "grammar.tense.past_simple_form"
    # Clients render the label; the code is a machine identifier.
    assert error.label and error.label != error.code
    assert error.blocks_meaning is True


def test_at_most_three_errors_are_offered(loaded_curriculum: Session, db_session: Session) -> None:
    """A list of everything wrong is a list nobody acts on — the same reason
    the rubric evaluator caps its corrections."""
    user = _user(db_session)
    for code in (
        "grammar.tense.past_simple_form",
        "grammar.article.definite_indefinite",
        "lexis.confusable.pair",
        "mechanics.spelling.common",
        "discourse.cohesion.connective",
    ):
        record_error(db_session, user.id, taxonomy_code=code, description=code)
    db_session.commit()

    assert len(service.build_prompt(db_session, user.id).recurring_errors) == 3


def test_errors_that_block_meaning_come_first(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """`docs/LEARNING_SCIENCE.md`: corrections prioritise what blocks
    meaning."""
    user = _user(db_session)
    record_error(
        db_session,
        user.id,
        taxonomy_code="mechanics.spelling.common",
        description="Spelling",
        blocks_meaning=False,
    )
    record_error(
        db_session,
        user.id,
        taxonomy_code="grammar.word_order.question",
        description="Question word order",
        blocks_meaning=True,
    )
    db_session.commit()

    first = service.build_prompt(db_session, user.id).recurring_errors[0]
    assert first.blocks_meaning is True


def test_stale_skills_are_named(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    node = db_session.execute(select(SkillNode)).scalars().first()
    assert node is not None
    db_session.add(
        SkillState(
            user_id=user.id,
            skill_node_id=node.id,
            mastery_probability=0.6,
            confidence=0.5,
            last_observed_at=utcnow() - timedelta(days=service.STALE_DAYS + 3),
        )
    )
    db_session.commit()

    assert node.key in service.build_prompt(db_session, user.id).untouched_skills


def test_a_skill_touched_recently_is_not_named(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    node = db_session.execute(select(SkillNode)).scalars().first()
    assert node is not None
    db_session.add(
        SkillState(
            user_id=user.id,
            skill_node_id=node.id,
            mastery_probability=0.6,
            confidence=0.5,
            last_observed_at=utcnow() - timedelta(days=1),
        )
    )
    db_session.commit()

    assert service.build_prompt(db_session, user.id).untouched_skills == ()


def test_the_product_names_its_own_blind_spot(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Someone reflecting on their progress should not read silence as
    approval. Provisional work is work nothing judged."""
    user = _user(db_session)
    learning_session = LearningSession(
        user_id=user.id, status=SessionStatus.COMPLETED, context={"kind": "writing_lab"}
    )
    db_session.add(learning_session)
    db_session.flush()
    db_session.add(
        Attempt(
            user_id=user.id,
            session_id=learning_session.id,
            activity_key="write:x",
            activity_type="writing_task",
            attempt_number=1,
            response={"text": "…", "provisional": True},
            submitted_at=utcnow(),
            hints_used=0,
            scaffolding_level=0.0,
            evaluator_id="deterministic/0.1.0",
        )
    )
    db_session.commit()

    assert service.build_prompt(db_session, user.id).unjudged_count == 1


def test_the_previous_note_comes_back(loaded_curriculum: Session, db_session: Session) -> None:
    """Reflection that never refers back is a diary nobody rereads."""
    user = _user(db_session)
    service.record(db_session, user.id, note="Last week I said I would read more.")
    db_session.commit()

    assert (
        service.build_prompt(db_session, user.id).previous_note
        == "Last week I said I would read more."
    )


def test_the_most_recent_note_is_the_one_returned(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    service.record(db_session, user.id, note="older")
    db_session.commit()
    service.record(db_session, user.id, note="newer")
    db_session.commit()

    assert service.build_prompt(db_session, user.id).previous_note == "newer"


# --- API --------------------------------------------------------------------


def test_the_endpoint_returns_the_material(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "reflect-api@example.com")
    body = seeded_client.get("/api/v1/reflection", headers=headers).json()

    assert body["recurring_errors"] == []
    assert body["unjudged_count"] == 0
    assert body["previous_note"] is None


def test_saving_says_out_loud_that_nothing_was_scored(
    seeded_client: TestClient,
) -> None:
    """A client has no other way to know, and a screen implying otherwise
    would teach the learner to write reflections that pass checks."""
    headers = register(seeded_client, "reflect-save@example.com")
    response = seeded_client.post(
        "/api/v1/reflection", headers=headers, json={"note": "I will read more."}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["saved"] is True
    assert body["scored"] is False
    assert body["evidence_recorded"] is False


def test_a_reflection_leaves_the_profile_untouched(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "reflect-profile@example.com")
    before = seeded_client.get("/api/v1/profile", headers=headers).json()

    seeded_client.post(
        "/api/v1/reflection", headers=headers, json={"note": "Feeling better about this."}
    )

    after = seeded_client.get("/api/v1/profile", headers=headers).json()
    assert after["skills"] == before["skills"]


def test_a_reflection_comes_back_next_time(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "reflect-again@example.com")
    seeded_client.post(
        "/api/v1/reflection", headers=headers, json={"note": "Reading is the weak spot."}
    )

    body = seeded_client.get("/api/v1/reflection", headers=headers).json()
    assert body["previous_note"] == "Reading is the weak spot."


def test_one_learners_reflection_is_not_another_s(seeded_client: TestClient) -> None:
    mine = register(seeded_client, "reflect-mine@example.com")
    theirs = register(seeded_client, "reflect-theirs@example.com")
    seeded_client.post("/api/v1/reflection", headers=theirs, json={"note": "private"})

    body = seeded_client.get("/api/v1/reflection", headers=mine).json()
    assert body["previous_note"] is None


def test_the_error_code_travels_with_a_label(seeded_client: TestClient) -> None:
    """Clients render the label. A raw taxonomy code shown to a learner is a
    machine identifier leaking into the interface."""
    headers = register(seeded_client, "reflect-label@example.com")
    from apps.api.app.models.identity import User as UserModel

    body = seeded_client.get("/api/v1/reflection", headers=headers).json()
    for error in body["recurring_errors"]:
        assert error["label"]
    del UserModel


def test_reflection_is_not_in_the_activity_endpoints(seeded_client: TestClient) -> None:
    """It has no activity key: its content is whatever the system noticed
    about this learner, so there is nothing a client could name."""
    headers = register(seeded_client, "reflect-key@example.com")
    response = seeded_client.get("/api/v1/activities/reflect:daily", headers=headers)

    assert response.status_code == 404


def _unused(pattern: ErrorPattern) -> None:  # pragma: no cover - import anchor
    del pattern


def test_reflecting_twice_in_one_sitting_works(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Found by the test above, not by review. Reflections reuse one session
    and one key, so the second one collided on
    `(session_id, activity_key, attempt_number)` and crashed. Unlike
    everywhere else in the product a repeat is not weaker evidence here,
    because there is no evidence — the number is only a counter."""
    user = _user(db_session)
    service.record(db_session, user.id, note="first")
    db_session.commit()
    service.record(db_session, user.id, note="second")
    db_session.commit()

    notes = [attempt.response["note"] for attempt in db_session.execute(select(Attempt)).scalars()]
    assert sorted(notes) == ["first", "second"]
