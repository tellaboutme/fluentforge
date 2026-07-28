"""Sittings: starting one, ending one, and what the ending is allowed to say.

The two endpoints that sat in the contract from the beginning. The tests here
fall into three groups, and the middle one is the reason the slice exists:

- **Starting** is idempotent within a day and abandons what was left open on
  an earlier one. The second half fixes a real defect: sessions were opened
  implicitly, reused regardless of age, and never ended.
- **The summary reports work, not improvement.** There is no mastery delta in
  the shape, and a test asserts it stays that way.
- **Ending twice** returns the same summary, and ending an abandoned sitting
  is refused rather than quietly claiming the learner finished it.
"""

from __future__ import annotations

import uuid
from dataclasses import fields
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.models.curriculum import SkillNode
from apps.api.app.models.enums import EvidenceType, SessionStatus
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import Attempt, EvidenceEvent, LearningSession
from apps.api.app.models.planning import Plan, PlanItem
from apps.api.app.services import sessions as service
from apps.api.tests.helpers import register


def _learner(session: Session) -> User:
    user = User(email=f"sit-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Sitter")
    session.add(user)
    session.commit()
    return user


def _attempt(
    session: Session,
    user: User,
    sitting: LearningSession,
    *,
    key: str = "write:x",
    activity_type: str = "writing_task",
    response: dict | None = None,
) -> Attempt:
    attempt = Attempt(
        user_id=user.id,
        session_id=sitting.id,
        activity_key=key,
        activity_type=activity_type,
        attempt_number=1,
        response=response if response is not None else {"text": "Some writing.", "score": 0.8},
        submitted_at=utcnow(),
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id="deterministic/0.1.0",
    )
    session.add(attempt)
    session.commit()
    return attempt


def _some_skill(session: Session) -> SkillNode:
    return session.execute(select(SkillNode).order_by(SkillNode.key)).scalars().first()


def _evidence(session: Session, user: User, attempt: Attempt, node: SkillNode) -> None:
    session.add(
        EvidenceEvent(
            user_id=user.id,
            skill_node_id=node.id,
            attempt_id=attempt.id,
            evidence_type=EvidenceType.CONTEXTUAL_PRODUCTION,
            score=0.8,
        )
    )
    session.commit()


# --- Starting ---------------------------------------------------------------


