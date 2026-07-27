"""Focused study units: the bank, opening one, and completing it.

Two invariants carry most of the weight here.

*Scaffolded work is weaker evidence.* The explanation is on screen while the
learner practises, so a perfect study score must not count as unaided recall.

*A mistake gets a name.* Each item declares the linguistic feature it
exercises, so a wrong answer becomes a specific, practisable error pattern
rather than "something in this skill went wrong".
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.curriculum.study import StudyUnit, parse_study_units
from apps.api.app.errors import ActivityNotFoundError, ActivityPayloadError
from apps.api.app.learning import taxonomy
from apps.api.app.models.enums import EvidenceType
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import Attempt, ErrorPattern, EvidenceEvent
from apps.api.app.models.planning import ReviewQueueItem
from apps.api.app.services import activities as service
from apps.api.tests.helpers import register

PAST_SIMPLE = "study.a2.past_simple"


# --- The bank --------------------------------------------------------------------


def test_the_study_bank_is_valid(curriculum_dir: Path) -> None:
    assert len(parse_study_units(curriculum_dir)) > 0


def test_every_unit_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for unit in parse_study_units(curriculum_dir, known_skill_keys=known):
        assert unit.skill_key in known


def test_unknown_skill_reference_is_rejected(curriculum_dir: Path) -> None:
    with pytest.raises(CurriculumError) as exc_info:
        parse_study_units(curriculum_dir, known_skill_keys={"nothing.here"})
    assert any("unknown skill" in error for error in exc_info.value.errors)


def test_every_item_names_a_real_feature(curriculum_dir: Path) -> None:
    """An error the taxonomy cannot name is an error nothing can practise."""
    for unit in parse_study_units(curriculum_dir):
        for item in unit.items:
            assert taxonomy.is_known(item.feature), item.feature


def test_every_item_explains_its_answer(curriculum_dir: Path) -> None:
    """A study unit whose feedback is only right/wrong is a quiz, not study."""
    for unit in parse_study_units(curriculum_dir):
        for item in unit.items:
            assert len(item.note) > 15, f"{unit.key}/{item.key}"


def test_every_item_shows_where_the_answer_goes(curriculum_dir: Path) -> None:
    for unit in parse_study_units(curriculum_dir):
        for item in unit.items:
            assert "___" in item.prompt, f"{unit.key}/{item.key}"


def test_every_answer_is_accepted_by_its_own_item(curriculum_dir: Path) -> None:
    for unit in parse_study_units(curriculum_dir):
        for item in unit.items:
            assert item.matches(item.answer)
            assert item.matches(item.answer.upper())


def test_no_distractor_is_also_correct(curriculum_dir: Path) -> None:
    for unit in parse_study_units(curriculum_dir):
        for item in unit.items:
            for option in item.options:
                if option != item.answer:
                    assert not item.matches(option), f"{unit.key}/{item.key}: {option}"


def test_the_bank_spans_several_levels(curriculum_dir: Path) -> None:
    levels = {unit.cefr_level for unit in parse_study_units(curriculum_dir)}
    assert len(levels) >= 3


def test_a_client_prompt_carries_neither_answer_nor_note(curriculum_dir: Path) -> None:
    for unit in parse_study_units(curriculum_dir):
        for entry in unit.as_prompt()["items"]:
            assert "answer" not in entry
            assert "note" not in entry


def test_a_unit_reports_the_features_it_covers() -> None:
    unit = service.study_by_key()[PAST_SIMPLE]
    assert "grammar.tense.past_simple_form" in unit.features
    assert unit.covers("grammar.tense.past_simple_form")
    assert not unit.covers("pronunciation.stress.word")


def test_features_are_reported_once_each() -> None:
    """Three items on one feature is one feature, not three."""
    unit = service.study_by_key()[PAST_SIMPLE]
    assert len(unit.features) == len(set(unit.features))


# --- Resolving -------------------------------------------------------------------


def test_a_study_key_resolves() -> None:
    unit = service.study_units()[0]
    assert service.get_activity(service.study_key_for(unit)) is unit


def test_a_study_key_is_typed_as_a_study_task() -> None:
    unit = service.study_units()[0]
    assert service.activity_type_for(service.study_key_for(unit)) == service.STUDY_TYPE


def test_an_unknown_study_key_is_rejected() -> None:
    with pytest.raises(ActivityNotFoundError):
        service.get_activity("study:does.not.exist")


def test_a_reading_key_is_not_a_study_unit() -> None:
    with pytest.raises(ActivityNotFoundError):
        service.get_study("read:text.a1.noticeboard")


def test_units_can_be_found_by_the_feature_they_practise() -> None:
    """This is what lets a recurring error become something openable."""
    units = service.study_for_feature("grammar.tense.past_simple_form")
    assert any(unit.key == PAST_SIMPLE for unit in units)


def test_a_feature_nothing_practises_finds_nothing() -> None:
    assert service.study_for_feature("who.knows.what") == ()


# --- Completing ------------------------------------------------------------------


def _answers(unit: StudyUnit, *, correct: bool = True) -> dict[str, str]:
    if correct:
        return {item.key: item.answer for item in unit.items}
    return {item.key: "definitely not the answer" for item in unit.items}


def test_completing_a_study_unit_scores_it(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    result = service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit),
    )
    db_session.commit()

    assert result.score == 1.0
    assert result.correct_count == len(unit.items)


def test_gap_fill_grading_forgives_case_and_spacing(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]
    answers = {item.key: f"  {item.answer.upper()}  " for item in unit.items}

    # Choice items are matched the same way, so upper-casing an option is
    # still correct — the learner picked the right one either way.
    result = service.complete_study(
        db_session, user.id, activity_key=service.study_key_for(unit), answers=answers
    )
    db_session.commit()
    assert result.score == 1.0


def test_a_missing_answer_is_simply_wrong(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    result = service.complete_study(
        db_session, user.id, activity_key=service.study_key_for(unit), answers={}
    )
    db_session.commit()
    assert result.score == 0.0


def test_study_records_controlled_recall_not_free_production(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit),
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert event.evidence_type is EvidenceType.CONTROLLED_RECALL


def test_a_visible_explanation_makes_the_evidence_weaker(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The core invariant: help on screen means this is not unaided recall."""
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    result = service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit),
    )
    db_session.commit()

    assert result.independence < 1.0
    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert event.independence == result.independence


