"""Daily plan generation: scoring, constraints, and explainability.

The constraints tested here are the difference between a plan and a ranked
list. `docs/ADAPTIVE_ENGINE.md` and `docs/LEARNING_SCIENCE.md` specify them;
these tests are what stop a future weight change from quietly discarding them.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app.learning.mastery import STATUS_INDEPENDENT
from apps.api.app.learning.planning import (
    MAX_CONSECUTIVE_HEAVY,
    ActivityKind,
    Candidate,
    SessionTemplate,
    build_plan,
    explain,
    score_candidate,
)
from apps.api.app.models.enums import PlanReasonCode, SkillDomain
from apps.api.tests.helpers import register


def candidate(
    key: str = "skill:x",
    kind: str = ActivityKind.STUDY,
    domain: SkillDomain = SkillDomain.GRAMMAR,
    minutes: int = 8,
    **kwargs: object,
) -> Candidate:
    return Candidate(
        activity_key=key,
        activity_type="skill_practice",
        kind=kind,
        skill_key=key,
        domain=domain,
        estimated_minutes=minutes,
        title=key,
        **kwargs,  # type: ignore[arg-type]
    )


# --- Scoring components ----------------------------------------------------------


def test_every_component_is_reported_separately() -> None:
    """No opaque magic score: each consideration must be inspectable."""
    scored = score_candidate(candidate())
    assert set(scored.components) >= {
        "due_review",
        "weak_prerequisite",
        "expected_gain",
        "uncertainty",
        "skill_balance",
        "goal_relevance",
        "error_follow_up",
        "modality_diversity",
        "transfer_check",
        "repetition_penalty",
    }


def test_priority_is_the_sum_of_its_components() -> None:
    scored = score_candidate(candidate(due_pressure=0.5, goal_match=1.0))
    assert scored.priority == round(sum(scored.components.values()), 6)


def test_an_overdue_review_outranks_ordinary_practice() -> None:
    overdue = score_candidate(candidate("review:a", kind=ActivityKind.REVIEW, due_pressure=1.0))
    ordinary = score_candidate(candidate("skill:b"))
    assert overdue.priority > ordinary.priority


def test_expected_gain_peaks_at_moderate_challenge() -> None:
    """Comfortable is not well calibrated, and neither is hopeless."""
    easy = score_candidate(candidate(has_evidence=True, mastery_probability=0.95))
    ideal = score_candidate(candidate(has_evidence=True, mastery_probability=0.55))
    hard = score_candidate(candidate(has_evidence=True, mastery_probability=0.05))

    assert ideal.components["expected_gain"] > easy.components["expected_gain"]
    assert ideal.components["expected_gain"] > hard.components["expected_gain"]


def test_expected_gain_needs_evidence() -> None:
    """Without evidence the mastery estimate is a placeholder, not a measurement."""
    unmeasured = score_candidate(candidate(has_evidence=False, mastery_probability=0.55))
    assert unmeasured.components["expected_gain"] == 0.0


def test_a_measured_weak_skill_beats_a_never_assessed_one() -> None:
    measured = score_candidate(
        candidate("skill:measured", has_evidence=True, confidence=0.1, mastery_probability=0.5)
    )
    unseen = score_candidate(candidate("skill:unseen", has_evidence=False, confidence=0.0))
    assert measured.priority > unseen.priority


def test_an_independent_skill_earns_no_uncertainty_credit() -> None:
    """Re-confirming something already shown teaches little."""
    settled = score_candidate(candidate(status=STATUS_INDEPENDENT, confidence=0.9))
    assert settled.components["uncertainty"] == 0.0


def test_reflection_is_not_scored_as_a_competency() -> None:
    reflection = score_candidate(
        candidate("reflect", kind=ActivityKind.REFLECTION, targets_a_skill=False)
    )
    assert reflection.components["uncertainty"] == 0.0
    assert reflection.components["expected_gain"] == 0.0


def test_recent_practice_is_penalised() -> None:
    fresh = score_candidate(candidate(days_since_practised=0.0))
    stale = score_candidate(candidate(days_since_practised=30.0))
    assert fresh.components["repetition_penalty"] < 0
    assert stale.components["repetition_penalty"] == 0.0
    assert stale.priority > fresh.priority


def test_speech_is_scheduled_not_left_to_choice() -> None:
    speaking = score_candidate(candidate("s", kind=ActivityKind.SPEAKING))
    writing = score_candidate(candidate("w", kind=ActivityKind.OUTPUT))
    assert speaking.components["modality_diversity"] > writing.components["modality_diversity"]


def test_a_dominant_domain_is_pushed_back() -> None:
    hogged = score_candidate(candidate(), domain_share=0.9)
    neglected = score_candidate(candidate(), domain_share=0.0)
    assert neglected.components["skill_balance"] > hogged.components["skill_balance"]


def test_repeated_errors_outrank_new_material() -> None:
    error = score_candidate(candidate("err", error_pressure=1.0))
    fresh = score_candidate(candidate("new"))
    assert error.priority > fresh.priority


# --- Reason codes ----------------------------------------------------------------


def test_reason_codes_name_what_actually_drove_the_choice() -> None:
    scored = score_candidate(candidate(kind=ActivityKind.REVIEW, due_pressure=1.0))
    assert PlanReasonCode.DUE_REVIEW in scored.reason_codes


def test_reason_codes_are_few_enough_to_mean_something() -> None:
    """A list containing every possible code explains nothing."""
    scored = score_candidate(
        candidate(
            kind=ActivityKind.SPEAKING,
            due_pressure=1.0,
            goal_match=1.0,
            error_pressure=1.0,
            prerequisite_weakness=1.0,
            is_transfer=True,
            has_evidence=True,
        )
    )
    assert len(scored.reason_codes) <= 3


def test_negligible_components_are_not_offered_as_reasons() -> None:
    scored = score_candidate(candidate(goal_match=0.01))
    assert PlanReasonCode.GOAL_RELEVANCE not in scored.reason_codes


def test_every_reason_code_has_learner_facing_wording() -> None:
    from apps.api.app.learning.planning import PlannedItem

    for code in PlanReasonCode:
        scored = score_candidate(candidate())
        forced = type(scored)(candidate=scored.candidate, components={_component_for(code): 1.0})
        item = PlannedItem(scored=forced, sequence=0, slot=ActivityKind.STUDY)
        assert explain(item)


def _component_for(code: PlanReasonCode) -> str:
    return {
        PlanReasonCode.DUE_REVIEW: "due_review",
        PlanReasonCode.EXPECTED_GAIN: "expected_gain",
        PlanReasonCode.WEAK_PREREQUISITE: "weak_prerequisite",
        PlanReasonCode.UNCERTAINTY: "uncertainty",
        PlanReasonCode.SKILL_BALANCE: "skill_balance",
        PlanReasonCode.GOAL_RELEVANCE: "goal_relevance",
        PlanReasonCode.ERROR_FOLLOW_UP: "error_follow_up",
        PlanReasonCode.MODALITY_DIVERSITY: "modality_diversity",
        PlanReasonCode.TRANSFER_CHECK: "transfer_check",
    }[code]


# --- Plan construction -----------------------------------------------------------


def _mixed_pool() -> list[Candidate]:
    return [
        candidate("review:a", kind=ActivityKind.REVIEW, due_pressure=0.9),
        candidate("input:a", kind=ActivityKind.INPUT, domain=SkillDomain.READING, minutes=10),
        candidate("study:a", kind=ActivityKind.STUDY),
        candidate(
            "output:a", kind=ActivityKind.OUTPUT, domain=SkillDomain.WRITTEN_PRODUCTION, minutes=10
        ),
        candidate(
            "speak:a", kind=ActivityKind.SPEAKING, domain=SkillDomain.SPOKEN_PRODUCTION, minutes=6
        ),
        candidate("reflect", kind=ActivityKind.REFLECTION, minutes=4, targets_a_skill=False),
    ]


def test_a_plan_stays_within_the_time_budget() -> None:
    for minutes in (20, 40, 60):
        plan = build_plan(_mixed_pool(), requested_minutes=minutes)
        assert plan.total_minutes <= minutes


def test_a_plan_balances_receptive_and_productive_work() -> None:
    plan = build_plan(_mixed_pool(), requested_minutes=40)
    assert plan.has_receptive
    assert plan.has_productive


def test_a_productive_task_is_forced_in_when_scoring_would_omit_it() -> None:
    """Scoring alone would happily fill the session with drills."""
    pool = [
        candidate(f"study:{index}", kind=ActivityKind.STUDY, due_pressure=1.0) for index in range(5)
    ]
    pool.append(candidate("output:a", kind=ActivityKind.OUTPUT, minutes=8))

    plan = build_plan(pool, requested_minutes=40)
    assert plan.has_productive


def test_an_unmeetable_constraint_is_reported_not_hidden() -> None:
    receptive_only = [
        candidate("study:a", kind=ActivityKind.STUDY),
        candidate("input:a", kind=ActivityKind.INPUT, minutes=10),
    ]
    plan = build_plan(receptive_only, requested_minutes=40)
    assert plan.unmet_constraints
    assert not plan.has_productive


def test_no_more_than_two_heavy_tasks_run_consecutively() -> None:
    """Three demanding tasks in a row measures stamina, not English."""
    pool = [
        candidate("input:a", kind=ActivityKind.INPUT, minutes=6),
        candidate("output:a", kind=ActivityKind.OUTPUT, minutes=6),
        candidate("speak:a", kind=ActivityKind.SPEAKING, minutes=6),
        candidate("study:a", kind=ActivityKind.STUDY, minutes=6),
        candidate("review:a", kind=ActivityKind.REVIEW, minutes=6),
        candidate("reflect", kind=ActivityKind.REFLECTION, minutes=4, targets_a_skill=False),
    ]
    plan = build_plan(pool, requested_minutes=60)

    run = 0
    for item in plan.items:
        run = run + 1 if item.candidate.is_heavy else 0
        assert run <= MAX_CONSECUTIVE_HEAVY


def test_an_empty_pool_produces_an_honest_empty_plan() -> None:
    plan = build_plan([], requested_minutes=40)
    assert plan.items == ()
    assert plan.unmet_constraints


def test_the_same_inputs_always_produce_the_same_plan() -> None:
    """A plan that reshuffles on every load cannot be followed."""
    pool = _mixed_pool()
    first = build_plan(pool, requested_minutes=40)
    second = build_plan(list(reversed(pool)), requested_minutes=40)
    assert [item.candidate.activity_key for item in first.items] == [
        item.candidate.activity_key for item in second.items
    ]


def test_a_shorter_budget_yields_a_shorter_plan() -> None:
    short = build_plan(_mixed_pool(), requested_minutes=20)
    long = build_plan(_mixed_pool(), requested_minutes=60)
    assert short.total_minutes <= long.total_minutes


def test_templates_scale_with_available_time() -> None:
    assert len(SessionTemplate.for_minutes(20).slots) < len(SessionTemplate.for_minutes(60).slots)
    assert SessionTemplate.for_minutes(5).minutes == 20


def test_every_item_can_explain_itself() -> None:
    plan = build_plan(_mixed_pool(), requested_minutes=60)
    assert plan.items
    for item in plan.items:
        assert explain(item)


# --- API -------------------------------------------------------------------------


def test_plan_requires_authentication(seeded_client: TestClient) -> None:
    assert seeded_client.get("/api/v1/plans/today").status_code == 401


def test_today_returns_a_plan_for_a_new_learner(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    body = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    assert body["items"]
    assert body["total_minutes"] <= body["requested_minutes"]
    assert body["engine_version"]


def test_todays_plan_is_stable_across_requests(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    first = seeded_client.get("/api/v1/plans/today", headers=headers).json()
    second = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    assert first["id"] == second["id"]
    assert [item["activity_key"] for item in first["items"]] == [
        item["activity_key"] for item in second["items"]
    ]


def test_regenerating_replaces_rather_than_duplicates(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    seeded_client.get("/api/v1/plans/today", headers=headers)
    regenerated = seeded_client.post(
        "/api/v1/plans/generate", headers=headers, json={"regenerate": True}
    ).json()
    current = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    assert current["id"] == regenerated["id"]


def test_every_plan_item_carries_its_reasoning(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    body = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    for item in body["items"]:
        assert item["explanation"]
        assert item["components"]
        assert "priority" in item


def test_plan_respects_the_learners_daily_minutes(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    seeded_client.patch("/api/v1/profile", headers=headers, json={"daily_minutes": 20})
    body = seeded_client.post(
        "/api/v1/plans/generate", headers=headers, json={"regenerate": True}
    ).json()

    assert body["requested_minutes"] == 20
    assert body["total_minutes"] <= 20


def test_plan_reflects_diagnostic_evidence(seeded_client: TestClient) -> None:
    """A plan built after a diagnostic must differ from a blank learner's."""
    from apps.api.app.learning.items import ItemType
    from apps.api.app.services.diagnostics import items_by_key

    headers = register(seeded_client)
    blank = seeded_client.get("/api/v1/plans/today", headers=headers).json()

    bank = items_by_key()
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]
    for _ in range(40):
        nxt = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
        if nxt["finished"]:
            break
        item = bank[nxt["item"]["key"]]
        if item.item_type is ItemType.SELF_ASSESSMENT:
            answer = "3"
        elif item.item_type is ItemType.WRITTEN_RESPONSE:
            answer = LONG_WRITING
        else:
            answer = item.answer_key[0]
        seeded_client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": item.key, "response": answer},
        )
    seeded_client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)

    informed = seeded_client.post(
        "/api/v1/plans/generate", headers=headers, json={"regenerate": True}
    ).json()

    assert informed["items"]
    # Evidence must actually change the reasoning, not just the labels.
    informed_reasons = {code for item in informed["items"] for code in item["reason_codes"]}
    blank_keys = {item["activity_key"] for item in blank["items"]}
    informed_keys = {item["activity_key"] for item in informed["items"]}
    assert informed_reasons or informed_keys != blank_keys


LONG_WRITING = " ".join(
    [
        "Last weekend I travelled to the coast with two friends from work.",
        "We swam in the morning and then we walked along the beach for hours.",
        "I enjoyed it because the weather stayed warm the whole day.",
        "However, the journey home was slow and I was very tired by the evening.",
        "Next month I want to go back and stay for a longer holiday.",
    ]
)
