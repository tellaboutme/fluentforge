"""What a learner keeps missing when they read and listen.

Before this, the error log had nothing at all to say about reading or
listening. A learner could work through a dozen texts, miss every inference
question, and open their error log to an empty list — while the information
needed to name the pattern sat unused in the stored results of every attempt.

The content already carries `gist | detail | inference` on every question, so
the feature exists in the material; it was simply never read back.

Two things these tests hold in place:

- **Once per question type, not once per question.** A text with four
  inference questions must not push that feature past the recurrence
  threshold on its own. The threshold exists so that one bad afternoon is not
  a pattern.
- **A comprehension error is answered by another text, never by a study
  unit.** There is no rule to explain about missing what a passage implies,
  and a study unit claiming to fix it would be a lie about what the practice
  does — the same distinction the error log already draws for pronunciation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.learning import taxonomy
from apps.api.app.learning.items import ItemType
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import ErrorPattern
from apps.api.app.services import activities
from apps.api.app.services.activities import QuestionResult, _log_comprehension_errors


def _learner(session: Session) -> User:
    user = User(email=f"comp-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Reader")
    session.add(user)
    session.commit()
    return user


def _result(key: str, question_type: str, *, correct: bool) -> QuestionResult:
    return QuestionResult(
        key=key, question_type=question_type, correct=correct, chosen="a", expected="b"
    )


def _patterns(session: Session, user: User) -> dict[str, ErrorPattern]:
    rows = (
        session.execute(select(ErrorPattern).where(ErrorPattern.user_id == user.id)).scalars().all()
    )
    return {pattern.taxonomy_code: pattern for pattern in rows}


# --- The features themselves ------------------------------------------------


def test_every_question_type_the_content_uses_has_a_feature() -> None:
    """A type outside the taxonomy would be logged as nothing, silently."""
    used = {
        question.question_type for text in activities.library() for question in text.questions
    } | {
        question.question_type
        for clip in activities.listening_clips()
        for question in clip.questions
    }

    assert used <= set(activities.COMPREHENSION_TYPES)
    for domain in ("reading", "listening"):
        for question_type in used:
            assert taxonomy.is_known(f"{domain}.comprehension.{question_type}")


def test_missing_a_detail_does_not_outrank_missing_the_point() -> None:
    """`typically_blocks_meaning` reads the same way in both directions:
    whether the message was lost.

    Flagging every comprehension miss as meaning-blocking would put receptive
    errors above every grammar error permanently, and the priority ordering
    would stop meaning anything.
    """
    assert taxonomy.blocks_meaning_default("reading.comprehension.gist") is True
    assert taxonomy.blocks_meaning_default("reading.comprehension.inference") is True
    assert taxonomy.blocks_meaning_default("reading.comprehension.detail") is False


# --- Logging ----------------------------------------------------------------


def test_a_missed_inference_question_is_logged(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)

    _log_comprehension_errors(
        db_session,
        user.id,
        (_result("q1", "gist", correct=True), _result("q2", "inference", correct=False)),
        domain="reading",
        source="the text 'A notice'",
    )
    db_session.commit()

    assert set(_patterns(db_session, user)) == {"reading.comprehension.inference"}


def test_four_missed_inference_questions_are_one_occurrence(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """One text is one observation. Counting each question would let a single
    difficult passage manufacture a pattern."""
    user = _learner(db_session)

    _log_comprehension_errors(
        db_session,
        user.id,
        tuple(_result(f"q{index}", "inference", correct=False) for index in range(4)),
        domain="reading",
        source="the text 'A long article'",
    )
    db_session.commit()

    assert _patterns(db_session, user)["reading.comprehension.inference"].occurrence_count == 1


def test_two_types_missed_in_one_text_are_two_patterns(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """They are different things to work on, and collapsing them would lose
    the only distinction the feature makes."""
    user = _learner(db_session)

    _log_comprehension_errors(
        db_session,
        user.id,
        (_result("q1", "detail", correct=False), _result("q2", "gist", correct=False)),
        domain="reading",
        source="the text 'A notice'",
    )
    db_session.commit()

    assert set(_patterns(db_session, user)) == {
        "reading.comprehension.detail",
        "reading.comprehension.gist",
    }


def test_listening_and_reading_never_merge(loaded_curriculum: Session, db_session: Session) -> None:
    """Missing an implication by eye and missing one by ear are different
    problems with different answers."""
    user = _learner(db_session)

    _log_comprehension_errors(
        db_session,
        user.id,
        (_result("q1", "inference", correct=False),),
        domain="reading",
        source="a text",
    )
    _log_comprehension_errors(
        db_session,
        user.id,
        (_result("q1", "inference", correct=False),),
        domain="listening",
        source="a clip",
    )
    db_session.commit()

    assert set(_patterns(db_session, user)) == {
        "reading.comprehension.inference",
        "listening.comprehension.inference",
    }


def test_a_perfect_attempt_logs_nothing(loaded_curriculum: Session, db_session: Session) -> None:
    user = _learner(db_session)

    _log_comprehension_errors(
        db_session,
        user.id,
        (_result("q1", "gist", correct=True),),
        domain="reading",
        source="a text",
    )
    db_session.commit()

    assert _patterns(db_session, user) == {}


def test_an_unknown_question_type_is_ignored_rather_than_invented(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The taxonomy is closed on purpose: a typo in curriculum source must not
    be able to create an unpractisable error category."""
    user = _learner(db_session)

    _log_comprehension_errors(
        db_session,
        user.id,
        (_result("q1", "vibes", correct=False),),
        domain="reading",
        source="a text",
    )
    db_session.commit()

    assert _patterns(db_session, user) == {}


