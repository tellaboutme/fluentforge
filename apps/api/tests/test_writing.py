"""Written production: deterministic analysis, scoring, and evidence.

The invariant under test throughout: deterministic checks confirm that the
learner *produced* language, and must never be mistaken for a judgement that
they produced it *well*.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.learning.items import ItemType, score_response
from apps.api.app.learning.writing import (
    DETERMINISTIC_CONFIDENCE,
    WritingRequirements,
    analyse,
    count_sentences,
    find_connectives,
)
from apps.api.app.models.enums import EvidenceType
from apps.api.app.providers import (
    DisabledWritingEvaluator,
    ProviderNotAvailableError,
    WritingEvaluation,
    WritingEvaluationRequest,
    get_writing_evaluator,
)
from apps.api.app.providers.base import MIN_USABLE_CONFIDENCE, RubricDimension
from apps.api.app.services.diagnostics import items_by_key
from apps.api.app.settings import settings
from apps.api.tests.helpers import register

GOOD_A2 = (
    "Last weekend I went to the mountains with my brother. We walked for three "
    "hours and then we cooked our dinner outside on a small fire. I enjoyed it "
    "a lot because the weather was perfect and very warm. On Sunday I stayed "
    "at home and rested."
)

REQUIREMENTS = WritingRequirements(
    min_words=40,
    max_words=160,
    min_sentences=3,
    min_connectives=2,
    required_elements=("because",),
)


# --- Counting --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("One sentence.", 1),
        ("One. Two. Three.", 3),
        ("No final stop", 1),
        ("Really?! Yes!", 2),
    ],
)
def test_sentence_counting(text: str, expected: int) -> None:
    assert count_sentences(text) == expected


def test_connectives_are_found_as_whole_words() -> None:
    assert "and" in find_connectives("bread and butter")
    # "band" contains "and" but is not a connective.
    assert "and" not in find_connectives("the band played")


def test_connective_detection_ignores_case_and_curly_apostrophes() -> None:
    assert "because" in find_connectives("BECAUSE it rained")


@pytest.mark.parametrize(
    "text",
    [
        "However, the journey was slow.",
        "It rained; however the trip was good.",
        "We left early. However the train was late.",
        "(However) it worked out.",
    ],
)
def test_connectives_are_found_next_to_punctuation(text: str) -> None:
    """Regression: 'However,' failed to match, under-counting real linking."""
    assert "however" in find_connectives(text)


def test_connective_at_the_very_start_or_end_is_found() -> None:
    assert "because" in find_connectives("because")
    assert "so" in find_connectives("I was tired so")


# --- Analysis --------------------------------------------------------------------


def test_a_good_response_meets_every_check() -> None:
    analysis = analyse(GOOD_A2, REQUIREMENTS)
    assert analysis.score == 1.0
    assert analysis.met_minimum
    assert not analysis.missing_elements


def test_scoring_is_graded_not_all_or_nothing() -> None:
    """Missing one requirement is partial evidence, not zero."""
    without_because = GOOD_A2.replace("because", "and")
    analysis = analyse(without_because, REQUIREMENTS)
    assert 0.0 < analysis.score < 1.0
    assert analysis.missing_elements == ("because",)


def test_empty_response_fails_everything_without_raising() -> None:
    analysis = analyse("", REQUIREMENTS)
    assert analysis.score == 0.0
    assert not analysis.met_minimum
    assert analysis.word_count == 0


def test_too_short_is_not_evidence() -> None:
    assert not analyse("I went to the park.", REQUIREMENTS).met_minimum


def test_over_length_is_flagged_but_still_counted_as_writing() -> None:
    analysis = analyse("word " * 500, WritingRequirements(min_words=10, max_words=50))
    assert not analysis.met_minimum
    assert analysis.word_count > 50


def test_analysis_never_raises_on_hostile_input() -> None:
    for text in ("", "   ", "!!!", "\n\n\n", "😀😀", "<script>alert(1)</script>"):
        analyse(text, REQUIREMENTS)


def test_lexical_variety_is_bounded() -> None:
    assert analyse("the the the the", REQUIREMENTS).lexical_variety == pytest.approx(0.25)
    assert analyse("", REQUIREMENTS).lexical_variety == 0.0


# --- Scoring a written item ------------------------------------------------------


def _writing_item(key: str = "writing.a2.last_weekend"):  # type: ignore[no-untyped-def]
    return items_by_key()[key]


def test_written_items_produce_production_evidence() -> None:
    item = _writing_item()
    assert item.item_type is ItemType.WRITTEN_RESPONSE
    assert item.evidence_type is EvidenceType.CONTEXTUAL_PRODUCTION


def test_written_scoring_is_marked_provisional() -> None:
    """Deterministic checks cannot judge accuracy, and must say so."""
    scored = score_response(_writing_item(), GOOD_A2)
    assert scored.provisional is True
    assert scored.evaluator_confidence == DETERMINISTIC_CONFIDENCE
    assert scored.evaluator_confidence < 1.0


def test_written_scoring_reports_each_check() -> None:
    scored = score_response(_writing_item(), GOOD_A2)
    codes = {code for code, _, _ in scored.checks}
    assert {"length", "sentences", "connectives", "content"} <= codes
    assert all(passed for _, passed, _ in scored.checks)


def test_written_feedback_disclaims_grammar_judgement() -> None:
    scored = score_response(_writing_item(), GOOD_A2)
    assert "grammar" in scored.explanation.lower()


def test_written_items_never_expose_an_answer_key() -> None:
    item = _writing_item()
    assert item.answer_key == ()
    assert "answer_key" not in item.as_prompt()


def test_written_prompt_states_its_length_requirement() -> None:
    """A learner must not fail a length check they were never told about."""
    prompt = _writing_item().as_prompt()
    assert prompt["min_words"] and prompt["max_words"]


def test_closed_items_stay_fully_confident_and_final() -> None:
    scored = score_response(items_by_key()["grammar.a1.be_present"], "is")
    assert scored.provisional is False
    assert scored.evaluator_confidence == 1.0
    assert scored.checks == ()


# --- Provider abstraction --------------------------------------------------------


def test_default_provider_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned rather than ambient: this asserts what the product ships with,
    not what the developer's `.env` currently says. Reading the environment
    here meant that configuring a real provider -- which the testing guide
    asks operators to do -- broke the suite."""
    monkeypatch.setattr(settings, "ai_provider", "disabled")
    get_writing_evaluator.cache_clear()
    try:
        assert isinstance(get_writing_evaluator(), DisabledWritingEvaluator)
    finally:
        get_writing_evaluator.cache_clear()


