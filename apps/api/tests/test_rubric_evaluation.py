"""The rubric evaluator, wired into the writing path.

Until now the provider contract existed, was validated, and was tested — and
nothing ever called it. Writing feedback was therefore permanently provisional
whatever a deployment configured. This is the wiring, and the invariants it
has to hold are all about *not overclaiming*:

- A rubric judgement **adds** evidence; it never replaces the deterministic
  event. The two say different things.
- Both share one context key. One piece of writing judged twice is one
  context, not two.
- An abstention, a low-confidence result, or a provider that throws all leave
  the learner with exactly the feedback they would have had anyway.
- Evaluator confidence is capped before it reaches the mastery model.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.learning.writing import DETERMINISTIC_CONFIDENCE
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import EvidenceEvent
from apps.api.app.providers import (
    MIN_USABLE_CONFIDENCE,
    RubricDimension,
    WritingEvaluation,
    WritingEvaluationRequest,
)
from apps.api.app.services import activities as service

TASK = "write.a2.late_email"

GOOD_EMAIL = (
    "Hi Sam, I am very sorry but I will be late tomorrow morning. My train "
    "was cancelled because of a signal fault, so I have to wait for the next "
    "one. I think I will arrive at about ten o'clock. Please start the "
    "meeting without me and begin with the budget, and I will join you as "
    "soon as I get there. Sorry again for the trouble."
)


class FakeEvaluator:
    """A stand-in provider. Records what it was asked, returns what it is told."""

    name = "fake"

    def __init__(self, evaluation: WritingEvaluation | None = None, *, raises: bool = False):
        self.evaluation = evaluation
        self.raises = raises
        self.requests: list[WritingEvaluationRequest] = []

    def evaluate(self, request: WritingEvaluationRequest) -> WritingEvaluation | None:
        self.requests.append(request)
        if self.raises:
            raise RuntimeError("provider exploded")
        return self.evaluation


def _evaluation(confidence: float = 0.8, score: float = 0.7) -> WritingEvaluation:
    return WritingEvaluation(
        dimensions=[
            RubricDimension(
                name="accuracy",
                score=score,
                confidence=confidence,
                evidence=["My train was cancelled"],
            ),
            RubricDimension(
                name="range",
                score=score,
                confidence=confidence,
                evidence=["so I have to wait"],
            ),
        ],
        confidence=confidence,
        provider="fake",
        model="fake-1",
        prompt_version="writing/0.1.0",
    )


def _complete(session: Session, user_id: uuid.UUID, evaluator: object, text: str = GOOD_EMAIL):
    task = service.tasks_by_key()[TASK]
    result = service.complete_writing(
        session,
        user_id,
        activity_key=service.writing_key_for(task),
        text=text,
        evaluator=evaluator,  # type: ignore[arg-type]
    )
    session.commit()
    return result


def _events(session: Session) -> list[EvidenceEvent]:
    return list(session.execute(select(EvidenceEvent)).scalars())


# --- With no evaluator -----------------------------------------------------------


def test_the_default_provider_leaves_writing_provisional(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The shipped default abstains, and the product still works."""
    user = _user(db_session)
    result = _complete(db_session, user.id, service.get_writing_evaluator())

    assert result.judged is False
    assert result.provisional is True
    assert len(_events(db_session)) == 1


# --- With a usable judgement -----------------------------------------------------