# --- Remedies ---------------------------------------------------------------


def test_a_reading_error_opens_another_text_not_a_study_unit() -> None:
    """There is no rule to explain about missing what a passage implies. A
    study unit claiming to fix it would misdescribe what the practice does."""
    remedy = activities.remedy_for_feature("reading.comprehension.inference")

    assert remedy is not None
    assert remedy.activity_type == activities.READING_TYPE
    assert remedy.activity_key.startswith(activities.READ_PREFIX)


def test_a_listening_error_opens_a_clip() -> None:
    remedy = activities.remedy_for_feature("listening.comprehension.gist")

    assert remedy is not None
    assert remedy.activity_type == activities.LISTENING_TYPE


def test_the_remedy_actually_asks_the_kind_of_question_that_was_missed() -> None:
    """The load-bearing property. Sending a learner who misses inference to a
    text with only gist questions is a remedy in name only."""
    remedy = activities.remedy_for_feature("reading.comprehension.inference")
    assert remedy is not None

    text = activities.get_reading(remedy.activity_key)

    assert any(question.question_type == "inference" for question in text.questions)


def test_the_remedy_is_the_shortest_one_available() -> None:
    """The learner is being sent back to something they just got wrong. A
    twenty-minute C1 article is a poor place to try again."""
    remedy = activities.remedy_for_feature("reading.comprehension.detail")
    assert remedy is not None

    shortest = min(
        text.minutes
        for text in activities.library()
        if any(question.question_type == "detail" for question in text.questions)
    )
    assert remedy.minutes == shortest


def test_a_production_error_still_opens_a_study_unit() -> None:
    """The change must not have redirected the path that already worked."""
    for code in taxonomy.codes():
        if ".comprehension." in code:
            continue
        remedy = activities.remedy_for_feature(code)
        if remedy is not None:
            assert remedy.activity_type == activities.STUDY_TYPE


def test_a_legacy_code_still_has_no_remedy() -> None:
    """`item.<skill>` names a skill, not a practisable feature. Nothing could
    honestly claim to fix it."""
    assert activities.remedy_for_feature("item.grammar.past_future_basic") is None


def test_a_remedy_carries_the_skill_it_evidences() -> None:
    """The planner places the candidate against a skill node. A taxonomy code
    names a feature and is not a skill key."""
    remedy = activities.remedy_for_feature("reading.comprehension.gist")

    assert remedy is not None
    assert remedy.skill_key
    assert ".comprehension." not in remedy.skill_key


# --- The diagnostic ---------------------------------------------------------


def test_every_closed_diagnostic_item_names_a_feature_except_one() -> None:
    """A closed item that names no feature logs `item.<skill>`, which cannot
    be practised.

    The four reading items were the bulk of the gap and now name comprehension
    features. `lexis.a1.days` is left alone deliberately: knowing which day
    follows Tuesday is a specific word, not a feature, and inventing a code
    for it would put an unpractisable category into a closed taxonomy that
    exists to prevent exactly that.
    """
    from apps.api.app.services.diagnostics import item_bank

    unfeatured = {
        item.key
        for item in item_bank()
        if item.item_type is not ItemType.SELF_ASSESSMENT
        and not item.item_type.is_productive
        and not item.feature
    }

    assert unfeatured == {"lexis.a1.days"}


def test_the_reading_items_name_comprehension_features() -> None:
    from apps.api.app.services.diagnostics import item_bank

    reading = [item for item in item_bank() if item.key.startswith("reading.")]

    assert reading
    for item in reading:
        assert item.feature is not None
        assert item.feature.startswith("reading.comprehension.")