def test_disabled_provider_abstains_rather_than_failing() -> None:
    evaluator = DisabledWritingEvaluator()
    result = evaluator.evaluate(
        WritingEvaluationRequest(
            task_prompt="p", response_text=GOOD_A2, target_level="A2", skill_key="s"
        )
    )
    assert result is None


def test_unknown_provider_mode_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app import providers

    monkeypatch.setattr(providers.settings, "ai_provider", "magic")
    providers.get_writing_evaluator.cache_clear()
    with pytest.raises(ProviderNotAvailableError, match="not a known mode"):
        providers.get_writing_evaluator()
    providers.get_writing_evaluator.cache_clear()


def test_low_confidence_evaluation_is_not_usable() -> None:
    """AI feedback must not move mastery without clearing a confidence bar."""
    evaluation = WritingEvaluation(
        dimensions=[RubricDimension(name="range", score=0.9, confidence=0.9, evidence=["cited"])],
        confidence=MIN_USABLE_CONFIDENCE - 0.01,
    )
    assert not evaluation.is_usable


def test_abstention_is_never_usable() -> None:
    evaluation = WritingEvaluation(confidence=1.0, abstain_reason="response too short")
    assert evaluation.abstained
    assert not evaluation.is_usable


def test_overall_score_weights_by_dimension_confidence() -> None:
    evaluation = WritingEvaluation(
        dimensions=[
            RubricDimension(name="a", score=1.0, confidence=1.0, evidence=["cited"]),
            RubricDimension(name="b", score=0.0, confidence=0.0, evidence=["cited"]),
        ],
        confidence=0.9,
    )
    assert evaluation.overall_score == 1.0
    assert evaluation.is_usable


