"""Spoken output tasks: the bank, opening one, and completing it.

The whole lab is shaped by one limitation, and the tests are mostly about
respecting it. What reaches the server is a transcript the browser produced.
That can evidence *that connected spoken language was produced*, and it
cannot evidence **how the learner sounded**.

Three refusals follow, and each has a test:

- No pronunciation claim. The curriculum parser refuses a task that targets a
  `pronunciation.*` skill; evidence never lands on one.
- Recognition confidence is recorded and never scored. Recognisers are worse
  on accented speech — this product's whole audience — so scoring it would be
  discrimination dressed as assessment.
- Typing is not speaking. The fallback exists for a learner with no
  microphone, and it records no speaking evidence, exactly as reading a
  listening transcript records no listening evidence.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.curriculum.speaking import parse_speaking_tasks
from apps.api.app.errors import ActivityNotFoundError
from apps.api.app.models.enums import EvidenceType
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import Attempt, EvidenceEvent
from apps.api.app.services import activities as service
from apps.api.tests.helpers import register

TASK = "speak.a2.weekend"

SPOKEN = (
    "On Saturday I went to the market with my brother and we bought some "
    "vegetables and cheese, and then we walked back along the river because "
    "the weather was very good that morning. In the evening I cooked dinner "
    "for my family and we watched an old film together at home. On Sunday I "
    "stayed in and rested, and I read a book for a few hours. I enjoyed the "
    "whole weekend a lot because I had time to see everybody properly."
)


# --- The bank --------------------------------------------------------------------


def test_the_speaking_bank_is_valid(curriculum_dir: Path) -> None:
    assert len(parse_speaking_tasks(curriculum_dir)) > 0


def test_every_task_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for task in parse_speaking_tasks(curriculum_dir, known_skill_keys=known):
        assert task.skill_key in known


def test_no_task_targets_pronunciation(curriculum_dir: Path) -> None:
    """The rule the lab rests on. A transcript cannot evidence how someone
    sounded, so no task may claim to."""
    for task in parse_speaking_tasks(curriculum_dir):
        assert not task.skill_key.startswith("pronunciation."), task.key


def test_a_pronunciation_task_is_refused(tmp_path: Path) -> None:
    """Enforced by the parser, so the rule cannot be broken by content alone."""
    content = tmp_path / "content"
    content.mkdir(parents=True)
    (content / "speaking.yml").write_text(
        "tasks:\n"
        "  - key: s1\n"
        "    level: A1\n"
        "    skill: pronunciation.core_intelligibility\n"
        "    title: T\n"
        "    format: monologue\n"
        '    prompt: "Say a few sentences about your day and what you did."\n'
        '    guidance: ["Speak clearly."]\n',
        encoding="utf-8",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_speaking_tasks(tmp_path)
    assert any("transcript cannot evidence" in error for error in exc_info.value.errors)


def test_every_task_states_preparation_time(curriculum_dir: Path) -> None:
    """Planning time changes what a speaking task measures, so it belongs in
    the content rather than in a UI decision."""
    for task in parse_speaking_tasks(curriculum_dir):
        assert task.preparation_seconds > 0, task.key


def test_required_wording_is_always_stated(curriculum_dir: Path) -> None:
    """A required word the task never says is a trap — worse here, because a
    recogniser may mishear it."""
    for task in parse_speaking_tasks(curriculum_dir):
        stated = f"{task.prompt} {' '.join(task.guidance)}".lower()
        for element in task.requirements.required_elements:
            assert element in stated, f"{task.key}: {element}"


def test_duration_rises_with_level(curriculum_dir: Path) -> None:
    tasks = parse_speaking_tasks(curriculum_dir)
    lowest = min(tasks, key=lambda task: task.cefr_level.rank)
    highest = max(tasks, key=lambda task: task.cefr_level.rank)
    assert highest.min_seconds > lowest.min_seconds


def test_speech_has_no_upper_word_bound(curriculum_dir: Path) -> None:
    """A fluent learner talking freely is the goal, not a fault."""
    for task in parse_speaking_tasks(curriculum_dir):
        assert task.requirements.max_words > 10_000


# --- Resolving -------------------------------------------------------------------


def test_a_speaking_key_resolves() -> None:
    task = service.speaking_tasks()[0]
    assert service.get_activity(service.speaking_key_for(task)) is task


def test_a_speaking_key_is_typed_as_a_speaking_task() -> None:
    task = service.speaking_tasks()[0]
    assert service.activity_type_for(service.speaking_key_for(task)) == service.SPEAKING_TYPE


def test_an_unknown_speaking_key_is_rejected() -> None:
    with pytest.raises(ActivityNotFoundError):
        service.get_activity("speak:does.not.exist")


# --- Completing ------------------------------------------------------------------


def _complete(session: Session, user_id: uuid.UUID, **kwargs: object):
    task = service.speaking_by_key()[TASK]
    defaults: dict[str, object] = {
        "transcript": SPOKEN,
        "spoken_seconds": task.min_seconds + 10,
        "recognition_confidence": 0.8,
        "typed_instead": False,
    }
    defaults.update(kwargs)
    result = service.complete_speaking(
        session,
        user_id,
        activity_key=service.speaking_key_for(task),
        **defaults,  # type: ignore[arg-type]
    )
    session.commit()
    return result


def _events(session: Session) -> list[EvidenceEvent]:
    return list(session.execute(select(EvidenceEvent)).scalars())


def test_a_full_spoken_answer_records_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id)

    assert result.evidence_recorded is True
    assert result.score == 1.0
    event = _events(db_session)[0]
    assert event.evidence_type is EvidenceType.CONTEXTUAL_PRODUCTION


def test_evidence_lands_on_a_speaking_skill_never_pronunciation(
    loaded_curriculum: Session, db_session: Session
) -> None:
    from apps.api.app.models.curriculum import SkillNode

    user = _user(db_session)
    _complete(db_session, user.id)

    event = _events(db_session)[0]
    node = db_session.get(SkillNode, event.skill_node_id)
    assert node is not None
    assert not node.key.startswith("pronunciation.")
    assert node.key == service.speaking_by_key()[TASK].skill_key


def test_a_transcript_is_weaker_evidence_than_writing(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The record is lossy: the recogniser may have misheard, dropped, or
    silently corrected what was said."""
    from apps.api.app.learning.writing import DETERMINISTIC_CONFIDENCE

    user = _user(db_session)
    _complete(db_session, user.id)

    event = _events(db_session)[0]
    assert event.confidence == service.TRANSCRIPT_CONFIDENCE
    assert event.confidence < DETERMINISTIC_CONFIDENCE


