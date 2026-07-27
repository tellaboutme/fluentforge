"""Listening clips: the library, opening one, and completing it.

The invariant that carries this file: **understanding by ear and understanding
by eye are different claims, and the profile may only make the one it has
evidence for.** A learner who reads the transcript has done something useful
and legitimate — it is the only route available to someone who cannot use
audio — but they have not shown they can follow speech, so no listening
evidence is recorded and they are told why.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum.listening import ListeningClip, parse_listening
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.errors import ActivityNotFoundError
from apps.api.app.models.enums import EvidenceType
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import Attempt, EvidenceEvent
from apps.api.app.services import activities as service
from apps.api.tests.helpers import register

CLIP = "listen.a2.voicemail"


# --- The library -----------------------------------------------------------------


def test_the_listening_library_is_valid(curriculum_dir: Path) -> None:
    assert len(parse_listening(curriculum_dir)) > 0


def test_every_clip_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for clip in parse_listening(curriculum_dir, known_skill_keys=known):
        assert clip.skill_key in known


def test_unknown_skill_reference_is_rejected(curriculum_dir: Path) -> None:
    with pytest.raises(CurriculumError) as exc_info:
        parse_listening(curriculum_dir, known_skill_keys={"nothing.here"})
    assert any("unknown skill" in error for error in exc_info.value.errors)


def test_every_clip_targets_a_listening_skill(curriculum_dir: Path) -> None:
    """A clip filed under a reading skill would record the wrong evidence."""
    for clip in parse_listening(curriculum_dir):
        assert clip.skill_key.startswith("listening."), clip.key


def test_every_clip_asks_about_meaning_first(curriculum_dir: Path) -> None:
    for clip in parse_listening(curriculum_dir):
        assert any(question.question_type == "gist" for question in clip.questions)


def test_every_clip_sets_the_scene(curriculum_dir: Path) -> None:
    """Real listening always has context. Removing it tests something else."""
    for clip in parse_listening(curriculum_dir):
        assert len(clip.setting) > 15, clip.key


def test_every_answer_is_among_its_options(curriculum_dir: Path) -> None:
    for clip in parse_listening(curriculum_dir):
        for question in clip.questions:
            assert question.answer in question.options


def test_the_library_spans_several_levels(curriculum_dir: Path) -> None:
    levels = {clip.cefr_level for clip in parse_listening(curriculum_dir)}
    assert len(levels) >= 3


def test_speech_rate_rises_with_level(curriculum_dir: Path) -> None:
    """An A1 learner needs processing time more than authentic pace."""
    clips = parse_listening(curriculum_dir)
    lowest = min(clips, key=lambda clip: clip.cefr_level.rank)
    highest = max(clips, key=lambda clip: clip.cefr_level.rank)
    assert lowest.speech_rate < highest.speech_rate


def test_a_client_prompt_never_carries_the_answer(curriculum_dir: Path) -> None:
    for clip in parse_listening(curriculum_dir):
        for question in clip.as_prompt()["questions"]:
            assert "answer" not in question


def test_the_transcript_is_sent_on_purpose(curriculum_dir: Path) -> None:
    """It is the stimulus, not the answer key.

    The client speaks it, and a learner who cannot use audio needs it. What
    protects the measurement is honesty about having read it, not secrecy.
    """
    for clip in parse_listening(curriculum_dir):
        assert clip.as_prompt()["transcript"] == clip.transcript


def test_clips_declare_whether_they_are_synthesised(curriculum_dir: Path) -> None:
    for clip in parse_listening(curriculum_dir):
        assert clip.is_synthesised is (clip.audio is None)


# --- Resolving -------------------------------------------------------------------


def test_a_listening_key_resolves() -> None:
    clip = service.listening_clips()[0]
    assert service.get_activity(service.listening_key_for(clip)) is clip


def test_a_listening_key_is_typed_as_a_listening_task() -> None:
    clip = service.listening_clips()[0]
    assert service.activity_type_for(service.listening_key_for(clip)) == service.LISTENING_TYPE


def test_an_unknown_listening_key_is_rejected() -> None:
    with pytest.raises(ActivityNotFoundError):
        service.get_activity("listen:does.not.exist")


def test_a_reading_key_is_not_a_clip() -> None:
    with pytest.raises(ActivityNotFoundError):
        service.get_listening("read:text.a1.noticeboard")


# --- Replays ---------------------------------------------------------------------


def test_a_first_listen_is_fully_independent() -> None:
    assert service.listening_independence(1) == 1.0
    assert service.listening_independence(service.FREE_PLAYS) == 1.0


def test_many_replays_weaken_the_evidence() -> None:
    """Catching a clip in two passes is stronger evidence than needing six."""
    assert service.listening_independence(6) < service.listening_independence(3)


def test_replaying_never_reduces_the_evidence_to_nothing() -> None:
    """Replaying is normal listening behaviour, not cheating."""
    assert service.listening_independence(50) >= service.MIN_LISTENING_INDEPENDENCE


# --- Completing ------------------------------------------------------------------


def _answers(clip: ListeningClip, *, correct: bool = True) -> dict[str, str]:
    return {
        question.key: (
            question.answer
            if correct
            else next(o for o in question.options if o != question.answer)
        )
        for question in clip.questions
    }


def test_completing_a_clip_scores_it(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    result = service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip),
    )
    db_session.commit()

    assert result.score == 1.0
    assert result.correct_count == len(clip.questions)


def test_wrong_answers_score_zero(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    result = service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip, correct=False),
    )
    db_session.commit()
    assert result.score == 0.0


def test_listening_records_comprehension_against_a_listening_skill(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip),
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert event.evidence_type is EvidenceType.COMPREHENSION
    assert event.metadata_json["source"] == service.LISTENING_CONTEXT


def test_each_clip_is_its_own_context(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    for clip in service.listening_clips()[:2]:
        service.complete_listening(
            db_session,
            user.id,
            activity_key=service.listening_key_for(clip),
            answers=_answers(clip),
        )
    db_session.commit()

    contexts = {event.context_key for event in db_session.execute(select(EvidenceEvent)).scalars()}
    assert len(contexts) == 2


def test_replays_are_recorded_on_the_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    result = service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip),
        plays=5,
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert event.metadata_json["plays"] == 5
    assert event.independence == result.independence
    assert result.independence < 1.0


def test_synthesised_speech_is_recorded_as_such(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Synthetic speech under-represents connected speech. A later audit has
    to be able to tell which evidence was gathered that way."""
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip),
    )
    db_session.commit()

    event = db_session.execute(select(EvidenceEvent)).scalars().one()
    assert event.metadata_json["synthesised"] is True


