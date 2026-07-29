"""Disagreeing with a verdict.

`docs/PRIVACY_SAFETY.md` asks the product to permit reporting bad feedback and
nothing did. `docs/AI_TUTOR_BEHAVIOR.md` says AI judgement is an accelerator
rather than an authority -- a claim about how the product behaves, and it was
not true of anything: a learner marked wrong by a countable check that had
misread them could watch the verdict feed their profile with no way to object.

Everything here turns on one asymmetry. A report lowers the **confidence** of
the evidence an attempt produced and leaves the **score** alone. Confidence is
how sure the model is; `mastery_probability` is what it believes. Disagreeing
is a reason for the first and not the second.

That is also what makes it ungameable. Someone who disputes every low score
does not inflate their profile -- they make it say "we do not really know"
about the skills they disputed, which is both true and exactly what they
argued for.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.types import utcnow
from apps.api.app.models.curriculum import SkillNode
from apps.api.app.models.enums import EvidenceType, SessionStatus
from apps.api.app.models.learning import (
    Attempt,
    EvidenceEvent,
    FeedbackReport,
    LearningSession,
)
from apps.api.app.services import reports
from apps.api.tests.helpers import register


def _learner_with_work(
    client: TestClient, session: Session, email: str, *, with_evidence: bool = True
) -> tuple[dict[str, str], uuid.UUID, uuid.UUID]:
    """An account, one graded attempt, and the skill it evidenced."""
    headers = register(client, email)
    user_id = uuid.UUID(client.get("/api/v1/profile", headers=headers).json()["user_id"])
    node = session.execute(select(SkillNode).order_by(SkillNode.key)).scalars().first()

    learning_session = LearningSession(
        user_id=user_id, status=SessionStatus.COMPLETED, context={"kind": "writing_lab"}
    )
    session.add(learning_session)
    session.flush()

    attempt = Attempt(
        user_id=user_id,
        session_id=learning_session.id,
        activity_key="write:weekend",
        activity_type="writing_task",
        attempt_number=1,
        response={"text": "I go to the shop yesterday.", "score": 0.2},
        submitted_at=utcnow(),
        hints_used=0,
        scaffolding_level=0.0,
        evaluator_id="deterministic/0.1.0",
    )
    session.add(attempt)
    session.flush()

    if with_evidence:
        session.add(
            EvidenceEvent(
                user_id=user_id,
                skill_node_id=node.id,
                attempt_id=attempt.id,
                evidence_type=EvidenceType.CONTEXTUAL_PRODUCTION,
                score=0.2,
                confidence=0.8,
                context_key="task:weekend",
            )
        )
    session.commit()
    return headers, attempt.id, node.id


def _report(client: TestClient, headers: dict[str, str], attempt_id: uuid.UUID, **body):
    payload = {"reason": "wrong_verdict", **body}
    return client.post(f"/api/v1/attempts/{attempt_id}/report", json=payload, headers=headers)


# --- What a report changes --------------------------------------------------


def test_the_evidence_becomes_less_certain(seeded_client: TestClient, db_session: Session) -> None:
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-soften@example.com"
    )

    assert _report(seeded_client, headers, attempt_id).status_code == 201

    db_session.expire_all()
    event = (
        db_session.execute(select(EvidenceEvent).where(EvidenceEvent.attempt_id == attempt_id))
        .scalars()
        .one()
    )
    assert event.confidence == 0.8 * reports.DISPUTED_CONFIDENCE_FACTOR


def test_the_score_is_not_touched(seeded_client: TestClient, db_session: Session) -> None:
    """The load-bearing asymmetry. Disagreeing is a reason to be less sure,
    not evidence that the learner did better -- so a report can only widen
    the uncertainty and never raise the estimate."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-score@example.com"
    )

    _report(seeded_client, headers, attempt_id)

    db_session.expire_all()
    event = (
        db_session.execute(select(EvidenceEvent).where(EvidenceEvent.attempt_id == attempt_id))
        .scalars()
        .one()
    )
    assert event.score == 0.2


def test_the_original_confidence_is_kept(seeded_client: TestClient, db_session: Session) -> None:
    """So the change is auditable and reversible, and so a second pass could
    not compound it even if one somehow happened."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-audit@example.com"
    )

    _report(seeded_client, headers, attempt_id)

    db_session.expire_all()
    event = (
        db_session.execute(select(EvidenceEvent).where(EvidenceEvent.attempt_id == attempt_id))
        .scalars()
        .one()
    )
    assert event.metadata_json["disputed"] is True
    assert event.metadata_json["confidence_before_dispute"] == 0.8


def test_the_attempt_and_its_feedback_survive(
    seeded_client: TestClient, db_session: Session
) -> None:
    """A learner returning to their history must find what they were actually
    told, not a gap where a disagreement used to be."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-keeps@example.com"
    )

    _report(seeded_client, headers, attempt_id)

    feedback = seeded_client.get(f"/api/v1/attempts/{attempt_id}/feedback", headers=headers).json()
    assert feedback["response"]["text"] == "I go to the shop yesterday."
    assert feedback["response"]["score"] == 0.2


