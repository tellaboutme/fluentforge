"""Diagnostic items, selection, and the end-to-end flow."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.curriculum.items import parse_item_bank
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.learning.items import (
    DiagnosticItem,
    ItemType,
    normalise,
    score_response,
)
from apps.api.app.learning.selection import (
    SelectionState,
    provisional_band,
    select_next,
)
from apps.api.app.models.enums import CefrLevel, EvidenceType
from apps.api.tests.helpers import register

#: Long enough to satisfy every writing prompt's minimum, with connectives.
LONG_ENOUGH_WRITING = " ".join(
    [
        "I live in a small city and I work in an office during the week.",
        "In the evening I usually cook something simple because I am tired.",
        "At the weekend I meet my friends, and sometimes we go to the river.",
        "However, when it rains we stay at home and watch a film together.",
        "I am learning English so that I can read and talk about my work.",
    ]
)


@pytest.fixture
def bank(curriculum_dir: Path) -> tuple[DiagnosticItem, ...]:
    return parse_item_bank(curriculum_dir)


# --- Item bank integrity ---------------------------------------------------------


def test_item_bank_is_valid(bank: tuple[DiagnosticItem, ...]) -> None:
    assert len(bank) > 0


def test_every_item_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    keys = {objective.key for objective in curriculum.objectives}
    for item in parse_item_bank(curriculum_dir, known_skill_keys=keys):
        assert item.skill_key in keys


def test_unknown_skill_reference_is_rejected(curriculum_dir: Path) -> None:
    with pytest.raises(CurriculumError) as exc_info:
        parse_item_bank(curriculum_dir, known_skill_keys={"nothing.here"})
    assert any("unknown skill" in error for error in exc_info.value.errors)


def test_multiple_choice_answers_are_among_their_options(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    for item in bank:
        if item.item_type is ItemType.MULTIPLE_CHOICE:
            assert set(item.answer_key) <= set(item.options), item.key


def test_bank_covers_a_range_of_levels(bank: tuple[DiagnosticItem, ...]) -> None:
    levels = {item.cefr_level for item in bank}
    assert {CefrLevel.A1, CefrLevel.A2, CefrLevel.B1} <= levels


def test_client_prompt_never_exposes_the_answer(bank: tuple[DiagnosticItem, ...]) -> None:
    """The single most damaging leak this endpoint could have."""
    for item in bank:
        prompt = item.as_prompt()
        assert "answer_key" not in prompt
        assert "answer" not in prompt


def test_recognition_items_produce_recognition_evidence(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    for item in bank:
        if item.item_type is ItemType.MULTIPLE_CHOICE:
            assert item.evidence_type is EvidenceType.RECOGNITION
        if item.item_type is ItemType.SELF_ASSESSMENT:
            assert item.evidence_type is EvidenceType.SELF_REPORT


# --- Scoring ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Went  ", "went"),
        ("WENT", "went"),
        ("don\u2019t", "don't"),
        ("caf\u00e9", "cafe"),
        ("more   interesting", "more interesting"),
        ("went.", "went"),
    ],
)
def test_normalisation_ignores_what_is_not_being_assessed(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def _item(**kwargs: object) -> DiagnosticItem:
    defaults = {
        "key": "t.1",
        "item_type": ItemType.GAP_FILL,
        "skill_key": "grammar.basic_clause",
        "cefr_level": CefrLevel.A1,
        "prompt": "p",
        "answer_key": ("went",),
    }
    return DiagnosticItem(**{**defaults, **kwargs})  # type: ignore[arg-type]


def test_correct_answer_scores_one() -> None:
    assert score_response(_item(), " WENT ").score == 1.0


def test_wrong_answer_scores_zero() -> None:
    result = score_response(_item(), "goed")
    assert result.score == 0.0
    assert not result.correct


def test_empty_answer_is_not_correct() -> None:
    assert score_response(_item(), "   ").correct is False


def test_any_listed_answer_is_accepted() -> None:
    item = _item(answer_key=("would learn", "'d learn"))
    assert score_response(item, "'D LEARN").correct


def test_distractor_rationale_is_returned() -> None:
    item = _item(distractor_rationale={"goed": "'go' is irregular."})
    assert "irregular" in score_response(item, "goed").explanation


def test_self_assessment_maps_a_rating_to_a_score() -> None:
    item = _item(item_type=ItemType.SELF_ASSESSMENT, answer_key=("0", "1", "2", "3", "4"))
    assert score_response(item, "4").score == 1.0
    assert score_response(item, "0").score == 0.0
    assert score_response(item, "2").score == 0.5


def test_self_assessment_tolerates_junk() -> None:
    item = _item(item_type=ItemType.SELF_ASSESSMENT, answer_key=("0", "1", "2", "3", "4"))
    assert score_response(item, "banana").score == 0.0
    assert score_response(item, "99").score == 1.0


# --- Selection -------------------------------------------------------------------


def test_selection_targets_the_ability_estimate(bank: tuple[DiagnosticItem, ...]) -> None:
    scored = [i for i in bank if i.item_type is not ItemType.SELF_ASSESSMENT]
    state = SelectionState(ability=0.55, answered_keys=frozenset())
    chosen = select_next(scored, state)
    assert chosen is not None
    closest = min(abs(item.difficulty - 0.55) for item in scored)
    assert abs(chosen.difficulty - 0.55) == pytest.approx(closest)


def test_failure_lowers_the_estimate_more_than_success_raises_it(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    item = next(i for i in bank if i.item_type is not ItemType.SELF_ASSESSMENT)
    start = SelectionState(ability=0.5)
    assert (start.ability - start.after(item, False).ability) > (
        start.after(item, True).ability - start.ability
    )


def test_self_assessment_does_not_drive_the_staircase(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    rating = next(i for i in bank if i.item_type is ItemType.SELF_ASSESSMENT)
    start = SelectionState(ability=0.4)
    assert start.after(rating, False).ability == start.ability


def test_selection_never_repeats_an_item(bank: tuple[DiagnosticItem, ...]) -> None:
    state = SelectionState()
    seen: set[str] = set()
    for _ in range(len(bank)):
        chosen = select_next(list(bank), state, max_items=len(bank))
        if chosen is None:
            break
        assert chosen.key not in seen
        seen.add(chosen.key)
        state = state.after(chosen, True)


def test_staircase_stops_after_three_consecutive_failures(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    """Further closed items would measure frustration, not ability.

    The writing task is still offered: a learner who found the questions hard
    should not be denied the chance to show what they can produce.
    """
    state = SelectionState(consecutive_failures=3, answered_keys=_self_assessment_keys(bank))
    chosen = select_next(list(bank), state)
    assert chosen is not None
    assert chosen.item_type is ItemType.WRITTEN_RESPONSE


def test_diagnostic_ends_once_the_writing_task_is_done(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    written = next(i for i in bank if i.item_type is ItemType.WRITTEN_RESPONSE)
    state = SelectionState(
        consecutive_failures=3,
        answered_keys=_self_assessment_keys(bank) | {written.key},
    )
    assert select_next(list(bank), state) is None


def _self_assessment_keys(bank: tuple[DiagnosticItem, ...]) -> frozenset[str]:
    """Self-ratings are always served first, so tests must clear them."""
    return frozenset(item.key for item in bank if item.item_type is ItemType.SELF_ASSESSMENT)


def test_writing_is_held_back_until_the_estimate_settles(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    """A writing prompt should match the learner's level, so it comes later."""
    closed = [
        item
        for item in bank
        if item.item_type not in (ItemType.SELF_ASSESSMENT, ItemType.WRITTEN_RESPONSE)
    ]
    ratings = [item.key for item in bank if item.item_type is ItemType.SELF_ASSESSMENT]

    state = SelectionState(answered_keys=frozenset(ratings))
    for _ in range(3):
        chosen = select_next(list(bank), state)
        assert chosen is not None
        assert chosen.item_type is not ItemType.WRITTEN_RESPONSE
        state = state.after(chosen, True)

    assert len(closed) > 3


