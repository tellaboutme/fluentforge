"""Spaced review: scheduling, the lexical bank, and the review loop.

The invariant running through all of it: recognising a word and producing it
are different memories, scheduled separately and recorded as different evidence
types. Collapsing them would let a learner "master" vocabulary they cannot use.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum.lexis import parse_lexis
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.learning.scheduling import (
    DEFAULT_CONFIG,
    Grade,
    MemoryState,
    grade_from,
    review,
)
from apps.api.app.models.enums import EvidenceType, ReviewMode
from apps.api.app.models.learning import EvidenceEvent
from apps.api.app.models.planning import ReviewQueueItem
from apps.api.app.services import reviews as service
from apps.api.tests.helpers import register

UTC = timezone.utc
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


# --- Scheduler -------------------------------------------------------------------


def test_a_new_card_comes_back_within_a_day() -> None:
    result = review(MemoryState(), Grade.GOOD, now=NOW)
    assert 0 < result.interval_days <= 2


def test_intervals_expand_with_repeated_success() -> None:
    """The whole point of spacing: each success buys a longer gap."""
    state = MemoryState()
    intervals: list[float] = []
    for _ in range(5):
        result = review(state, Grade.GOOD, now=NOW)
        intervals.append(result.interval_days)
        state = result.state

    assert intervals == sorted(intervals)
    assert intervals[-1] > intervals[0] * 5


def test_forgetting_brings_a_card_straight_back() -> None:
    settled = MemoryState(stability=40.0, difficulty=0.3, repetitions=6)
    lapsed = review(settled, Grade.FORGOT, now=NOW)

    assert lapsed.interval_days < 2
    assert lapsed.state.lapses == settled.lapses + 1


def test_a_lapse_does_not_erase_everything() -> None:
    """Relearning is faster than learning; pretending otherwise wastes time."""
    result = review(MemoryState(stability=40.0, repetitions=6), Grade.FORGOT, now=NOW)
    assert result.state.stability >= DEFAULT_CONFIG.lapse_stability


def test_grades_produce_meaningfully_different_intervals() -> None:
    state = MemoryState(stability=10.0, difficulty=0.35, repetitions=3)
    intervals = {
        grade: review(state, grade, now=NOW).interval_days
        for grade in (Grade.FORGOT, Grade.HARD, Grade.GOOD, Grade.EASY)
    }
    assert (
        intervals[Grade.FORGOT]
        < intervals[Grade.HARD]
        < intervals[Grade.GOOD]
        < intervals[Grade.EASY]
    )


def test_difficulty_rises_on_lapses_and_falls_on_easy_recall() -> None:
    state = MemoryState(stability=5.0, difficulty=0.5, repetitions=2)
    assert review(state, Grade.FORGOT, now=NOW).state.difficulty > state.difficulty
    assert review(state, Grade.EASY, now=NOW).state.difficulty < state.difficulty


def test_difficulty_stays_within_bounds() -> None:
    for start in (0.0, 0.5, 1.0):
        state = MemoryState(stability=5.0, difficulty=start, repetitions=2)
        for grade in Grade:
            assert 0.0 <= review(state, grade, now=NOW).state.difficulty <= 1.0


def test_a_harder_card_earns_shorter_gaps() -> None:
    easy = MemoryState(stability=10.0, difficulty=0.1, repetitions=3)
    hard = MemoryState(stability=10.0, difficulty=0.9, repetitions=3)
    assert review(hard, Grade.GOOD, now=NOW).interval_days < (
        review(easy, Grade.GOOD, now=NOW).interval_days
    )


def test_production_returns_sooner_than_recognition() -> None:
    """Being able to produce a word decays faster than recognising it."""
    state = MemoryState(stability=10.0, repetitions=3)
    recognition = review(state, Grade.GOOD, mode=ReviewMode.MEANING_RECOGNITION, now=NOW)
    production = review(state, Grade.GOOD, mode=ReviewMode.CONTEXTUAL_PRODUCTION, now=NOW)
    assert production.interval_days < recognition.interval_days


def test_intervals_are_capped_so_cards_do_not_vanish() -> None:
    enormous = MemoryState(stability=100_000.0, difficulty=0.0, repetitions=50)
    assert review(enormous, Grade.EASY, now=NOW).interval_days <= (DEFAULT_CONFIG.max_interval_days)


def test_scheduling_is_deterministic() -> None:
    """A learner reporting the same thing twice must get the same schedule."""
    state = MemoryState(stability=7.0, difficulty=0.4, repetitions=2)
    assert review(state, Grade.GOOD, now=NOW) == review(state, Grade.GOOD, now=NOW)


def test_due_date_follows_the_interval() -> None:
    result = review(MemoryState(stability=10.0, repetitions=3), Grade.GOOD, now=NOW)
    assert result.due_at == NOW + timedelta(days=result.interval_days)


def test_every_result_can_explain_itself() -> None:
    for grade in Grade:
        assert review(MemoryState(stability=5.0, repetitions=2), grade, now=NOW).explanation


def test_grade_mapping_is_centralised() -> None:
    assert grade_from(correct=False) is Grade.FORGOT
    assert grade_from(correct=True, hesitated=True) is Grade.HARD
    assert grade_from(correct=True) is Grade.GOOD
    assert grade_from(correct=True, effortless=True) is Grade.EASY


# --- Lexical bank ----------------------------------------------------------------


def test_the_lexical_bank_is_valid(curriculum_dir: Path) -> None:
    entries = parse_lexis(curriculum_dir)
    assert len(entries) > 0


def test_every_entry_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for entry in parse_lexis(curriculum_dir, known_skill_keys=known):
        assert entry.skill_key in known


def test_unknown_skill_reference_is_rejected(curriculum_dir: Path) -> None:
    with pytest.raises(CurriculumError) as exc_info:
        parse_lexis(curriculum_dir, known_skill_keys={"nothing.here"})
    assert any("unknown skill" in error for error in exc_info.value.errors)


def test_the_bank_is_phrase_first(curriculum_dir: Path) -> None:
    """Collocations are where errors live, so chunks must dominate."""
    entries = parse_lexis(curriculum_dir)
    multiword = [entry for entry in entries if entry.is_multiword]
    assert len(multiword) > len(entries) / 2


def test_every_example_actually_uses_the_item(curriculum_dir: Path) -> None:
    for entry in parse_lexis(curriculum_dir):
        assert entry.lemma.split()[0].lower() in entry.example.lower()


def test_entries_declare_which_memories_to_schedule(curriculum_dir: Path) -> None:
    for entry in parse_lexis(curriculum_dir):
        assert entry.modes
        for mode in entry.modes:
            assert isinstance(mode, ReviewMode)


# --- Seeding and the queue -------------------------------------------------------


def test_seeding_creates_one_card_per_entry_per_mode(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    created = service.seed_reviews(db_session, user.id)
    db_session.commit()

    expected = sum(len(entry.modes) for entry in service.lexis())
    assert len(created) == expected


def test_seeding_is_idempotent(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()

    again = service.seed_reviews(db_session, user.id)
    db_session.commit()
    assert again == []


def test_seeding_respects_the_learners_level(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """C1 idioms would bury the cards an A1 learner can actually use."""
    user = _user(db_session)
    service.seed_reviews(db_session, user.id, up_to_level_rank=1)
    db_session.commit()

    entries = service.lexis_by_key()
    for item in db_session.execute(select(ReviewQueueItem)).scalars():
        assert entries[item.memory_object_key].cefr_level.rank <= 1


def test_recognition_and_production_are_separate_cards(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()

    modes = {
        item.review_mode
        for item in db_session.execute(
            select(ReviewQueueItem).where(ReviewQueueItem.memory_object_key == "make_a_decision")
        ).scalars()
    }
    assert ReviewMode.MEANING_RECOGNITION in modes
    assert ReviewMode.CONTEXTUAL_PRODUCTION in modes


def test_new_cards_are_due_immediately(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()
    assert service.due_count(db_session, user.id) > 0


def test_the_due_queue_is_capped(loaded_curriculum: Session, db_session: Session) -> None:
    """Showing a learner 300 overdue cards is how people quit."""
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()

    assert len(service.due_reviews(db_session, user.id, limit=5)) == 5
    assert service.due_count(db_session, user.id) > 5


def test_answering_pushes_a_card_into_the_future(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()

    card = service.due_reviews(db_session, user.id)[0]
    before = service.due_count(db_session, user.id)
    service.answer_review(db_session, user.id, card.id, grade=Grade.GOOD)
    db_session.commit()

    assert service.due_count(db_session, user.id) == before - 1


def test_answering_records_evidence_of_the_right_type(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A recognition review must never be recorded as production."""
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()

    card = next(
        item
        for item in service.due_reviews(db_session, user.id, limit=100)
        if item.review_mode is ReviewMode.MEANING_RECOGNITION
    )
    service.answer_review(db_session, user.id, card.id, grade=Grade.GOOD)
    db_session.commit()

    events = db_session.execute(select(EvidenceEvent)).scalars().all()
    assert events
    assert all(event.evidence_type is EvidenceType.RECOGNITION for event in events)