def test_the_learner_is_told_their_score_did_not_change(
    seeded_client: TestClient, db_session: Session
) -> None:
    """A report that said only "thanks" would let someone believe their score
    had been overturned, and finding out later is worse than being told now."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-notes@example.com"
    )

    body = _report(seeded_client, headers, attempt_id).json()

    assert body["notes"]
    assert any("has not changed" in note for note in body["notes"])
    assert any("cannot tell us you did better" in note for note in body["notes"])


def test_an_attempt_with_no_evidence_still_records_the_report(
    seeded_client: TestClient, db_session: Session
) -> None:
    """A reflection evidences nothing, and someone unhappy with it should
    still be able to say so."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-noevidence@example.com", with_evidence=False
    )

    body = _report(seeded_client, headers, attempt_id).json()

    assert body["evidence_softened"] == 0
    assert any("nothing to soften" in note for note in body["notes"])


# --- What it refuses --------------------------------------------------------


def test_reporting_twice_is_refused(seeded_client: TestClient, db_session: Session) -> None:
    """One complaint. Letting it repeat would turn the confidence reduction
    into a way to zero the observation out entirely."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-twice@example.com"
    )
    assert _report(seeded_client, headers, attempt_id).status_code == 201

    second = _report(seeded_client, headers, attempt_id)

    assert second.status_code == 409
    assert "already_reported" in second.text


def test_a_second_report_cannot_compound_the_softening(
    seeded_client: TestClient, db_session: Session
) -> None:
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-compound@example.com"
    )
    _report(seeded_client, headers, attempt_id)
    _report(seeded_client, headers, attempt_id)

    db_session.expire_all()
    event = (
        db_session.execute(select(EvidenceEvent).where(EvidenceEvent.attempt_id == attempt_id))
        .scalars()
        .one()
    )
    assert event.confidence == 0.8 * reports.DISPUTED_CONFIDENCE_FACTOR


def test_an_unknown_reason_is_refused(seeded_client: TestClient, db_session: Session) -> None:
    """The set is closed because free text alone cannot be counted, and a
    report nobody can count is one nobody acts on."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-reason@example.com"
    )

    response = _report(seeded_client, headers, attempt_id, reason="just because")

    assert response.status_code == 422
    assert "unknown_reason" in response.text


def test_every_reason_is_accepted(seeded_client: TestClient, db_session: Session) -> None:
    for index, reason in enumerate(reports.REASONS):
        headers, attempt_id, _ = _learner_with_work(
            seeded_client, db_session, f"report-reason-{index}@example.com"
        )
        assert _report(seeded_client, headers, attempt_id, reason=reason).status_code == 201


def test_one_learner_cannot_report_another_s_attempt(
    seeded_client: TestClient, db_session: Session
) -> None:
    _, theirs, _ = _learner_with_work(seeded_client, db_session, "report-theirs@example.com")
    mine = register(seeded_client, "report-mine@example.com")

    assert _report(seeded_client, mine, theirs).status_code == 404


def test_reporting_needs_an_account(seeded_client: TestClient) -> None:
    response = seeded_client.post(
        f"/api/v1/attempts/{uuid.uuid4()}/report", json={"reason": "wrong_verdict"}
    )

    assert response.status_code == 401


# --- The learner's own words ------------------------------------------------


def test_the_note_is_kept_verbatim(seeded_client: TestClient, db_session: Session) -> None:
    """This is the learner explaining themselves, and paraphrasing it would
    defeat the point of asking."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-note@example.com"
    )
    note = "The check counted 'used to' as a past simple error. It is not."

    _report(seeded_client, headers, attempt_id, note=note)

    db_session.expire_all()
    stored = db_session.execute(select(FeedbackReport)).scalars().one()
    assert stored.note == note


def test_an_empty_note_is_stored_as_nothing(seeded_client: TestClient, db_session: Session) -> None:
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-blank@example.com"
    )

    _report(seeded_client, headers, attempt_id, note="   ")

    db_session.expire_all()
    assert db_session.execute(select(FeedbackReport)).scalars().one().note is None


def test_the_evaluator_is_recorded_at_report_time(
    seeded_client: TestClient, db_session: Session
) -> None:
    """The evaluator can be replaced. The useful question later is which one
    produced the feedback somebody objected to, not which is running now."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-evaluator@example.com"
    )

    _report(seeded_client, headers, attempt_id)

    db_session.expire_all()
    assert (
        db_session.execute(select(FeedbackReport)).scalars().one().evaluator_id
        == "deterministic/0.1.0"
    )


def test_reports_appear_in_the_data_export(seeded_client: TestClient, db_session: Session) -> None:
    """The learner's own objections, exported for the same reason their
    writing is: they wrote them."""
    headers, attempt_id, _ = _learner_with_work(
        seeded_client, db_session, "report-export@example.com"
    )
    _report(seeded_client, headers, attempt_id, note="This was marked wrong unfairly.")

    body = seeded_client.get("/api/v1/account/export", headers=headers).json()

    assert body["feedback_reports"][0]["note"] == "This was marked wrong unfairly."
    assert body["feedback_reports"][0]["reason"] == "wrong_verdict"