def test_the_evidence_says_pronunciation_was_not_assessed(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Stated in the record, so a future reader cannot assume otherwise."""
    user = _user(db_session)
    _complete(db_session, user.id)

    event = _events(db_session)[0]
    assert event.metadata_json["pronunciation_unassessed"] is True


def test_recognition_confidence_is_stored_but_not_scored(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The load-bearing fairness test. A recogniser is worse on accented
    speech, so the same answer must score identically however well it was
    heard."""
    user_a = _user(db_session)
    user_b = _user(db_session)

    heard_well = _complete(db_session, user_a.id, recognition_confidence=0.95)
    heard_badly = _complete(db_session, user_b.id, recognition_confidence=0.20)

    assert heard_well.score == heard_badly.score

    events = _events(db_session)
    assert {event.score for event in events} == {heard_well.score}
    assert {event.confidence for event in events} == {service.TRANSCRIPT_CONFIDENCE}
    # Recorded, so an audit can ask whether recognition quality correlated
    # with outcomes.
    stored = {event.metadata_json["recognition_confidence"] for event in events}
    assert stored == {0.95, 0.20}


def test_speaking_too_briefly_records_nothing(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Length is what makes it connected speech rather than an utterance."""
    user = _user(db_session)
    result = _complete(db_session, user.id, spoken_seconds=5)

    assert result.evidence_recorded is False
    assert _events(db_session) == []


def test_a_short_transcript_records_nothing(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id, transcript="I went out.")

    assert result.evidence_recorded is False
    assert _events(db_session) == []


# --- Typing is not speaking ------------------------------------------------------


def test_typing_records_no_speaking_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The mirror of reading a listening transcript."""
    user = _user(db_session)
    result = _complete(db_session, user.id, typed_instead=True, spoken_seconds=0)

    assert result.score == 1.0, "the answer was still good"
    assert result.evidence_recorded is False
    assert _events(db_session) == []


def test_the_typed_attempt_is_still_kept(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    _complete(db_session, user.id, typed_instead=True, spoken_seconds=0)

    attempt = db_session.execute(select(Attempt)).scalars().one()
    assert attempt.activity_type == service.SPEAKING_TYPE
    assert attempt.response["typed_instead"] is True


def test_the_learner_is_told_why_typing_did_not_count(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """And is not made to feel they cheated."""
    user = _user(db_session)
    result = _complete(db_session, user.id, typed_instead=True, spoken_seconds=0)

    assert "typed" in result.explanation.lower()
    assert "speaking" in result.explanation.lower()
    assert "%" not in result.explanation


def test_a_spoken_result_never_claims_to_judge_delivery(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id)

    assert result.provisional is True
    assert "pronunciation" in result.explanation.lower()


# --- API -------------------------------------------------------------------------


def test_opening_a_speaking_task_returns_what_the_player_needs(
    seeded_client: TestClient,
) -> None:
    headers = register(seeded_client, "speaker@example.com")
    task = service.speaking_by_key()[TASK]

    body = seeded_client.get(
        f"/api/v1/activities/{service.speaking_key_for(task)}", headers=headers
    ).json()

    assert body["activity_type"] == "speaking_task"
    assert body["prompt"]
    assert body["guidance"]
    assert body["preparation_seconds"] > 0
    assert body["min_seconds"] == task.min_seconds


def test_completing_a_spoken_task_through_the_api(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "speaker2@example.com")
    task = service.speaking_by_key()[TASK]

    body = seeded_client.post(
        f"/api/v1/activities/{service.speaking_key_for(task)}/complete",
        headers=headers,
        json={
            "text": SPOKEN,
            "spoken_seconds": task.min_seconds + 5,
            "recognition_confidence": 0.77,
            "typed_instead": False,
        },
    ).json()

    assert body["activity_type"] == "speaking_task"
    assert body["evidence_recorded"] is True
    assert body["provisional"] is True
    assert body["recognition_confidence"] == 0.77
    assert body["transcript"] == SPOKEN


def test_the_api_reports_a_typed_answer_honestly(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "speaker3@example.com")
    task = service.speaking_by_key()[TASK]

    body = seeded_client.post(
        f"/api/v1/activities/{service.speaking_key_for(task)}/complete",
        headers=headers,
        json={"text": SPOKEN, "spoken_seconds": 0, "typed_instead": True},
    ).json()

    assert body["typed_instead"] is True
    assert body["evidence_recorded"] is False


def test_speaking_no_longer_rests_on_self_report(seeded_client: TestClient) -> None:
    """The point of the whole milestone."""
    headers = register(seeded_client, "speaker4@example.com")
    task = service.speaking_by_key()[TASK]

    before = seeded_client.get("/api/v1/profile", headers=headers).json()
    before_skill = next(s for s in before["skills"] if s["skill_key"] == task.skill_key)
    assert before_skill["evidence_count"] == 0

    seeded_client.post(
        f"/api/v1/activities/{service.speaking_key_for(task)}/complete",
        headers=headers,
        json={"text": SPOKEN, "spoken_seconds": task.min_seconds + 5},
    )

    after = seeded_client.get("/api/v1/profile", headers=headers).json()
    after_skill = next(s for s in after["skills"] if s["skill_key"] == task.skill_key)
    assert after_skill["evidence_count"] == 1


def _user(session: Session) -> User:
    user = User(email=f"speak-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Speaker")
    session.add(user)
    session.commit()
    return user


# --- The bank as content ----------------------------------------------------


def test_every_level_has_more_than_one_spoken_task(curriculum_dir: Path) -> None:
    """With one task per band, a learner's second speaking session at their
    level is the same prompt again — and unlike a re-read, they will
    reproduce the answer they rehearsed last time, which measures memory of
    their own words."""
    from collections import Counter

    counts = Counter(task.cefr_level for task in parse_speaking_tasks(curriculum_dir))
    thin = [level.value for level, count in counts.items() if count < 2]
    assert not thin, f"only one spoken task at: {', '.join(sorted(thin))}"


def test_the_bank_reaches_every_level(curriculum_dir: Path) -> None:
    from apps.api.app.models.enums import CefrLevel

    levels = {task.cefr_level for task in parse_speaking_tasks(curriculum_dir)}
    assert levels == set(CefrLevel)
