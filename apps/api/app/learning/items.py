"""Deterministic diagnostic item types and scoring.

Deterministic means: the same response always produces the same score, computed
locally, with no model call. `docs/PRODUCT_SPEC.md` requires the core learning
loop to work without a paid AI provider, so the diagnostic is built entirely
from item types that can be scored this way.

Answer keys never leave the server. `DiagnosticItem.as_prompt()` is the only
shape sent to a client.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..models.enums import CefrLevel, EvidenceType
from .writing import (
    DETERMINISTIC_CONFIDENCE,
    WritingRequirements,
    analyse,
    summarise,
)


class ItemType(str, Enum):
    """Item types available to the diagnostic.

    Each maps to the strongest evidence type it can honestly produce: a
    multiple-choice question demonstrates recognition, never production.
    """

    MULTIPLE_CHOICE = "multiple_choice"
    GAP_FILL = "gap_fill"
    WORD_ORDER = "word_order"
    SELF_ASSESSMENT = "self_assessment"
    WRITTEN_RESPONSE = "written_response"

    @property
    def evidence_type(self) -> EvidenceType:
        return {
            ItemType.MULTIPLE_CHOICE: EvidenceType.RECOGNITION,
            ItemType.GAP_FILL: EvidenceType.CONTROLLED_RECALL,
            ItemType.WORD_ORDER: EvidenceType.CONTROLLED_RECALL,
            ItemType.SELF_ASSESSMENT: EvidenceType.SELF_REPORT,
            ItemType.WRITTEN_RESPONSE: EvidenceType.CONTEXTUAL_PRODUCTION,
        }[self]

    @property
    def is_productive(self) -> bool:
        """Whether the learner composes language rather than selecting it."""
        return self is ItemType.WRITTEN_RESPONSE

    @property
    def evaluator_confidence(self) -> float:
        """How much to trust this item type's score as a judgement.

        Deterministic checks on free writing confirm production but cannot
        judge accuracy, so written responses carry reduced confidence into the
        mastery model. See `learning/writing.py`.
        """
        if self is ItemType.WRITTEN_RESPONSE:
            return DETERMINISTIC_CONFIDENCE
        return 1.0


@dataclass(frozen=True)
class DiagnosticItem:
    """One scorable item.

    `skill_key` ties the item to a curriculum skill node, so evidence lands on
    the competency rather than on the exercise.
    """

    key: str
    item_type: ItemType
    skill_key: str
    cefr_level: CefrLevel
    prompt: str
    answer_key: tuple[str, ...]
    options: tuple[str, ...] = ()
    difficulty: float = 0.5
    instructions: str = ""
    distractor_rationale: dict[str, str] = field(default_factory=dict)
    #: Only meaningful for `written_response` items.
    requirements: WritingRequirements | None = None

    @property
    def evidence_type(self) -> EvidenceType:
        return self.item_type.evidence_type

    def as_prompt(self) -> dict[str, Any]:
        """The client-safe view. Deliberately excludes `answer_key`."""
        return {
            "key": self.key,
            "item_type": self.item_type.value,
            "skill_key": self.skill_key,
            "cefr_level": self.cefr_level.value,
            "prompt": self.prompt,
            "instructions": self.instructions,
            "options": list(self.options),
            "difficulty": self.difficulty,
            "evidence_type": self.evidence_type.value,
            # Requirements are shown up front: a learner should never fail a
            # length check they were not told about.
            "min_words": self.requirements.min_words if self.requirements else None,
            "max_words": self.requirements.max_words if self.requirements else None,
        }


@dataclass(frozen=True)
class ScoredResponse:
    score: float
    correct: bool
    normalised_response: str
    expected: tuple[str, ...]
    explanation: str
    #: Per-check detail for written responses; empty for closed items.
    checks: tuple[tuple[str, bool, str], ...] = ()
    #: How much this score should be trusted as a judgement of the skill.
    evaluator_confidence: float = 1.0
    #: True when scoring is provisional pending a rubric evaluator.
    provisional: bool = False


def normalise(text: str) -> str:
    """Normalise a free-text response before comparison.

    Case, surrounding punctuation, accents, and repeated whitespace are not what
    is being assessed here, so they must not decide correctness. Straight and
    curly apostrophes are treated as the same character.
    """
    folded = unicodedata.normalize("NFKD", text.strip().lower())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    # Escaped so the source stays ASCII: U+2019 RIGHT SINGLE QUOTATION MARK
    # and U+02BC MODIFIER LETTER APOSTROPHE both fold to a plain apostrophe.
    folded = folded.replace("\u2019", "'").replace("\u02bc", "'")
    folded = "".join(char for char in folded if char.isalnum() or char.isspace() or char in "'-")
    return " ".join(folded.split())


def score_response(item: DiagnosticItem, response: str) -> ScoredResponse:
    """Score one response. Deterministic and total: never raises on bad input."""
    if item.item_type is ItemType.SELF_ASSESSMENT:
        return _score_self_assessment(item, response)
    if item.item_type is ItemType.WRITTEN_RESPONSE:
        return _score_written_response(item, response)

    normalised = normalise(response)
    expected = tuple(normalise(answer) for answer in item.answer_key)
    correct = normalised in expected and normalised != ""

    return ScoredResponse(
        score=1.0 if correct else 0.0,
        correct=correct,
        normalised_response=normalised,
        expected=item.answer_key,
        explanation=_explain(item, normalised, correct),
    )


def _score_self_assessment(item: DiagnosticItem, response: str) -> ScoredResponse:
    """A can-do self-rating on a 0-4 scale, mapped to 0..1.

    Recorded as `self_report` evidence, which the mastery model weights very
    low. It seeds the diagnostic's starting point; it never establishes mastery.
    """
    try:
        rating = int(str(response).strip())
    except (TypeError, ValueError):
        rating = 0
    rating = max(0, min(4, rating))

    return ScoredResponse(
        score=rating / 4.0,
        correct=rating >= 3,
        normalised_response=str(rating),
        expected=item.answer_key,
        explanation="Self-rating recorded. It guides item selection, not your level.",
    )


def _score_written_response(item: DiagnosticItem, response: str) -> ScoredResponse:
    """Score free writing against countable requirements only.

    The score is the proportion of checks met, and it is flagged provisional:
    these checks confirm the learner produced language, not that they produced
    it accurately. `evaluator_confidence` carries that caveat into the mastery
    model rather than leaving it as a comment.
    """
    requirements = item.requirements or WritingRequirements()
    analysis = analyse(response, requirements)

    return ScoredResponse(
        score=analysis.score,
        # "Correct" is the wrong frame for writing; met_minimum records only
        # that the response was substantial enough to count as evidence.
        correct=analysis.met_minimum,
        normalised_response=response.strip(),
        expected=(),
        explanation=summarise(analysis),
        checks=tuple((check.code, check.passed, check.message) for check in analysis.checks),
        evaluator_confidence=item.item_type.evaluator_confidence,
        provisional=True,
    )


def _explain(item: DiagnosticItem, normalised: str, correct: bool) -> str:
    if correct:
        return "Correct."
    rationale = item.distractor_rationale.get(normalised)
    if rationale:
        return rationale
    return f"Not quite. Expected: {item.answer_key[0]}."
