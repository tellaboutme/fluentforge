"""Recurring errors, and their route into scheduled practice.

An error log that only accumulates is a list of grievances. The behaviour under
test is the loop: an error recurs, becomes a review card, is practised, and
stops being scheduled once the learner stops making it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.enums import ErrorStatus, MemoryObjectType, ReviewMode
from apps.api.app.models.learning import ErrorPattern
from apps.api.app.models.planning import ReviewQueueItem
from apps.api.app.services import errors_log as service
from apps.api.tests.helpers import register


def _user(session: Session):  # type: ignore[no-untyped-def]
    from apps.api.app.models.identity import LearnerProfile, User

    user = User(email="erring@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Learner")
    session.add(user)
    session.commit()
    return user


# --- Logging ---------------------------------------------------------------------


def test_the_same_mistake_becomes_one_pattern(db_session: Session) -> None:
    """Ten occurrences is one pattern with a count, not ten rows."""
    user = _user(db_session)
    for _ in range(3):
        service.record_error(
            db_session,
            user.id,
            taxonomy_code="grammar.article_omission",
            description="Missing article before a singular noun",
        )
    db_session.commit()

    patterns = db_session.execute(select(ErrorPattern)).scalars().all()
    assert len(patterns) == 1
    assert patterns[0].occurrence_count == 3


def test_examples_are_kept_but_bounded(db_session: Session) -> None:
    user = _user(db_session)
    for index in range(8):
        service.record_error(
            db_session,
            user.id,
            taxonomy_code="grammar.article_omission",
            description="Missing article",
            example=f"example {index}",
        )
    db_session.commit()

    pattern = db_session.execute(select(ErrorPattern)).scalar_one()
    assert 0 < len(pattern.examples) <= 5


def test_a_meaning_blocking_flag_is_never_lost(db_session: Session) -> None:
    """A pattern that sometimes destroys the message is a blocking pattern."""
    user = _user(db_session)
    service.record_error(
        db_session,
        user.id,
        taxonomy_code="grammar.negation",
        description="Negation reversed",
        blocks_meaning=True,
    )
    service.record_error(
        db_session,
        user.id,
        taxonomy_code="grammar.negation",
        description="Negation reversed",
        blocks_meaning=False,
    )
    db_session.commit()

    assert db_session.execute(select(ErrorPattern)).scalar_one().blocks_meaning


# --- Priority --------------------------------------------------------------------


def test_meaning_blocking_errors_outrank_merely_repeated_ones(db_session: Session) -> None:
    user = _user(db_session)
    blocking = service.record_error(
        db_session,
        user.id,
        taxonomy_code="a",
        description="a",
        blocks_meaning=True,
    )
    for _ in range(3):
        repeated = service.record_error(db_session, user.id, taxonomy_code="b", description="b")
    db_session.commit()

    assert blocking.current_priority > repeated.current_priority


def test_repetition_saturates(db_session: Session) -> None:
    """The tenth occurrence is not five times the fifth."""
    user = _user(db_session)
    for _ in range(20):
        pattern = service.record_error(db_session, user.id, taxonomy_code="c", description="c")
    db_session.commit()
    assert pattern.current_priority <= 1.0


def test_priority_stays_within_bounds(db_session: Session) -> None:
    user = _user(db_session)
    for _ in range(30):
        pattern = service.record_error(
            db_session,
            user.id,
            taxonomy_code="d",
            description="d",
            blocks_meaning=True,
        )
    db_session.commit()
    assert 0.0 <= pattern.current_priority <= 1.0


# --- Becoming review cards -------------------------------------------------------


def test_a_one_off_slip_is_not_scheduled(db_session: Session) -> None:
    """Scheduling practice for a single slip wastes the learner's time."""
    user = _user(db_session)
    service.record_error(db_session, user.id, taxonomy_code="e", description="e")
    created = service.sync_error_cards(db_session, user.id)
    db_session.commit()

    assert created == []