# --- Reading the transcript ------------------------------------------------------


def test_reading_the_transcript_records_no_listening_evidence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The invariant this whole lab turns on."""
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    result = service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip),
        used_transcript=True,
    )
    db_session.commit()

    assert result.score == 1.0, "the answers were still right"
    assert result.evidence_recorded is False
    assert list(db_session.execute(select(EvidenceEvent)).scalars()) == []


def test_the_transcript_attempt_is_still_kept(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """It is history, and a legitimate way to work through a clip."""
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip),
        used_transcript=True,
    )
    db_session.commit()

    attempt = db_session.execute(select(Attempt)).scalars().one()
    assert attempt.activity_type == service.LISTENING_TYPE
    assert attempt.response["used_transcript"] is True
    assert attempt.scaffolding_level == 1.0


def test_the_learner_is_told_why_it_did_not_count(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """And not made to feel they cheated."""
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    result = service.complete_listening(
        db_session,
        user.id,
        activity_key=service.listening_key_for(clip),
        answers=_answers(clip),
        used_transcript=True,
    )
    db_session.commit()

    assert "reading" in result.explanation.lower()
    assert "listening" in result.explanation.lower()
    assert "%" not in result.explanation


def test_feedback_is_about_understanding_not_a_mark(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    clip = service.listening_by_key()[CLIP]

    answers = _answers(clip, correct=False)
    gist = next(q for q in clip.questions if q.question_type == "gist")
    answers[gist.key] = gist.answer

    result = service.complete_listening(
        db_session, user.id, activity_key=service.listening_key_for(clip), answers=answers
    )
    db_session.commit()

    assert "overall message" in result.explanation.lower()
    assert "%" not in result.explanation


# --- API -------------------------------------------------------------------------


def test_opening_a_clip_returns_what_the_player_needs(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "listener@example.com")
    clip = service.listening_by_key()[CLIP]

    body = seeded_client.get(
        f"/api/v1/activities/{service.listening_key_for(clip)}", headers=headers
    ).json()

    assert body["activity_type"] == "listening_task"
    assert body["setting"]
    assert body["transcript"] == clip.transcript
    assert body["speech_rate"] == clip.speech_rate
    assert body["audio"] is None
    assert len(body["questions"]) == len(clip.questions)


def test_an_open_clip_never_includes_the_answers(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "listener2@example.com")
    clip = service.listening_by_key()[CLIP]

    body = seeded_client.get(
        f"/api/v1/activities/{service.listening_key_for(clip)}", headers=headers
    ).json()

    for question in body["questions"]:
        assert "answer" not in question


def test_completing_a_clip_through_the_api(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "listener3@example.com")
    clip = service.listening_by_key()[CLIP]

    body = seeded_client.post(
        f"/api/v1/activities/{service.listening_key_for(clip)}/complete",
        headers=headers,
        json={"answers": _answers(clip), "plays": 2, "used_transcript": False},
    ).json()

    assert body["activity_type"] == "listening_task"
    assert body["score"] == 1.0
    assert body["evidence_recorded"] is True
    assert body["plays"] == 2
    assert body["independence"] == 1.0
    assert body["used_transcript"] is False


def test_the_api_reports_a_transcript_run_honestly(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "listener4@example.com")
    clip = service.listening_by_key()[CLIP]

    body = seeded_client.post(
        f"/api/v1/activities/{service.listening_key_for(clip)}/complete",
        headers=headers,
        json={"answers": _answers(clip), "plays": 0, "used_transcript": True},
    ).json()

    assert body["used_transcript"] is True
    assert body["evidence_recorded"] is False


def test_a_completed_clip_reaches_the_profile(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "listener5@example.com")
    clip = service.listening_by_key()[CLIP]

    seeded_client.post(
        f"/api/v1/activities/{service.listening_key_for(clip)}/complete",
        headers=headers,
        json={"answers": _answers(clip)},
    )

    profile = seeded_client.get("/api/v1/profile", headers=headers).json()
    skill = next(s for s in profile["skills"] if s["skill_key"] == clip.skill_key)
    assert skill["evidence_count"] == 1


def test_listening_no_longer_rests_on_self_report(seeded_client: TestClient) -> None:
    """The point of the whole slice: a listening skill can now be evidenced by
    something the learner actually did."""
    headers = register(seeded_client, "listener6@example.com")
    clip = service.listening_by_key()[CLIP]

    before = seeded_client.get("/api/v1/profile", headers=headers).json()
    before_skill = next(s for s in before["skills"] if s["skill_key"] == clip.skill_key)
    assert before_skill["evidence_count"] == 0

    seeded_client.post(
        f"/api/v1/activities/{service.listening_key_for(clip)}/complete",
        headers=headers,
        json={"answers": _answers(clip)},
    )

    after = seeded_client.get("/api/v1/profile", headers=headers).json()
    after_skill = next(s for s in after["skills"] if s["skill_key"] == clip.skill_key)
    assert after_skill["evidence_count"] == 1
    assert after_skill["mastery_probability"] > before_skill["mastery_probability"]


def _user(session: Session) -> User:
    user = User(email=f"listen-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Listener")
    session.add(user)
    session.commit()
    return user
