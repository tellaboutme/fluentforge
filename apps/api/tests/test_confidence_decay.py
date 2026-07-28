"""Confidence has to fall when nobody is looking.

`CLAUDE.md` states the invariant plainly: mastery decays in confidence when
not observed, not necessarily in underlying ability. The model implemented it
-- `confidence_for` folds a recency term in -- and then the value was written
to a row and never touched again. A state computed in March and read in July
still carried March's certainty, so the profile said "confident" about a skill
nobody had looked at for four months.

`services/evidence.py` said as much in a comment: "a scheduled refresh will
own that in Milestone 2". It never arrived, and the alternative here is
better: the correction is applied on **read**, which needs no worker, has no
window during which the answer is stale, and cannot silently stop.

What must not happen is `mastery_probability` moving. The learner has not
become worse. We have become less sure, and those are different claims that
this product keeps apart everywhere else.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.learning.evidence import DEFAULT_CONFIG, decay_since
from apps.api.app.models.curriculum import SkillNode
from apps.api.app.models.identity import LearnerProfile, User
from apps.api.app.models.learning import SkillState
from apps.api.app.services.evidence import current_confidence
from apps.api.tests.helpers import register


def _learner(session: Session) -> User:
    user = User(email=f"decay-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    user.profile = LearnerProfile(display_name="Absent")
    session.add(user)
    session.commit()
    return user


def _state(session: Session, user: User, *, stale_days: float, confidence: float) -> SkillState:
    node = session.execute(select(SkillNode).order_by(SkillNode.key)).scalars().first()
    moment = utcnow() - timedelta(days=stale_days)
    state = SkillState(
        user_id=user.id,
        skill_node_id=node.id,
        mastery_probability=0.85,
        confidence=confidence,
        distinct_contexts=4,
        evidence_count=12,
        last_observed_at=moment,
    )
    session.add(state)
    session.commit()
    # `updated_at` is set by the mixin on write, so it has to be pushed back
    # explicitly to simulate a state that has sat unrecomputed.
    state.updated_at = moment
    session.commit()
    return state


# --- The arithmetic ---------------------------------------------------------


def test_nothing_decays_at_the_moment_it_was_computed() -> None:
    now = utcnow()

    assert decay_since(0.8, now, now) == 0.8


def test_one_half_life_halves_it() -> None:
    now = utcnow()
    computed = now - timedelta(days=DEFAULT_CONFIG.confidence_halflife_days)

    assert decay_since(0.8, computed, now) == 0.4


def test_it_never_goes_negative_or_above_one() -> None:
    now = utcnow()

    assert decay_since(1.0, now - timedelta(days=3650), now) >= 0.0
    assert decay_since(1.0, now, now) <= 1.0


def test_a_clock_that_ran_backwards_does_not_raise_confidence() -> None:
    """A state written slightly in the future -- clock skew between a worker
    and a reader -- must not be reported as *more* certain than it was."""
    now = utcnow()

    assert decay_since(0.8, now + timedelta(hours=2), now) == 0.8


def test_a_state_that_was_never_written_is_left_alone() -> None:
    assert decay_since(0.8, None, utcnow()) == 0.8


def test_no_state_reads_as_no_confidence() -> None:
    assert current_confidence(None) == 0.0


# --- What it must not touch -------------------------------------------------


def test_mastery_is_not_decayed(loaded_curriculum: Session, db_session: Session) -> None:
    """The load-bearing separation. The learner has not become worse; we have
    become less sure, and the product keeps those apart everywhere else."""
    user = _learner(db_session)
    state = _state(db_session, user, stale_days=180, confidence=0.9)

    assert state.mastery_probability == 0.85
    assert current_confidence(state) < 0.9


def test_the_stored_value_is_not_rewritten(loaded_curriculum: Session, db_session: Session) -> None:
    """Read-time, not write-time. A read that wrote would make every request
    a mutation and would compound the decay each time it happened."""
    user = _learner(db_session)
    state = _state(db_session, user, stale_days=90, confidence=0.9)

    current_confidence(state)
    db_session.refresh(state)

    assert state.confidence == 0.9


# --- What a learner sees ----------------------------------------------------


def test_the_profile_reports_the_decayed_value(
    seeded_client: TestClient, db_session: Session
) -> None:
    headers = register(seeded_client, "decay-profile@example.com")
    user_id = uuid.UUID(seeded_client.get("/api/v1/profile", headers=headers).json()["user_id"])
    user = db_session.get(User, user_id)
    assert user is not None
    stale = _state(db_session, user, stale_days=120, confidence=0.9)

    body = seeded_client.get("/api/v1/profile", headers=headers).json()
    node = db_session.get(SkillNode, stale.skill_node_id)
    assert node is not None
    reported = next(skill for skill in body["skills"] if skill["skill_key"] == node.key)

    assert reported["confidence"] < 0.9
    assert reported["mastery_probability"] == 0.85


def test_a_stale_skill_loses_its_status(seeded_client: TestClient, db_session: Session) -> None:
    """`classify_status` gates `independent` on confidence, so a skill nobody
    has looked at for months stops claiming to be independent by itself. That
    is the invariant doing its job rather than a separate rule."""
    headers = register(seeded_client, "decay-status@example.com")
    user_id = uuid.UUID(seeded_client.get("/api/v1/profile", headers=headers).json()["user_id"])
    user = db_session.get(User, user_id)
    assert user is not None
    stale = _state(db_session, user, stale_days=365, confidence=0.95)

    body = seeded_client.get("/api/v1/profile", headers=headers).json()
    node = db_session.get(SkillNode, stale.skill_node_id)
    assert node is not None
    reported = next(skill for skill in body["skills"] if skill["skill_key"] == node.key)

    assert reported["status"] != "independent"


def test_a_freshly_computed_state_is_unaffected(
    seeded_client: TestClient, db_session: Session
) -> None:
    """The decay must be invisible to someone who is actually practising, or
    it would read as the product forgetting work they just did."""
    headers = register(seeded_client, "decay-fresh@example.com")
    user_id = uuid.UUID(seeded_client.get("/api/v1/profile", headers=headers).json()["user_id"])
    user = db_session.get(User, user_id)
    assert user is not None
    fresh = _state(db_session, user, stale_days=0, confidence=0.7)

    body = seeded_client.get("/api/v1/profile", headers=headers).json()
    node = db_session.get(SkillNode, fresh.skill_node_id)
    assert node is not None
    reported = next(skill for skill in body["skills"] if skill["skill_key"] == node.key)

    assert reported["confidence"] == 0.7