def test_writing_appears_once_enough_closed_items_are_answered(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    state = SelectionState()
    types_seen: list[ItemType] = []
    for _ in range(30):
        chosen = select_next(list(bank), state)
        if chosen is None:
            break
        types_seen.append(chosen.item_type)
        state = state.after(chosen, True)

    assert ItemType.WRITTEN_RESPONSE in types_seen
    # Exactly one writing task, and never the first thing a learner sees.
    assert types_seen.count(ItemType.WRITTEN_RESPONSE) == 1
    assert types_seen[0] is not ItemType.WRITTEN_RESPONSE


def test_writing_does_not_move_the_difficulty_estimate(
    bank: tuple[DiagnosticItem, ...],
) -> None:
    written = next(i for i in bank if i.item_type is ItemType.WRITTEN_RESPONSE)
    start = SelectionState(ability=0.4)
    assert start.after(written, False).ability == start.ability


def test_diagnostic_respects_the_item_budget(bank: tuple[DiagnosticItem, ...]) -> None:
    state = SelectionState(answered_keys=frozenset({item.key for item in bank[:5]}))
    assert select_next(list(bank), state, max_items=5) is None


def test_provisional_band_picks_the_highest_passed_level() -> None:
    results = [
        (CefrLevel.A1, True),
        (CefrLevel.A1, True),
        (CefrLevel.A2, True),
        (CefrLevel.A2, True),
        (CefrLevel.B1, False),
        (CefrLevel.B1, False),
    ]
    assert provisional_band(results) is CefrLevel.A2


def test_provisional_band_needs_enough_items() -> None:
    assert provisional_band([(CefrLevel.B2, True)]) is None


def test_provisional_band_is_none_without_evidence() -> None:
    assert provisional_band([]) is None


# --- End-to-end flow -------------------------------------------------------------


def _run_diagnostic(
    client: TestClient, headers: dict[str, str], ceiling: CefrLevel = CefrLevel.A2
) -> dict[str, object]:
    """Drive a full diagnostic for a learner who passes up to `ceiling`."""
    from apps.api.app.services.diagnostics import items_by_key

    bank = items_by_key()
    session_id = client.post("/api/v1/diagnostics", headers=headers).json()["id"]

    for _ in range(60):
        nxt = client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
        if nxt["finished"]:
            break
        item = bank[nxt["item"]["key"]]
        if item.item_type is ItemType.SELF_ASSESSMENT:
            answer = "2"
        elif item.item_type is ItemType.WRITTEN_RESPONSE:
            answer = LONG_ENOUGH_WRITING
        elif item.cefr_level.rank <= ceiling.rank:
            answer = item.answer_key[0]
        else:
            answer = "deliberately wrong"
        client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": nxt["item"]["key"], "response": answer},
        )

    report = client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)
    assert report.status_code == 200, report.text
    return dict(report.json())