def test_revealing_hints_weakens_it_further(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]
    key = service.study_key_for(unit)

    unaided = service.complete_study(db_session, user.id, activity_key=key, answers=_answers(unit))
    helped = service.complete_study(
        db_session, user.id, activity_key=key, answers=_answers(unit), hints_used=2
    )
    db_session.commit()

    assert helped.independence < unaided.independence


def test_independence_never_reaches_zero(loaded_curriculum: Session, db_session: Session) -> None:
    """A learner who revealed everything still produced something."""
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    result = service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit),
        hints_used=99,
    )
    db_session.commit()
    assert result.independence >= service.MIN_INDEPENDENCE


def test_the_unit_is_one_context_however_many_items(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit),
    )
    db_session.commit()

    events = list(db_session.execute(select(EvidenceEvent)).scalars())
    assert len(events) == 1
    assert events[0].context_key == f"study:{unit.key}"


def test_completing_records_an_attempt_with_its_scaffolding(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit),
        hints_used=1,
    )
    db_session.commit()

    attempt = db_session.execute(select(Attempt)).scalars().one()
    assert attempt.activity_type == service.STUDY_TYPE
    assert attempt.hints_used == 1
    assert attempt.scaffolding_level > 0.0


# --- Errors get a name -----------------------------------------------------------


def test_a_wrong_answer_becomes_a_named_error(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    result = service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit, correct=False),
    )
    db_session.commit()

    patterns = list(db_session.execute(select(ErrorPattern)).scalars())
    codes = {pattern.taxonomy_code for pattern in patterns}

    assert codes == set(result.logged_features)
    assert codes == set(unit.features)
    # Every code is a real feature, not a skill key.
    for code in codes:
        assert taxonomy.is_known(code)
        assert not taxonomy.is_legacy(code)


def test_two_slips_on_one_feature_count_once(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """One sitting is one observation of a weakness, whatever the item count.

    Counting per item would let a single unit push a feature past the
    recurrence threshold on its own — the "recent repeated attempts cannot
    prove generalised mastery" invariant, read backwards.
    """
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]
    feature = "grammar.tense.past_simple_form"
    repeated = [item for item in unit.items if item.feature == feature]
    assert len(repeated) >= 2, "this test needs a unit with a repeated feature"

    service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit, correct=False),
    )
    db_session.commit()

    pattern = db_session.execute(
        select(ErrorPattern).where(ErrorPattern.taxonomy_code == feature)
    ).scalar_one()
    assert pattern.occurrence_count == 1


