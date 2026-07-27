"""Written output tasks: the bank, opening one, and completing it.

The invariant that matters most here is honesty. Deterministic checks confirm
a learner produced connected language; they cannot confirm it was accurate.
So writing evidence is recorded at reduced *evaluator confidence*, every
result is flagged provisional, and a response too short to say anything
records no evidence at all rather than recording a bad score.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.curriculum.tasks import parse_writing_tasks
from apps.api.app.errors import ActivityNotFoundError, ActivityPayloadError
from apps.api.app.learning import taxonomy
from apps.api.app.learning.writing import DETERMINISTIC_CONFIDENCE
from apps.api.app.models.enums import EvidenceType
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import Attempt, EvidenceEvent
from apps.api.app.services import activities as service
from apps.api.tests.helpers import register

LATE_EMAIL = "write.a2.late_email"

GOOD_EMAIL = (
    "Hi Sam, I am very sorry but I will be late tomorrow morning. My train "
    "was cancelled because of a signal fault, so I have to wait for the next "
    "one. I think I will arrive at about ten o'clock. Please start the "
    "meeting without me and begin with the budget, and I will join you as "
    "soon as I get there. Sorry again for the trouble."
)


# --- The bank --------------------------------------------------------------------


def test_the_task_bank_is_valid(curriculum_dir: Path) -> None:
    assert len(parse_writing_tasks(curriculum_dir)) > 0


def test_every_task_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for task in parse_writing_tasks(curriculum_dir, known_skill_keys=known):
        assert task.skill_key in known


def test_unknown_skill_reference_is_rejected(curriculum_dir: Path) -> None:
    with pytest.raises(CurriculumError) as exc_info:
        parse_writing_tasks(curriculum_dir, known_skill_keys={"nothing.here"})
    assert any("unknown skill" in error for error in exc_info.value.errors)


def test_every_target_feature_is_a_real_feature(curriculum_dir: Path) -> None:
    """These name what a rubric evaluator must judge. A typo here would make
    the gap invisible rather than recorded."""
    for task in parse_writing_tasks(curriculum_dir):
        for code in task.target_features:
            assert taxonomy.is_known(code), code


def test_no_task_demands_wording_it_never_uses(curriculum_dir: Path) -> None:
    """Required elements are matched as literal substrings, so a requirement
    the prompt never states would mark a learner down for a word nobody asked
    them to use."""
    for task in parse_writing_tasks(curriculum_dir):
        stated = f"{task.prompt} {' '.join(task.guidance)}".lower()
        for element in task.requirements.required_elements:
            assert element in stated, f"{task.key}: {element}"


def test_requirements_are_coherent(curriculum_dir: Path) -> None:
    for task in parse_writing_tasks(curriculum_dir):
        requirements = task.requirements
        assert requirements.max_words > requirements.min_words
        assert requirements.min_sentences >= 2


def test_the_bank_spans_several_levels_and_genres(curriculum_dir: Path) -> None:
    tasks = parse_writing_tasks(curriculum_dir)
    assert len({task.cefr_level for task in tasks}) >= 3
    assert len({task.genre for task in tasks}) >= 3


def test_length_expectations_rise_with_level(curriculum_dir: Path) -> None:
    """A B2 argument that asks for as little as an A1 introduction is not a
    B2 task, whatever it says on the label."""
    tasks = parse_writing_tasks(curriculum_dir)
    lowest = min(tasks, key=lambda task: task.cefr_level.rank)
    highest = max(tasks, key=lambda task: task.cefr_level.rank)
    assert highest.requirements.min_words > lowest.requirements.min_words


def test_a_client_prompt_carries_no_rubric(curriculum_dir: Path) -> None:
    for task in parse_writing_tasks(curriculum_dir):
        assert "target_features" not in task.as_prompt()


# --- Resolving -------------------------------------------------------------------


def test_a_writing_key_resolves() -> None:
    task = service.writing_tasks()[0]
    assert service.get_activity(service.writing_key_for(task)) is task


def test_a_writing_key_is_typed_as_a_writing_task() -> None:
    task = service.writing_tasks()[0]
    assert service.activity_type_for(service.writing_key_for(task)) == service.WRITING_TYPE


def test_an_unknown_writing_key_is_rejected() -> None:
    with pytest.raises(ActivityNotFoundError):
        service.get_activity("write:does.not.exist")


# --- Completing ------------------------------------------------------------------


def test_a_good_response_passes_every_check(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    result = service.complete_writing(
        db_session, user.id, activity_key=service.writing_key_for(task), text=GOOD_EMAIL
    )
    db_session.commit()

    failed = [check.code for check in result.analysis.checks if not check.passed]
    assert failed == []
    assert result.score == 1.0


def test_writing_records_production_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The learner composed it themselves. That part is not in doubt."""
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    service.complete_writing(
        db_session, user.id, activity_key=service.writing_key_for(task), text=GOOD_EMAIL
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert event.evidence_type is EvidenceType.CONTEXTUAL_PRODUCTION


def test_countable_checks_are_recorded_as_uncertain_judgement(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Nothing here judged accuracy, and the stored confidence says so."""
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    service.complete_writing(
        db_session, user.id, activity_key=service.writing_key_for(task), text=GOOD_EMAIL
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert event.confidence == DETERMINISTIC_CONFIDENCE
    assert event.confidence < 1.0
    # Independence is full: the scaffolding question and the grading question
    # are different, and only the grading is uncertain.
    assert event.independence == 1.0
    assert event.metadata_json["provisional"] is True


def test_the_unjudged_features_are_recorded_not_hidden(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    service.complete_writing(
        db_session, user.id, activity_key=service.writing_key_for(task), text=GOOD_EMAIL
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert set(event.metadata_json["unjudged_features"]) == set(task.target_features)


def test_a_response_too_short_to_judge_records_no_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Not enough to say, and said badly, are different claims."""
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    result = service.complete_writing(
        db_session,
        user.id,
        activity_key=service.writing_key_for(task),
        text="Sorry, train broke.",
    )
    db_session.commit()

    assert result.evidence_recorded is False
    assert list(db_session.execute(select(EvidenceEvent)).scalars()) == []


def test_a_short_response_is_still_kept(loaded_curriculum: Session, db_session: Session) -> None:
    """The attempt is history even when it produced no evidence."""
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    service.complete_writing(
        db_session,
        user.id,
        activity_key=service.writing_key_for(task),
        text="Sorry, train broke.",
    )
    db_session.commit()

    attempt = db_session.execute(select(Attempt)).scalars().one()
    assert attempt.activity_type == service.WRITING_TYPE
    assert attempt.response["provisional"] is True


def test_missing_content_is_reported_specifically(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]
    long_but_off_topic = (
        "Hello there. I hope you are well and that the week has been kind to "
        "you so far. I wanted to write and let you know how things are going "
        "here, because there is quite a lot to say and I did not want to "
        "leave it any longer than I already have done. Everything is fine."
    )

    result = service.complete_writing(
        db_session,
        user.id,
        activity_key=service.writing_key_for(task),
        text=long_but_off_topic,
    )
    db_session.commit()

    assert result.analysis.word_count >= task.requirements.min_words
    assert result.analysis.missing_elements
    assert result.score < 1.0


def test_the_result_never_claims_to_have_judged_accuracy(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    result = service.complete_writing(
        db_session, user.id, activity_key=service.writing_key_for(task), text=GOOD_EMAIL
    )
    db_session.commit()

    assert result.provisional is True
    assert "grammar" in result.explanation.lower()


def test_analysis_survives_anything_the_learner_submits(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    for text in ("", "   ", "!!!", "a" * 5000):
        result = service.complete_writing(
            db_session, user.id, activity_key=service.writing_key_for(task), text=text
        )
        assert 0.0 <= result.score <= 1.0
    db_session.commit()


# --- API -------------------------------------------------------------------------


def test_opening_a_writing_task_returns_the_prompt(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "writer@example.com")
    task = service.tasks_by_key()[LATE_EMAIL]

    body = seeded_client.get(
        f"/api/v1/activities/{service.writing_key_for(task)}", headers=headers
    ).json()

    assert body["activity_type"] == "writing_task"
    assert body["prompt"]
    assert body["guidance"]
    assert body["genre"] == task.genre
    assert body["min_words"] == task.requirements.min_words


def test_the_requirements_are_shown_not_hidden(seeded_client: TestClient) -> None:
    """A word count the learner cannot see is a trap, not a requirement."""
    headers = register(seeded_client, "writer2@example.com")
    task = service.tasks_by_key()[LATE_EMAIL]

    body = seeded_client.get(
        f"/api/v1/activities/{service.writing_key_for(task)}", headers=headers
    ).json()

    assert body["max_words"] > body["min_words"]
    assert body["min_sentences"] >= 2
    assert set(body["required_elements"]) == set(task.requirements.required_elements)


def test_completing_a_writing_task_through_the_api(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "writer3@example.com")
    task = service.tasks_by_key()[LATE_EMAIL]

    body = seeded_client.post(
        f"/api/v1/activities/{service.writing_key_for(task)}/complete",
        headers=headers,
        json={"text": GOOD_EMAIL},
    ).json()

    assert body["activity_type"] == "writing_task"
    assert body["score"] == 1.0
    assert body["evidence_recorded"] is True
    assert body["provisional"] is True
    assert body["word_count"] > 0
    assert body["checks"]


def test_sending_answers_to_a_writing_task_is_a_clear_error(
    seeded_client: TestClient,
) -> None:
    headers = register(seeded_client, "writer4@example.com")
    task = service.tasks_by_key()[LATE_EMAIL]

    response = seeded_client.post(
        f"/api/v1/activities/{service.writing_key_for(task)}/complete",
        headers=headers,
        json={"answers": {"q1": "a"}},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "activity_payload_mismatch"
    assert response.json()["details"]["expected_field"] == "text"


def test_the_payload_mismatch_is_raised_by_the_service_too(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    task = service.tasks_by_key()[LATE_EMAIL]

    with pytest.raises(ActivityPayloadError):
        service.complete(
            db_session,
            user.id,
            activity_key=service.writing_key_for(task),
            answers={"q1": "a"},
        )


def test_a_completed_writing_task_reaches_the_profile(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "writer5@example.com")
    task = service.tasks_by_key()[LATE_EMAIL]

    seeded_client.post(
        f"/api/v1/activities/{service.writing_key_for(task)}/complete",
        headers=headers,
        json={"text": GOOD_EMAIL},
    )

    profile = seeded_client.get("/api/v1/profile", headers=headers).json()
    skill = next(s for s in profile["skills"] if s["skill_key"] == task.skill_key)
    assert skill["evidence_count"] == 1


def _user(session: Session) -> User:
    user = User(email=f"write-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Writer")
    session.add(user)
    session.commit()
    return user