def test_diagnostic_requires_authentication(seeded_client: TestClient) -> None:
    assert seeded_client.post("/api/v1/diagnostics").status_code == 401


def test_diagnostic_produces_evidence_and_a_report(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    report = _run_diagnostic(seeded_client, headers)

    assert report["items_answered"] > 0
    assert report["skills_observed"] > 0
    assert report["outcomes"]
    assert report["caveats"]


def test_report_never_claims_certification(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    report = _run_diagnostic(seeded_client, headers)
    joined = " ".join(str(c) for c in report["caveats"]).lower()
    assert "not an official" in joined


def test_short_diagnostic_does_not_grant_mastery(seeded_client: TestClient) -> None:
    """A 20-item diagnostic cannot support a can-do claim."""
    headers = register(seeded_client)
    report = _run_diagnostic(seeded_client, headers)

    statuses = {outcome["status"] for outcome in report["outcomes"]}  # type: ignore[index]
    assert statuses <= {"emerging", "supported"}
    assert "independent" not in statuses


def test_profile_withholds_cefr_estimates_after_the_diagnostic(
    seeded_client: TestClient,
) -> None:
    headers = register(seeded_client)
    _run_diagnostic(seeded_client, headers)

    profile = seeded_client.get("/api/v1/profile", headers=headers).json()
    observed = [skill for skill in profile["skills"] if skill["evidence_count"] > 0]
    assert observed, "the diagnostic must leave evidence on the profile"
    assert all(skill["cefr_estimate"] is None for skill in observed)


def test_starting_band_tracks_learner_performance(seeded_client: TestClient) -> None:
    """A stronger learner must not be routed to the same content as a weaker one."""
    weak = _run_diagnostic(seeded_client, register(seeded_client, "weak@example.com"), CefrLevel.A1)
    strong = _run_diagnostic(
        seeded_client, register(seeded_client, "strong@example.com"), CefrLevel.C1
    )

    assert strong["starting_band"] is not None
    if weak["starting_band"] is not None:
        strong_rank = CefrLevel(strong["starting_band"]).rank  # type: ignore[arg-type]
        weak_rank = CefrLevel(weak["starting_band"]).rank  # type: ignore[arg-type]
        assert strong_rank > weak_rank


def test_diagnostic_can_be_resumed(seeded_client: TestClient) -> None:
    """An interrupted diagnostic continues rather than discarding evidence."""
    headers = register(seeded_client)
    first = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]

    item = seeded_client.get(f"/api/v1/diagnostics/{first}/next", headers=headers).json()
    seeded_client.post(
        f"/api/v1/diagnostics/{first}/responses",
        headers=headers,
        json={"item_key": item["item"]["key"], "response": "2"},
    )

    resumed = seeded_client.post("/api/v1/diagnostics", headers=headers).json()
    assert resumed["id"] == first
    assert resumed["answered"] == 1


def test_learners_cannot_reach_each_others_sessions(seeded_client: TestClient) -> None:
    owner = register(seeded_client, "owner@example.com")
    intruder = register(seeded_client, "intruder@example.com")

    session_id = seeded_client.post("/api/v1/diagnostics", headers=owner).json()["id"]
    response = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=intruder)

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


def test_unknown_item_is_rejected(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]

    response = seeded_client.post(
        f"/api/v1/diagnostics/{session_id}/responses",
        headers=headers,
        json={"item_key": "not.a.real.item", "response": "x"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "item_not_found"


def test_completed_diagnostic_rejects_further_responses(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]
    item = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
    seeded_client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)

    response = seeded_client.post(
        f"/api/v1/diagnostics/{session_id}/responses",
        headers=headers,
        json={"item_key": item["item"]["key"], "response": "2"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "diagnostic_complete"


def test_next_item_does_not_leak_the_answer(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]
    body = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).text

    assert "answer_key" not in body
    assert "distractor" not in body


def test_hints_are_recorded_and_weaken_evidence(seeded_client: TestClient) -> None:
    from apps.api.app.services.diagnostics import items_by_key

    headers = register(seeded_client)
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]
    bank = items_by_key()

    nxt = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
    key = nxt["item"]["key"]
    response = seeded_client.post(
        f"/api/v1/diagnostics/{session_id}/responses",
        headers=headers,
        json={"item_key": key, "response": bank[key].answer_key[0], "hints_used": 2},
    )
    assert response.status_code == 200
