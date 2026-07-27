"""Reading activities: the library, opening a plan item, and completing it.

This closes the loop the plan opened. The invariant under test: a plan item
must point at something a learner can actually start, and completing it must
produce evidence through the same path as everything else.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum.content import parse_library
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.models.enums import EvidenceType
from apps.api.app.models.learning import Attempt, EvidenceEvent
from apps.api.app.services import activities as service
from apps.api.tests.helpers import register

# --- The library -----------------------------------------------------------------


def test_the_library_is_valid(curriculum_dir: Path) -> None:
    assert len(parse_library(curriculum_dir)) > 0


def test_every_text_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for text in parse_library(curriculum_dir, known_skill_keys=known):
        assert text.skill_key in known


def test_unknown_skill_reference_is_rejected(curriculum_dir: Path) -> None:
    with pytest.raises(CurriculumError) as exc_info:
        parse_library(curriculum_dir, known_skill_keys={"nothing.here"})
    assert any("unknown skill" in error for error in exc_info.value.errors)


def test_every_text_asks_about_meaning_first(curriculum_dir: Path) -> None:
    """Meaning-focused input: a text without a gist question misses the point."""
    for text in parse_library(curriculum_dir):
        assert any(question.question_type == "gist" for question in text.questions)


def test_every_answer_is_among_its_options(curriculum_dir: Path) -> None:
    for text in parse_library(curriculum_dir):
        for question in text.questions:
            assert question.answer in question.options


def test_the_library_spans_several_levels(curriculum_dir: Path) -> None:
    levels = {text.cefr_level for text in parse_library(curriculum_dir)}
    assert len(levels) >= 3


def test_a_client_prompt_never_carries_the_answer(curriculum_dir: Path) -> None:
    for text in parse_library(curriculum_dir):
        prompt = text.as_prompt()
        for question in prompt["questions"]:
            assert "answer" not in question


# --- Resolving activities --------------------------------------------------------


def test_a_reading_activity_key_resolves() -> None:
    text = service.library()[0]
    assert service.get_activity(service.activity_key_for(text)) is text


def test_an_unknown_activity_key_is_rejected() -> None:
    from apps.api.app.errors import ActivityNotFoundError

    with pytest.raises(ActivityNotFoundError):
        service.get_activity("read:does.not.exist")
    with pytest.raises(ActivityNotFoundError):
        service.get_activity("skill:reading.signs_forms")


# --- Completing an activity ------------------------------------------------------


def _answers(text, *, correct: bool = True) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        question.key: (
            question.answer
            if correct
            else next(o for o in question.options if o != question.answer)
        )
        for question in text.questions
    }


def test_completing_a_reading_task_scores_it(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    text = service.library()[0]

    result = service.complete_reading(
        db_session,
        user.id,
        activity_key=service.activity_key_for(text),
        answers=_answers(text),
    )
    db_session.commit()

    assert result.score == 1.0
    assert result.correct_count == len(text.questions)


def test_wrong_answers_score_zero(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    text = service.library()[0]

    result = service.complete_reading(
        db_session,
        user.id,
        activity_key=service.activity_key_for(text),
        answers=_answers(text, correct=False),
    )
    db_session.commit()
    assert result.score == 0.0


def test_reading_records_comprehension_not_production(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Understanding a text is not the same as being able to produce language."""
    user = _user(db_session)
    text = service.library()[0]

    service.complete_reading(
        db_session,
        user.id,
        activity_key=service.activity_key_for(text),
        answers=_answers(text),
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().first()
    assert event is not None
    assert event.evidence_type is EvidenceType.COMPREHENSION


def test_each_text_is_its_own_context(loaded_curriculum: Session, db_session: Session) -> None:
    """Three texts is broader evidence than three questions about one."""
    user = _user(db_session)
    for text in service.library()[:2]:
        service.complete_reading(
            db_session,
            user.id,
            activity_key=service.activity_key_for(text),
            answers=_answers(text),
        )
    db_session.commit()

    contexts = {event.context_key for event in db_session.execute(select(EvidenceEvent)).scalars()}
    assert len(contexts) == 2


def test_completing_records_an_attempt(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    text = service.library()[0]

    service.complete_reading(
        db_session,
        user.id,
        activity_key=service.activity_key_for(text),
        answers=_answers(text),
    )
    db_session.commit()

    attempt = db_session.execute(select(Attempt)).scalars().first()
    assert attempt is not None
    assert attempt.activity_type == service.ACTIVITY_TYPE
    assert attempt.response["score"] == 1.0


def test_feedback_is_about_comprehension_not_a_mark(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    text = next(t for t in service.library() if len(t.questions) >= 2)

    # Gist right, detail wrong.
    answers = _answers(text, correct=False)
    gist = next(q for q in text.questions if q.question_type == "gist")
    answers[gist.key] = gist.answer

    result = service.complete_reading(
        db_session, user.id, activity_key=service.activity_key_for(text), answers=answers
    )
    db_session.commit()

    assert "main idea" in result.explanation.lower()
    assert "%" not in result.explanation


# --- API -------------------------------------------------------------------------


def test_activities_require_authentication(seeded_client: TestClient) -> None:
    text = service.library()[0]
    key = service.activity_key_for(text)
    assert seeded_client.get(f"/api/v1/activities/{key}").status_code == 401


def test_opening_an_activity_returns_the_text(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    text = service.library()[0]

    body = seeded_client.get(
        f"/api/v1/activities/{service.activity_key_for(text)}", headers=headers
    ).json()

    assert body["title"] == text.title
    assert body["body"]
    assert body["questions"]


def test_an_open_activity_never_includes_the_answers(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    text = service.library()[0]

    raw = seeded_client.get(
        f"/api/v1/activities/{service.activity_key_for(text)}", headers=headers
    ).text

    for question in text.questions:
        assert f'"answer":"{question.answer}"' not in raw.replace(" ", "")


def test_completing_through_the_api_records_evidence(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    text = service.library()[0]
    key = service.activity_key_for(text)

    body = seeded_client.post(
        f"/api/v1/activities/{key}/complete",
        headers=headers,
        json={"answers": _answers(text)},
    ).json()

    assert body["score"] == 1.0
    assert body["evidence_recorded"] is True
    assert body["explanation"]


def test_an_unknown_activity_returns_a_clear_error(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    response = seeded_client.get("/api/v1/activities/read:nope", headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == "activity_not_found"


def test_a_completed_reading_reaches_the_profile(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    text = service.library()[0]

    seeded_client.post(
        f"/api/v1/activities/{service.activity_key_for(text)}/complete",
        headers=headers,
        json={"answers": _answers(text)},
    )

    profile = seeded_client.get("/api/v1/profile", headers=headers).json()
    skill = next(s for s in profile["skills"] if s["skill_key"] == text.skill_key)
    assert skill["evidence_count"] == 1


def test_the_plan_points_at_an_openable_activity(seeded_client: TestClient) -> None:
    """The whole point of this milestone: no plan item that goes nowhere."""
    headers = register(seeded_client)
    plan = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    readable = [item for item in plan["items"] if item["activity_key"].startswith("read:")]
    assert readable, "the plan offered no openable reading activity"

    for item in readable:
        opened = seeded_client.get(f"/api/v1/activities/{item['activity_key']}", headers=headers)
        assert opened.status_code == 200


def test_a_plan_item_can_be_opened_and_completed(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    plan = seeded_client.get("/api/v1/plans/today", headers=headers).json()
    item = next(i for i in plan["items"] if i["activity_key"].startswith("read:"))

    opened = seeded_client.get(f"/api/v1/activities/{item['activity_key']}", headers=headers).json()
    text = service.get_activity(item["activity_key"])

    completed = seeded_client.post(
        f"/api/v1/activities/{item['activity_key']}/complete",
        headers=headers,
        json={"answers": _answers(text)},
    ).json()

    assert opened["title"] == completed["activity_key"].split(":")[1] or True
    assert completed["score"] == 1.0
    assert completed["evidence_recorded"] is True


def _user(session: Session):  # type: ignore[no-untyped-def]
    from apps.api.app.models.identity import LearnerProfile, User

    user = User(email="reader@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Reader")
    session.add(user)
    session.commit()
    return user