def test_a_correct_unit_logs_nothing(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    result = service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit),
    )
    db_session.commit()

    assert result.logged_features == ()
    assert list(db_session.execute(select(ErrorPattern)).scalars()) == []


def test_a_meaning_blocking_error_schedules_practice_immediately(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]
    blocking = [f for f in unit.features if taxonomy.blocks_meaning_default(f)]
    assert blocking, "this test needs a unit covering a meaning-blocking feature"

    service.complete_study(
        db_session,
        user.id,
        activity_key=service.study_key_for(unit),
        answers=_answers(unit, correct=False),
    )
    db_session.commit()

    cards = db_session.execute(select(ReviewQueueItem)).scalars()
    scheduled = {card.memory_object_key for card in cards}
    assert set(blocking) <= scheduled


def test_feedback_names_what_to_look_at_again(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    answers = _answers(unit)
    last = unit.items[-1]
    answers[last.key] = "not it"

    result = service.complete_study(
        db_session, user.id, activity_key=service.study_key_for(unit), answers=answers
    )
    db_session.commit()

    assert taxonomy.label_for(last.feature) in result.explanation
    assert "%" not in result.explanation


# --- API -------------------------------------------------------------------------


def test_opening_a_study_unit_returns_the_explanation(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "study@example.com")
    unit = service.study_by_key()[PAST_SIMPLE]

    body = seeded_client.get(
        f"/api/v1/activities/{service.study_key_for(unit)}", headers=headers
    ).json()

    assert body["activity_type"] == "study_task"
    assert body["explanation"]
    assert body["examples"]
    assert len(body["items"]) == len(unit.items)
    assert body["items"][0]["feature_label"]


def test_an_open_study_unit_withholds_answers_and_notes(seeded_client: TestClient) -> None:
    """The note is the teaching moment; it has to come after the attempt.

    The answer itself cannot be checked by substring — a study unit's
    explanation legitimately contains the forms it teaches — so the guarantee
    is structural: the opened payload has no such fields at all.
    """
    headers = register(seeded_client, "study2@example.com")
    unit = service.study_by_key()[PAST_SIMPLE]

    body = seeded_client.get(
        f"/api/v1/activities/{service.study_key_for(unit)}", headers=headers
    ).json()

    for entry in body["items"]:
        assert "answer" not in entry
        assert "note" not in entry
        assert "accepted" not in entry


def test_completing_a_study_unit_through_the_api(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "study3@example.com")
    unit = service.study_by_key()[PAST_SIMPLE]
    key = service.study_key_for(unit)

    body = seeded_client.post(
        f"/api/v1/activities/{key}/complete",
        headers=headers,
        json={"answers": _answers(unit)},
    ).json()

    assert body["activity_type"] == "study_task"
    assert body["score"] == 1.0
    assert body["evidence_recorded"] is True
    assert body["independence"] < 1.0
    # Notes are revealed only after submission — that is the teaching moment.
    assert all(outcome["note"] for outcome in body["results"])


def test_sending_writing_text_to_a_study_unit_is_a_clear_error(
    seeded_client: TestClient,
) -> None:
    headers = register(seeded_client, "study4@example.com")
    unit = service.study_by_key()[PAST_SIMPLE]

    response = seeded_client.post(
        f"/api/v1/activities/{service.study_key_for(unit)}/complete",
        headers=headers,
        json={"text": "I wrote an essay instead."},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "activity_payload_mismatch"
    assert response.json()["details"]["expected_field"] == "answers"


def test_the_payload_mismatch_is_raised_by_the_service_too(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    unit = service.study_by_key()[PAST_SIMPLE]

    with pytest.raises(ActivityPayloadError):
        service.complete(
            db_session, user.id, activity_key=service.study_key_for(unit), text="wrong shape"
        )


def test_a_completed_study_unit_reaches_the_profile(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "study5@example.com")
    unit = service.study_by_key()[PAST_SIMPLE]

    seeded_client.post(
        f"/api/v1/activities/{service.study_key_for(unit)}/complete",
        headers=headers,
        json={"answers": _answers(unit)},
    )

    profile = seeded_client.get("/api/v1/profile", headers=headers).json()
    skill = next(s for s in profile["skills"] if s["skill_key"] == unit.skill_key)
    assert skill["evidence_count"] == 1


def _user(session: Session) -> User:
    user = User(email=f"study-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Student")
    session.add(user)
    session.commit()
    return user
