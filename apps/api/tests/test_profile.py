"""Profile shape and mastery interpretation.

These tests encode the non-negotiable rules from `START_HERE_CLAUDE.md`:
no single learner-wide CEFR level, and no mastery claim without evidence.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.db.types import utcnow
from apps.api.app.learning.mastery import (
    STATUS_EMERGING,
    STATUS_INDEPENDENT,
    STATUS_SUPPORTED,
    STATUS_UNOBSERVED,
    MasteryThresholds,
    cefr_estimate_for,
    classify_status,
)
from apps.api.app.models.curriculum import SkillNode
from apps.api.app.models.enums import CefrLevel
from apps.api.app.models.learning import SkillState
from apps.api.app.services.accounts import get_user_by_email
from apps.api.tests.helpers import register

THRESHOLDS = MasteryThresholds(
    supported=0.70, independent=0.82, high_confidence=0.75, minimum_distinct_contexts=3
)


# --- Mastery classification ------------------------------------------------------


def test_no_evidence_means_unobserved() -> None:
    assert (
        classify_status(
            mastery_probability=0.9,
            confidence=0.9,
            distinct_contexts=5,
            evidence_count=0,
            thresholds=THRESHOLDS,
        )
        == STATUS_UNOBSERVED
    )


def test_high_score_in_one_context_is_not_mastery() -> None:
    """Repeated attempts on the same item cannot prove generalised mastery."""
    assert (
        classify_status(
            mastery_probability=0.95,
            confidence=0.95,
            distinct_contexts=1,
            evidence_count=12,
            thresholds=THRESHOLDS,
        )
        == STATUS_EMERGING
    )


def test_breadth_without_confidence_is_supported_not_independent() -> None:
    assert (
        classify_status(
            mastery_probability=0.9,
            confidence=0.4,
            distinct_contexts=4,
            evidence_count=6,
            thresholds=THRESHOLDS,
        )
        == STATUS_SUPPORTED
    )


def test_confident_broad_evidence_is_independent() -> None:
    assert (
        classify_status(
            mastery_probability=0.9,
            confidence=0.8,
            distinct_contexts=4,
            evidence_count=6,
            thresholds=THRESHOLDS,
        )
        == STATUS_INDEPENDENT
    )


def test_cefr_estimate_withheld_until_supported() -> None:
    assert cefr_estimate_for(STATUS_UNOBSERVED, CefrLevel.B1) is None
    assert cefr_estimate_for(STATUS_EMERGING, CefrLevel.B1) is None
    assert cefr_estimate_for(STATUS_SUPPORTED, CefrLevel.B1) is CefrLevel.B1
    assert cefr_estimate_for(STATUS_INDEPENDENT, CefrLevel.B1) is CefrLevel.B1


def test_thresholds_come_from_curriculum_metadata() -> None:
    thresholds = MasteryThresholds.from_metadata(
        {"mastery": {"supported_threshold": 0.5, "minimum_distinct_contexts": 1}}
    )
    assert thresholds.supported == 0.5
    assert thresholds.minimum_distinct_contexts == 1
    # Unspecified keys fall back to defaults rather than to zero.
    assert thresholds.independent == 0.82


def test_thresholds_ignore_malformed_metadata() -> None:
    thresholds = MasteryThresholds.from_metadata({"mastery": {"supported_threshold": "high"}})
    assert thresholds.supported == 0.70


# --- Profile endpoint ------------------------------------------------------------


def test_profile_requires_authentication(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/v1/profile").status_code == 401


def test_profile_requires_loaded_curriculum(client: TestClient) -> None:
    headers = register(client)
    response = client.get("/api/v1/profile", headers=headers)
    assert response.status_code == 503
    assert response.json()["code"] == "curriculum_not_loaded"


def test_new_learner_has_no_cefr_estimates(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    body = seeded_client.get("/api/v1/profile", headers=headers).json()

    assert body["skills"], "profile must list tracked skills"
    assert all(skill["cefr_estimate"] is None for skill in body["skills"])
    assert all(skill["status"] == "unobserved" for skill in body["skills"])
    assert all(skill["evidence_count"] == 0 for skill in body["skills"])


def test_profile_has_no_single_overall_level(seeded_client: TestClient) -> None:
    """`target_level` is a goal, not an assessment. No field asserts one current level."""
    headers = register(seeded_client)
    body = seeded_client.get("/api/v1/profile", headers=headers).json()

    assert body["target_level"] == "C2"
    assert "cefr_estimate" not in body
    assert "level" not in body
    assert len({skill["domain"] for skill in body["skills"]}) > 1


def test_profile_lists_every_domain_including_unassessed(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    body = seeded_client.get("/api/v1/profile", headers=headers).json()

    summaries = {summary["domain"]: summary for summary in body["domain_summaries"]}
    assert len(summaries) > 1
    assert all(summary["observed_skills"] == 0 for summary in summaries.values())
    assert sum(summary["tracked_skills"] for summary in summaries.values()) == len(body["skills"])


def test_profile_reflects_recorded_evidence(
    seeded_client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = register(seeded_client)

    with session_factory() as session:
        user = get_user_by_email(session, "learner@example.com")
        assert user is not None
        node = session.execute(
            select(SkillNode).where(SkillNode.key == "reading.signs_forms")
        ).scalar_one()
        session.add(
            SkillState(
                user_id=user.id,
                skill_node_id=node.id,
                mastery_probability=0.88,
                confidence=0.8,
                distinct_contexts=4,
                evidence_count=7,
                last_observed_at=utcnow(),
            )
        )
        session.commit()

    body = seeded_client.get("/api/v1/profile", headers=headers).json()
    reading = next(s for s in body["skills"] if s["skill_key"] == "reading.signs_forms")

    assert reading["status"] == "independent"
    assert reading["cefr_estimate"] == "A1"
    assert reading["evidence_count"] == 7
    assert reading["last_observed_at"] is not None

    others = [s for s in body["skills"] if s["skill_key"] != "reading.signs_forms"]
    assert all(s["cefr_estimate"] is None for s in others)


def test_patch_profile_updates_plan_inputs(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    response = seeded_client.patch(
        "/api/v1/profile",
        headers=headers,
        json={"daily_minutes": 20, "goals": {"primary": "technical meetings"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["daily_minutes"] == 20
    assert body["goals"] == {"primary": "technical meetings"}


def test_patch_profile_rejects_unknown_fields(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    response = seeded_client.patch("/api/v1/profile", headers=headers, json={"cefr_estimate": "C2"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_patch_profile_rejects_out_of_range_minutes(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    response = seeded_client.patch("/api/v1/profile", headers=headers, json={"daily_minutes": 0})
    assert response.status_code == 422


def test_learners_cannot_see_each_other(seeded_client: TestClient) -> None:
    first = register(seeded_client, "first@example.com")
    second = register(seeded_client, "second@example.com")

    first_body = seeded_client.get("/api/v1/profile", headers=first).json()
    second_body = seeded_client.get("/api/v1/profile", headers=second).json()

    assert first_body["user_id"] != second_body["user_id"]