def test_a_production_review_records_production_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()

    card = next(
        item
        for item in service.due_reviews(db_session, user.id, limit=100)
        if item.review_mode is ReviewMode.CONTEXTUAL_PRODUCTION
    )
    service.answer_review(db_session, user.id, card.id, grade=Grade.GOOD)
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().first()
    assert event is not None
    assert event.evidence_type is EvidenceType.CONTEXTUAL_PRODUCTION


def test_forgetting_records_a_failure(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    service.seed_reviews(db_session, user.id)
    db_session.commit()

    card = service.due_reviews(db_session, user.id)[0]
    service.answer_review(db_session, user.id, card.id, grade=Grade.FORGOT)
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().first()
    assert event is not None
    assert event.score == 0.0


# --- API -------------------------------------------------------------------------


def test_reviews_require_authentication(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/v1/reviews/due").status_code == 401


def test_seeding_then_serving_due_cards(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    seeded = seeded_client.post("/api/v1/reviews/seed", headers=headers).json()
    assert seeded["created"] > 0

    due = seeded_client.get("/api/v1/reviews/due", headers=headers).json()
    assert due["cards"]
    assert due["due_now"] >= due["returned"]


def test_a_due_card_never_ships_its_own_answer(seeded_client: TestClient) -> None:
    """A recall card that included the answer would test nothing."""
    headers = register(seeded_client)
    seeded_client.post("/api/v1/reviews/seed", headers=headers)
    body = seeded_client.get("/api/v1/reviews/due", headers=headers).text

    assert "meaning" in body  # the field exists...
    for card in seeded_client.get("/api/v1/reviews/due", headers=headers).json()["cards"]:
        assert card["meaning"] is None  # ...but is withheld
        assert card["example"] is None


def test_answering_reveals_the_card_and_reschedules(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    seeded_client.post("/api/v1/reviews/seed", headers=headers)
    card = seeded_client.get("/api/v1/reviews/due", headers=headers).json()["cards"][0]

    answered = seeded_client.post(
        f"/api/v1/reviews/{card['id']}/answer", headers=headers, json={"grade": "good"}
    ).json()

    assert answered["meaning"]
    assert answered["interval_days"] > 0
    assert answered["explanation"]


def test_answering_an_unknown_card_is_rejected(seeded_client: TestClient) -> None:
    import uuid as uuid_module

    headers = register(seeded_client)
    response = seeded_client.post(
        f"/api/v1/reviews/{uuid_module.uuid4()}/answer",
        headers=headers,
        json={"grade": "good"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "review_not_found"


def test_learners_cannot_answer_each_others_cards(seeded_client: TestClient) -> None:
    owner = register(seeded_client, "owner@example.com")
    intruder = register(seeded_client, "intruder@example.com")

    seeded_client.post("/api/v1/reviews/seed", headers=owner)
    card = seeded_client.get("/api/v1/reviews/due", headers=owner).json()["cards"][0]

    response = seeded_client.post(
        f"/api/v1/reviews/{card['id']}/answer", headers=intruder, json={"grade": "good"}
    )
    assert response.status_code == 404


def test_the_diagnostic_seeds_a_starting_deck(seeded_client: TestClient) -> None:
    """Finishing the diagnostic should leave the learner with something to do."""
    from apps.api.app.learning.items import ItemType
    from apps.api.app.services.diagnostics import items_by_key

    headers = register(seeded_client)
    bank = items_by_key()
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]

    for _ in range(40):
        nxt = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
        if nxt["finished"]:
            break
        item = bank[nxt["item"]["key"]]
        answer = (
            "3"
            if item.item_type is ItemType.SELF_ASSESSMENT
            else LONG_WRITING
            if item.item_type is ItemType.WRITTEN_RESPONSE
            else item.answer_key[0]
        )
        seeded_client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": item.key, "response": answer},
        )
    seeded_client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)

    due = seeded_client.get("/api/v1/reviews/due", headers=headers).json()
    assert due["due_now"] > 0


def test_reviews_reach_the_daily_plan(seeded_client: TestClient) -> None:
    """The plan's strongest priority component finally has real data."""
    headers = register(seeded_client)
    seeded_client.post("/api/v1/reviews/seed", headers=headers)

    plan = seeded_client.post(
        "/api/v1/plans/generate", headers=headers, json={"regenerate": True}
    ).json()

    kinds = {item["kind"] for item in plan["items"]}
    assert "review" in kinds
    review_item = next(item for item in plan["items"] if item["kind"] == "review")
    assert "DUE_REVIEW" in review_item["reason_codes"]


# --- Helpers ---------------------------------------------------------------------


def _user(session: Session):  # type: ignore[no-untyped-def]
    from apps.api.app.models.identity import LearnerProfile, User

    user = User(email="reviewer@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Reviewer")
    session.add(user)
    session.commit()
    return user


LONG_WRITING = " ".join(
    [
        "Last weekend I travelled to the coast with two friends from work.",
        "We swam in the morning and then we walked along the beach for hours.",
        "I enjoyed it because the weather stayed warm the whole day.",
        "However, the journey home was slow and I was very tired by the evening.",
    ]
)