def test_a_usable_judgement_adds_a_second_evidence_event(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Adds, never replaces: the two events make different claims."""
    user = _user(db_session)
    _complete(db_session, user.id, FakeEvaluator(_evaluation()))

    events = _events(db_session)
    assert len(events) == 2

    confidences = sorted(event.confidence for event in events)
    assert confidences[0] == DETERMINISTIC_CONFIDENCE
    assert confidences[1] > DETERMINISTIC_CONFIDENCE


def test_both_events_share_one_context(loaded_curriculum: Session, db_session: Session) -> None:
    """One piece of writing judged twice is one context.

    Counting it as two would let a single submission satisfy the mastery
    model's breadth requirement on its own.
    """
    user = _user(db_session)
    _complete(db_session, user.id, FakeEvaluator(_evaluation()))

    assert len({event.context_key for event in _events(db_session)}) == 1


def test_the_rubric_event_is_marked_and_attributed(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    _complete(db_session, user.id, FakeEvaluator(_evaluation()))

    rubric = next(e for e in _events(db_session) if e.metadata_json.get("rubric"))
    assert rubric.metadata_json["provider"] == "fake"
    assert rubric.metadata_json["prompt_version"] == "writing/0.1.0"
    assert "accuracy" in rubric.metadata_json["dimensions"]


def test_a_judged_response_is_no_longer_provisional(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id, FakeEvaluator(_evaluation()))

    assert result.judged is True
    assert result.provisional is False
    assert "accuracy" in result.explanation.lower()


def test_evaluator_confidence_is_capped(loaded_curriculum: Session, db_session: Session) -> None:
    """A model claiming near-certainty has not earned the trust of a closed
    item scored against a known answer."""
    user = _user(db_session)
    _complete(db_session, user.id, FakeEvaluator(_evaluation(confidence=0.99)))

    rubric = next(e for e in _events(db_session) if e.metadata_json.get("rubric"))
    assert rubric.confidence == service.MAX_RUBRIC_CONFIDENCE
    assert rubric.confidence < 0.99


def test_the_evaluator_is_given_the_task_and_the_level(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A rubric applied without knowing the target level is not a rubric."""
    user = _user(db_session)
    evaluator = FakeEvaluator(_evaluation())
    _complete(db_session, user.id, evaluator)

    request = evaluator.requests[0]
    assert request.response_text == GOOD_EMAIL
    assert request.target_level == "A2"
    assert request.skill_key == "writing.linked_messages"
    assert len(request.task_prompt) > 0


# --- Refusals --------------------------------------------------------------------


def test_an_abstention_changes_nothing(loaded_curriculum: Session, db_session: Session) -> None:
    user = _user(db_session)
    result = _complete(db_session, user.id, FakeEvaluator(None))

    assert result.provisional is True
    assert len(_events(db_session)) == 1


def test_a_low_confidence_judgement_is_refused(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Below the bar it produces no evidence, however plausible it looks."""
    user = _user(db_session)
    weak = _evaluation(confidence=MIN_USABLE_CONFIDENCE - 0.2)
    result = _complete(db_session, user.id, FakeEvaluator(weak))

    assert result.judged is False
    assert result.provisional is True
    assert len(_events(db_session)) == 1


def test_an_evaluation_with_no_dimensions_is_an_abstention(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _user(db_session)
    empty = WritingEvaluation(confidence=0.9, abstain_reason="off-topic", provider="fake")
    result = _complete(db_session, user.id, FakeEvaluator(empty))

    assert result.judged is False
    assert len(_events(db_session)) == 1


def test_a_provider_that_throws_cannot_lose_the_submission(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A learner's writing must survive somebody else's exception."""
    user = _user(db_session)
    result = _complete(db_session, user.id, FakeEvaluator(raises=True))

    assert result.score == 1.0, "the deterministic checks still ran"
    assert result.provisional is True
    assert len(_events(db_session)) == 1


def test_a_response_too_short_is_never_sent_to_an_evaluator(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """No point spending a model call on three words, and no point judging
    what is already known to be insufficient."""
    user = _user(db_session)
    evaluator = FakeEvaluator(_evaluation())
    result = _complete(db_session, user.id, evaluator, text="Sorry, train broke.")

    assert evaluator.requests == []
    assert result.evidence_recorded is False
    assert _events(db_session) == []


# --- API -------------------------------------------------------------------------


def test_the_api_reports_an_unjudged_response_as_provisional(seeded_client) -> None:
    from apps.api.tests.helpers import register

    headers = register(seeded_client, "rubric1@example.com")
    task = service.tasks_by_key()[TASK]

    body = seeded_client.post(
        f"/api/v1/activities/{service.writing_key_for(task)}/complete",
        headers=headers,
        json={"text": GOOD_EMAIL},
    ).json()

    # The shipped default abstains, so this is the state a real deployment
    # sees until an evaluator is configured.
    assert body["provisional"] is True
    assert body["rubric"] == []
    assert body["priority_feedback"] == []
    assert body["evaluated_by"] is None


def _user(session: Session) -> User:
    user = User(email=f"rubric-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Writer")
    session.add(user)
    session.commit()
    return user


@pytest.fixture(autouse=True)
def _reset_provider_cache():
    """`get_writing_evaluator` is cached; keep tests order-independent."""
    from apps.api.app import providers

    providers.get_writing_evaluator.cache_clear()
    yield
    providers.get_writing_evaluator.cache_clear()
