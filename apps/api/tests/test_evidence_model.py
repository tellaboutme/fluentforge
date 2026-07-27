"""Regression fixtures for the evidence-to-mastery model.

These encode the learning-system invariants in `CLAUDE.md`. If a future model
change breaks one of these, the change is wrong until the invariant is
explicitly renegotiated in `docs/DECISION_LOG.md`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.api.app.learning.evidence import (
    DEFAULT_CONFIG,
    EVIDENCE_TYPE_WEIGHTS,
    Observation,
    compute_mastery,
    difficulty_relevance,
    weigh,
)
from apps.api.app.models.enums import EvidenceType

UTC = timezone.utc
NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def obs(
    evidence_type: EvidenceType = EvidenceType.CONTEXTUAL_PRODUCTION,
    score: float = 1.0,
    context: str | None = "c0",
    minutes_ago: int = 60,
    **kwargs: float,
) -> Observation:
    return Observation(
        evidence_type=evidence_type,
        score=score,
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        context_key=context,
        **kwargs,
    )


def spread(count: int, contexts: int, **kwargs: object) -> list[Observation]:
    """`count` observations spread across `contexts` distinct contexts."""
    return [
        obs(context=f"c{index % contexts}", minutes_ago=60 + index * 60, **kwargs)  # type: ignore[arg-type]
        for index in range(count)
    ]


# --- Weighting components --------------------------------------------------------


def test_evidence_types_are_ordered_by_strength() -> None:
    """Recognising something must never count as much as using it in a new context."""
    assert (
        EVIDENCE_TYPE_WEIGHTS[EvidenceType.SELF_REPORT]
        < EVIDENCE_TYPE_WEIGHTS[EvidenceType.RECOGNITION]
        < EVIDENCE_TYPE_WEIGHTS[EvidenceType.CONTROLLED_RECALL]
        < EVIDENCE_TYPE_WEIGHTS[EvidenceType.CONTEXTUAL_PRODUCTION]
        <= EVIDENCE_TYPE_WEIGHTS[EvidenceType.TRANSFER]
    )


def test_every_evidence_type_has_a_weight() -> None:
    for evidence_type in EvidenceType:
        assert evidence_type in EVIDENCE_TYPE_WEIGHTS


def test_hard_success_outweighs_easy_success() -> None:
    assert difficulty_relevance(1.0, 0.9, DEFAULT_CONFIG) > difficulty_relevance(
        1.0, 0.1, DEFAULT_CONFIG
    )


def test_easy_failure_outweighs_hard_failure() -> None:
    assert difficulty_relevance(0.0, 0.1, DEFAULT_CONFIG) > difficulty_relevance(
        0.0, 0.9, DEFAULT_CONFIG
    )


def test_difficulty_relevance_never_reaches_zero() -> None:
    """Mismatched difficulty is discounted, never discarded."""
    for score in (0.0, 1.0):
        for difficulty in (0.0, 0.5, 1.0):
            assert difficulty_relevance(score, difficulty, DEFAULT_CONFIG) > 0


def test_hints_reduce_evidence_weight() -> None:
    unaided = weigh(obs(independence=1.0), [])
    hinted = weigh(obs(independence=0.2), [])
    assert hinted.effective < unaided.effective


def test_repeat_of_same_item_is_worth_less() -> None:
    first = obs(context="same", minutes_ago=120)
    second = obs(context="same", minutes_ago=60)
    assert weigh(second, [first]).effective < weigh(first, []).effective


def test_spaced_repetition_keeps_full_weight() -> None:
    """Only *recent* repetition is damped; spaced retrieval is the point."""
    old = obs(context="same", minutes_ago=60 * 24 * 10)
    now_ish = obs(context="same", minutes_ago=60)
    assert weigh(now_ish, [old]).effective == pytest.approx(weigh(now_ish, []).effective)


# --- Aggregate behaviour ---------------------------------------------------------


def test_no_evidence_yields_zero() -> None:
    result = compute_mastery([], now=NOW)
    assert result.mastery_probability == 0.0
    assert result.confidence == 0.0
    assert result.last_observed_at is None


def test_unaided_recall_beats_heavily_scaffolded_success() -> None:
    """The headline invariant: a propped-up correct answer proves less."""
    unaided = compute_mastery(spread(8, 4, independence=1.0), now=NOW)
    scaffolded = compute_mastery(spread(8, 4, independence=0.2), now=NOW)

    assert unaided.mastery_probability > scaffolded.mastery_probability
    assert unaided.confidence > scaffolded.confidence


def test_drilling_one_item_cannot_manufacture_mastery() -> None:
    """Many correct answers in one context must not beat fewer across many."""
    drilled = compute_mastery(spread(15, 1), now=NOW)
    varied = compute_mastery(spread(6, 3), now=NOW)

    assert drilled.distinct_contexts == 1
    assert drilled.confidence < varied.confidence


def test_recognition_alone_stays_below_production_evidence() -> None:
    recognition = compute_mastery(
        spread(
            8,
            4,
        ),
        now=NOW,
    )
    assert recognition.mastery_probability > 0
    only_recognition = compute_mastery(
        [
            obs(EvidenceType.RECOGNITION, context=f"c{i % 4}", minutes_ago=60 + i * 60)
            for i in range(8)
        ],
        now=NOW,
    )
    assert only_recognition.mastery_probability < recognition.mastery_probability


def test_self_report_barely_moves_the_estimate() -> None:
    claimed = compute_mastery(
        [obs(EvidenceType.SELF_REPORT, context=f"c{i}", minutes_ago=60 + i * 60) for i in range(5)],
        now=NOW,
    )
    demonstrated = compute_mastery(spread(5, 5), now=NOW)
    assert claimed.mastery_probability < demonstrated.mastery_probability


def test_failures_lower_the_estimate() -> None:
    passing = compute_mastery(spread(6, 3, score=1.0), now=NOW)
    failing = compute_mastery(spread(6, 3, score=0.0), now=NOW)
    assert failing.mastery_probability < 0.5 < passing.mastery_probability


def test_confidence_decays_but_mastery_does_not() -> None:
    """Not observing a skill makes us less sure; it does not make the learner worse."""
    observations = spread(8, 4)
    fresh = compute_mastery(observations, now=NOW)
    stale = compute_mastery(observations, now=NOW + timedelta(days=120))

    assert stale.mastery_probability == fresh.mastery_probability
    assert stale.confidence < fresh.confidence


def test_confidence_halves_over_the_configured_halflife() -> None:
    observations = spread(8, 4)
    fresh = compute_mastery(observations, now=NOW)
    later = compute_mastery(
        observations, now=NOW + timedelta(days=DEFAULT_CONFIG.confidence_halflife_days)
    )
    assert later.confidence == pytest.approx(fresh.confidence / 2, rel=0.02)


def test_confidence_grows_with_breadth() -> None:
    narrow = compute_mastery(spread(6, 1), now=NOW)
    wide = compute_mastery(spread(6, 3), now=NOW)
    assert wide.confidence > narrow.confidence


def test_low_evaluator_confidence_moves_the_estimate_less() -> None:
    certain = compute_mastery(spread(6, 3, confidence=1.0), now=NOW)
    unsure = compute_mastery(spread(6, 3, confidence=0.2), now=NOW)
    assert unsure.mastery_probability < certain.mastery_probability


def test_probability_and_confidence_stay_bounded() -> None:
    for observations in (spread(40, 8), spread(40, 8, score=0.0), spread(1, 1)):
        result = compute_mastery(observations, now=NOW)
        assert 0.0 <= result.mastery_probability <= 1.0
        assert 0.0 <= result.confidence <= 1.0


def test_result_is_order_independent() -> None:
    observations = spread(8, 4)
    assert (
        compute_mastery(observations, now=NOW).mastery_probability
        == compute_mastery(list(reversed(observations)), now=NOW).mastery_probability
    )


def test_breakdown_explains_the_weight() -> None:
    """The UI must be able to answer 'why did my estimate change?'."""
    result = compute_mastery(spread(3, 3), now=NOW)
    assert len(result.breakdowns) == 3
    for breakdown in result.breakdowns:
        assert 0 < breakdown.effective <= 1
        assert breakdown.base == EVIDENCE_TYPE_WEIGHTS[EvidenceType.CONTEXTUAL_PRODUCTION]