def test_a_recurring_error_earns_a_card(db_session: Session) -> None:
    user = _user(db_session)
    for _ in range(service.RECURRENCE_THRESHOLD):
        service.record_error(db_session, user.id, taxonomy_code="f", description="f")
    created = service.sync_error_cards(db_session, user.id)
    db_session.commit()

    assert len(created) == 1
    assert created[0].memory_object_type is MemoryObjectType.ERROR_PATTERN


def test_a_meaning_blocking_error_is_scheduled_immediately(db_session: Session) -> None:
    user = _user(db_session)
    service.record_error(
        db_session, user.id, taxonomy_code="g", description="g", blocks_meaning=True
    )
    created = service.sync_error_cards(db_session, user.id)
    db_session.commit()

    assert len(created) == 1


def test_error_cards_ask_for_production(db_session: Session) -> None:
    """An error is fixed when the learner produces the right form, not spots it."""
    user = _user(db_session)
    for _ in range(3):
        service.record_error(db_session, user.id, taxonomy_code="h", description="h")
    created = service.sync_error_cards(db_session, user.id)
    db_session.commit()

    assert created[0].review_mode is ReviewMode.CONTEXTUAL_PRODUCTION


def test_syncing_is_idempotent(db_session: Session) -> None:
    user = _user(db_session)
    for _ in range(3):
        service.record_error(db_session, user.id, taxonomy_code="i", description="i")
    service.sync_error_cards(db_session, user.id)
    db_session.commit()

    assert service.sync_error_cards(db_session, user.id) == []


def test_resolving_stops_the_scheduling(db_session: Session) -> None:
    """Progress is fewer repeated errors, so resolution must actually stop it."""
    user = _user(db_session)
    for _ in range(3):
        service.record_error(db_session, user.id, taxonomy_code="j", description="j")
    service.sync_error_cards(db_session, user.id)
    db_session.commit()

    service.mark_resolved(db_session, user.id, "j")
    db_session.commit()

    remaining = (
        db_session.execute(
            select(ReviewQueueItem).where(
                ReviewQueueItem.memory_object_type == MemoryObjectType.ERROR_PATTERN
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


def test_a_resolved_pattern_is_kept_as_a_result(db_session: Session) -> None:
    user = _user(db_session)
    for _ in range(3):
        service.record_error(db_session, user.id, taxonomy_code="k", description="k")
    service.mark_resolved(db_session, user.id, "k")
    db_session.commit()

    pattern = db_session.execute(select(ErrorPattern)).scalar_one()
    assert pattern.status is ErrorStatus.RESOLVED
    assert pattern.occurrence_count == 3


def test_a_resolved_error_is_never_rescheduled(db_session: Session) -> None:
    user = _user(db_session)
    for _ in range(3):
        service.record_error(db_session, user.id, taxonomy_code="l", description="l")
    service.mark_resolved(db_session, user.id, "l")
    db_session.commit()

    assert service.sync_error_cards(db_session, user.id) == []


def test_active_errors_are_ranked(db_session: Session) -> None:
    user = _user(db_session)
    service.record_error(
        db_session, user.id, taxonomy_code="high", description="h", blocks_meaning=True
    )
    service.record_error(db_session, user.id, taxonomy_code="low", description="l")
    db_session.commit()

    ranked = service.active_errors(db_session, user.id)
    assert ranked[0].taxonomy_code == "high"


# --- End to end ------------------------------------------------------------------


def test_diagnostic_mistakes_become_errors(seeded_client: TestClient) -> None:
    """A wrong answer is a data point about what went wrong, not a lost point."""
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
        answer = "3" if item.item_type is ItemType.SELF_ASSESSMENT else "deliberately wrong"
        seeded_client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": item.key, "response": answer},
        )

    plan = seeded_client.post(
        "/api/v1/plans/generate", headers=headers, json={"regenerate": True}
    ).json()

    # The errors should now be visible to the planner as follow-up work.
    assert plan["items"]


def test_error_cards_appear_in_the_review_queue(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    seeded_client.post("/api/v1/reviews/seed", headers=headers)

    due = seeded_client.get("/api/v1/reviews/due", headers=headers).json()
    assert due["cards"]