def test_priority_feedback_is_capped_at_three() -> None:
    """Correcting everything teaches nothing (docs/LEARNING_SCIENCE.md)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WritingEvaluation(
            confidence=0.9,
            dimensions=[RubricDimension(name="a", score=1.0, confidence=1.0, evidence=["cited"])],
            priority_feedback=[
                {"category": "grammar", "original": "x", "improved": "y", "explanation": "z"}
            ]
            * 4,
        )


# --- End to end ------------------------------------------------------------------


def test_diagnostic_offers_a_writing_task(seeded_client: TestClient) -> None:
    """Milestone 1 needs production evidence, so a writing task must appear."""
    headers = register(seeded_client)
    bank = items_by_key()
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]

    seen_written = False
    for _ in range(40):
        nxt = seeded_client.get(f"/api/v1/diagnostics/{session_id}/next", headers=headers).json()
        if nxt["finished"]:
            break
        item = bank[nxt["item"]["key"]]
        if item.item_type is ItemType.WRITTEN_RESPONSE:
            seen_written = True
            answer = GOOD_A2
        elif item.item_type is ItemType.SELF_ASSESSMENT:
            answer = "3"
        else:
            answer = item.answer_key[0]
        seeded_client.post(
            f"/api/v1/diagnostics/{session_id}/responses",
            headers=headers,
            json={"item_key": nxt["item"]["key"], "response": answer},
        )

    assert seen_written, "the diagnostic never asked the learner to write anything"


def test_writing_produces_contextual_production_evidence(seeded_client: TestClient) -> None:
    headers = register(seeded_client)
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]

    response = seeded_client.post(
        f"/api/v1/diagnostics/{session_id}/responses",
        headers=headers,
        json={"item_key": "writing.a2.last_weekend", "response": GOOD_A2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provisional"] is True
    assert body["checks"]

    seeded_client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)
    profile = seeded_client.get("/api/v1/profile", headers=headers).json()
    written = next(
        skill for skill in profile["skills"] if skill["skill_key"] == "writing.linked_messages"
    )
    assert written["evidence_count"] == 1


def test_one_good_paragraph_is_not_mastery(seeded_client: TestClient) -> None:
    """Production is the strongest evidence, but one sample is still one context."""
    headers = register(seeded_client)
    session_id = seeded_client.post("/api/v1/diagnostics", headers=headers).json()["id"]
    seeded_client.post(
        f"/api/v1/diagnostics/{session_id}/responses",
        headers=headers,
        json={"item_key": "writing.a2.last_weekend", "response": GOOD_A2},
    )
    seeded_client.post(f"/api/v1/diagnostics/{session_id}/complete", headers=headers)

    profile = seeded_client.get("/api/v1/profile", headers=headers).json()
    written = next(
        skill for skill in profile["skills"] if skill["skill_key"] == "writing.linked_messages"
    )
    assert written["status"] == "emerging"
    assert written["cefr_estimate"] is None


def test_writing_prompt_reaches_the_client_with_its_requirements(
    seeded_client: TestClient,
) -> None:
    headers = register(seeded_client)
    seeded_client.post("/api/v1/diagnostics", headers=headers)
    prompt = items_by_key()["writing.b2.argument"].as_prompt()
    assert prompt["min_words"] == 90
    assert prompt["item_type"] == "written_response"


def test_every_level_has_more_than_one_writing_task(curriculum_dir: Path) -> None:
    """One task per band means a learner's second piece of writing at their
    level is the same prompt again."""
    from collections import Counter

    from apps.api.app.curriculum.tasks import parse_writing_tasks
    from apps.api.app.models.enums import CefrLevel

    tasks = parse_writing_tasks(curriculum_dir)
    assert {task.cefr_level for task in tasks} == set(CefrLevel)

    counts = Counter(task.cefr_level for task in tasks)
    thin = [level.value for level, count in counts.items() if count < 2]
    assert not thin, f"only one writing task at: {', '.join(sorted(thin))}"