def test_starting_twice_in_a_day_returns_the_same_sitting(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A reload, or a retried request, must not split the learner's work in
    half."""
    user = _learner(db_session)

    first = service.start(db_session, user.id)
    second = service.start(db_session, user.id)

    assert second.sitting.id == first.sitting.id
    assert second.resumed is True
    assert first.resumed is False


def test_yesterday_s_sitting_is_not_resumed(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Sitting down today does not continue yesterday."""
    user = _learner(db_session)
    stale = LearningSession(
        user_id=user.id,
        status=SessionStatus.IN_PROGRESS,
        context={"kind": service.SITTING_KIND},
        started_at=utcnow() - timedelta(days=1),
    )
    db_session.add(stale)
    db_session.commit()

    started = service.start(db_session, user.id)

    assert started.sitting.id != stale.id
    assert started.resumed is False


def test_sessions_left_open_on_an_earlier_day_are_abandoned(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The defect this module exists to fix.

    Activity sessions were reused regardless of age, so one opened in March
    was still collecting attempts in July and `ended_at` was null on every
    row. They become `abandoned`, not `completed`: nobody finished them.
    """
    user = _learner(db_session)
    started_at = utcnow() - timedelta(days=90)
    stale = LearningSession(
        user_id=user.id,
        status=SessionStatus.IN_PROGRESS,
        context={"kind": "writing_lab"},
        started_at=started_at,
    )
    db_session.add(stale)
    db_session.commit()

    service.start(db_session, user.id)
    db_session.refresh(stale)

    assert stale.status is SessionStatus.ABANDONED
    assert stale.ended_at == started_at


def test_another_learner_s_open_session_is_untouched(
    loaded_curriculum: Session, db_session: Session
) -> None:
    mine = _learner(db_session)
    theirs = _learner(db_session)
    stale = LearningSession(
        user_id=theirs.id,
        status=SessionStatus.IN_PROGRESS,
        context={"kind": "writing_lab"},
        started_at=utcnow() - timedelta(days=5),
    )
    db_session.add(stale)
    db_session.commit()

    service.start(db_session, mine.id)
    db_session.refresh(stale)

    assert stale.status is SessionStatus.IN_PROGRESS


def test_a_sitting_binds_to_today_s_plan_if_one_exists(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)
    plan = Plan(user_id=user.id, plan_date=utcnow().date(), requested_minutes=40)
    db_session.add(plan)
    db_session.commit()

    assert service.start(db_session, user.id).sitting.plan_id == plan.id


def test_starting_a_sitting_does_not_generate_a_plan(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Sitting down must not manufacture a plan for a day the learner never
    planned: that would put rows in `plans` describing intentions nobody
    had."""
    user = _learner(db_session)

    started = service.start(db_session, user.id)

    assert started.sitting.plan_id is None
    assert db_session.execute(select(Plan).where(Plan.user_id == user.id)).scalars().all() == []


def test_another_learner_s_plan_id_is_ignored_rather_than_rejected(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Which plans exist is not something one learner may learn about
    another, and the sitting is perfectly valid unbound."""
    mine = _learner(db_session)
    theirs = _learner(db_session)
    plan = Plan(user_id=theirs.id, plan_date=utcnow().date(), requested_minutes=40)
    db_session.add(plan)
    db_session.commit()

    assert service.start(db_session, mine.id, plan_id=plan.id).sitting.plan_id is None


# --- What the summary says --------------------------------------------------


def test_the_summary_reports_no_improvement_figure(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The load-bearing refusal.

    A sitting-level "you improved by 4%" is the most seductive number in the
    product: derived from a handful of attempts, presented as measured, and
    impossible to argue with. `docs/ADAPTIVE_ENGINE.md` forbids exactly this.
    """
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting
    attempt = _attempt(db_session, user, sitting)
    _evidence(db_session, user, attempt, _some_skill(db_session))

    summary = service.complete(db_session, user.id, sitting.id)

    names = {field.name for field in fields(summary)} | {
        field.name for field in fields(service.SkillTouched)
    }
    forbidden = {"mastery_probability", "mastery_delta", "improvement", "gain", "level_up", "xp"}
    assert names & forbidden == set()


def test_the_notes_are_never_empty(loaded_curriculum: Session, db_session: Session) -> None:
    """A good session is precisely where someone reads a verdict into the
    numbers."""
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting
    attempt = _attempt(db_session, user, sitting)
    _evidence(db_session, user, attempt, _some_skill(db_session))

    notes = service.complete(db_session, user.id, sitting.id).notes

    assert notes
    assert "not proof" in notes[0]


def test_an_empty_sitting_says_nothing_was_recorded(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """And says it is not held against them. Opening the app and closing it
    is not a failure to be logged."""
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting

    summary = service.complete(db_session, user.id, sitting.id)

    assert summary.activities == []
    assert summary.skills == []
    assert any("not held against you" in note for note in summary.notes)


def test_skills_report_total_contexts_not_the_ones_added(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The total is what the mastery model gates on. The number added in one
    sitting is not a threshold anything uses."""
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting
    attempt = _attempt(db_session, user, sitting)
    node = _some_skill(db_session)
    _evidence(db_session, user, attempt, node)

    summary = service.complete(db_session, user.id, sitting.id)

    assert [skill.key for skill in summary.skills] == [node.key]
    assert summary.skills[0].evidence_recorded == 1
    # No skill state was recomputed here, so breadth is still zero and the
    # skill must say what it still needs rather than nothing.
    assert summary.skills[0].needs is not None


def test_a_skill_with_enough_breadth_needs_nothing_said(
    loaded_curriculum: Session, db_session: Session
) -> None:
    from apps.api.app.learning.mastery import MasteryThresholds

    thresholds = MasteryThresholds.from_metadata(None)

    assert service._needs(thresholds.minimum_distinct_contexts, thresholds) is None
    assert service._needs(thresholds.minimum_distinct_contexts - 1, thresholds) is not None


def test_a_reflection_in_the_sitting_is_marked_unjudged(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """A summary that scored reflections would be judging the one activity
    deliberately left unjudged."""
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting
    _attempt(
        db_session,
        user,
        sitting,
        key="reflect:daily",
        activity_type="reflection",
        response={"note": "Slow going.", "scored": False},
    )

    summary = service.complete(db_session, user.id, sitting.id)

    assert summary.activities[0].was_judged is False
    assert summary.activities[0].score is None


def test_work_outside_the_plan_still_counts(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)
    plan = Plan(user_id=user.id, plan_date=utcnow().date(), requested_minutes=40)
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        PlanItem(
            plan_id=plan.id,
            sequence=1,
            activity_key="write:planned",
            activity_type="writing_task",
            estimated_minutes=10,
        )
    )
    db_session.commit()

    sitting = service.start(db_session, user.id).sitting
    _attempt(db_session, user, sitting, key="write:unplanned")

    summary = service.complete(db_session, user.id, sitting.id)

    assert summary.activities[0].on_plan is False
    assert summary.plan_items_done == 0
    assert summary.plan_items_total == 1
    assert any("still counts" in note for note in summary.notes)


def test_an_unfinished_plan_is_not_described_as_a_debt(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The plan is a suggestion. Carrying it over as an obligation would make
    a missed day compound."""
    user = _learner(db_session)
    plan = Plan(user_id=user.id, plan_date=utcnow().date(), requested_minutes=40)
    db_session.add(plan)
    db_session.flush()
    for index in range(3):
        db_session.add(
            PlanItem(
                plan_id=plan.id,
                sequence=index + 1,
                activity_key=f"write:{index}",
                activity_type="writing_task",
                estimated_minutes=10,
            )
        )
    db_session.commit()

    sitting = service.start(db_session, user.id).sitting
    _attempt(db_session, user, sitting, key="write:0")

    summary = service.complete(db_session, user.id, sitting.id)

    assert summary.plan_items_done == 1
    assert any("rather than carried over as a debt" in note for note in summary.notes)


def test_open_minutes_is_elapsed_time_not_time_on_task(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """Named for what it is. Someone who started a session and made lunch did
    not study for forty minutes, and this product does not measure time on
    task at all."""
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting
    sitting.started_at = utcnow() - timedelta(minutes=95)
    db_session.commit()

    summary = service.complete(db_session, user.id, sitting.id)

    assert summary.open_minutes >= 95


# --- Ending -----------------------------------------------------------------


def test_completing_sets_an_end_and_a_status(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting

    summary = service.complete(db_session, user.id, sitting.id)

    assert summary.status is SessionStatus.COMPLETED
    assert summary.ended_at is not None


def test_completing_twice_does_not_move_the_end_time(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """The write is retryable. A retry that moved the end time would rewrite
    the learner's day to match a network hiccup."""
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting

    first = service.complete(db_session, user.id, sitting.id)
    second = service.complete(db_session, user.id, sitting.id)

    assert first.ended_at == second.ended_at


def test_an_abandoned_sitting_cannot_be_completed(
    loaded_curriculum: Session, db_session: Session
) -> None:
    """It was abandoned because the learner walked away. Completing it would
    record that they finished something they did not."""
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting
    sitting.status = SessionStatus.ABANDONED
    db_session.commit()

    try:
        service.complete(db_session, user.id, sitting.id)
    except service.SessionAlreadyEndedError as error:
        assert error.status_code == 409
    else:  # pragma: no cover - the assertion above is the test
        raise AssertionError("an abandoned sitting was completed")


def test_one_learner_cannot_complete_another_s_sitting(
    loaded_curriculum: Session, db_session: Session
) -> None:
    from apps.api.app.errors import SessionNotFoundError

    mine = _learner(db_session)
    theirs = _learner(db_session)
    sitting = service.start(db_session, theirs.id).sitting

    try:
        service.complete(db_session, mine.id, sitting.id)
    except SessionNotFoundError as error:
        assert error.status_code == 404
    else:  # pragma: no cover
        raise AssertionError("one learner completed another's sitting")


def test_reading_a_summary_does_not_end_the_sitting(
    loaded_curriculum: Session, db_session: Session
) -> None:
    user = _learner(db_session)
    sitting = service.start(db_session, user.id).sitting

    summary = service.summarise(db_session, user.id, sitting)

    assert summary.status is SessionStatus.IN_PROGRESS
    assert sitting.ended_at is None


# --- Through the API --------------------------------------------------------


def test_the_endpoints_round_trip(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "sitting-api@example.com")

    started = seeded_client.post("/api/v1/sessions", json={}, headers=headers)
    assert started.status_code == 201, started.text
    assert started.json()["resumed"] is False
    session_id = started.json()["session_id"]

    again = seeded_client.post("/api/v1/sessions", json={}, headers=headers)
    assert again.json()["session_id"] == session_id
    assert again.json()["resumed"] is True

    done = seeded_client.post(f"/api/v1/sessions/{session_id}/complete", headers=headers)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "completed"
    assert body["notes"]


def test_the_endpoints_require_a_learner(seeded_client: TestClient) -> None:
    assert seeded_client.post("/api/v1/sessions", json={}).status_code == 401
    assert seeded_client.post(f"/api/v1/sessions/{uuid.uuid4()}/complete").status_code == 401


def test_completing_a_sitting_that_does_not_exist_is_a_404(seeded_client: TestClient) -> None:
    headers = register(seeded_client, "sitting-missing@example.com")

    response = seeded_client.post(f"/api/v1/sessions/{uuid.uuid4()}/complete", headers=headers)

    assert response.status_code == 404
