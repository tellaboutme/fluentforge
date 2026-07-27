"""Deterministic analysis of a written response.

What this module can and cannot do
----------------------------------
It measures things that are *countable*: length, sentence structure, connective
use, lexical variety, and whether prompted content appears. That is genuine
evidence of production — the learner composed the text themselves — but it is
partial. Grammatical accuracy, precision, register, and whether the writing
actually achieves the task are not measurable this way, and this module does
not pretend otherwise.

That honesty is expressed numerically: written responses record
`contextual_production` evidence at reduced *evaluator confidence*
(`DETERMINISTIC_CONFIDENCE`). The mastery model multiplies weight by that
confidence, so a deterministic-only pass moves the estimate less than a
rubric-scored one would. When an AI evaluator is configured it adds a second,
schema-validated evidence event rather than overwriting this one.

No model call, no network. `docs/PRODUCT_SPEC.md` requires the core learning
loop to work with AI disabled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: How much to trust deterministic checks as a judgement of writing quality.
#: They confirm the learner produced language; they cannot confirm it was good.
DETERMINISTIC_CONFIDENCE = 0.45

#: Connectives an A1-B2 learner is expected to reach for. Deliberately common:
#: this measures whether ideas are being joined at all, not stylistic range.
CONNECTIVES = frozenset(
    {
        "and",
        "but",
        "so",
        "because",
        "then",
        "or",
        "also",
        "however",
        "although",
        "though",
        "while",
        "when",
        "after",
        "before",
        "if",
        "since",
        "therefore",
        "moreover",
        "whereas",
        "unless",
        "besides",
        "furthermore",
        "nevertheless",
        "instead",
        "finally",
        "first",
        "secondly",
        "for example",
        "such as",
        "in addition",
        "as a result",
    }
)

_SENTENCE_SPLIT = re.compile(r"[.!?]+(?:\s|$)")
#: Everything that is not a letter, digit, apostrophe, or hyphen.
_PUNCTUATION = re.compile(r"[^a-z0-9'\-]+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019\-]*")


@dataclass(frozen=True)
class WritingRequirements:
    """What a prompt asks for. All checks are optional except length."""

    min_words: int = 40
    max_words: int = 400
    #: Lowercase substrings the response should contain, e.g. ["yesterday"].
    #: Matched on normalised text, so casing and punctuation do not matter.
    required_elements: tuple[str, ...] = ()
    min_sentences: int = 2
    min_connectives: int = 1


@dataclass(frozen=True)
class WritingCheck:
    """One pass/fail observation, phrased for the learner."""

    code: str
    passed: bool
    message: str


@dataclass(frozen=True)
class WritingAnalysis:
    word_count: int
    sentence_count: int
    distinct_words: int
    connectives_used: tuple[str, ...]
    missing_elements: tuple[str, ...]
    checks: tuple[WritingCheck, ...] = field(default=())

    @property
    def lexical_variety(self) -> float:
        """Distinct words over total. A crude range proxy, not a quality score."""
        if self.word_count == 0:
            return 0.0
        return round(self.distinct_words / self.word_count, 4)

    @property
    def passed_checks(self) -> int:
        return sum(1 for check in self.checks if check.passed)

    @property
    def score(self) -> float:
        """Proportion of checks met, 0..1.

        A proportion rather than all-or-nothing: a response that is long enough
        and on-topic but under-linked is partial evidence, not zero.
        """
        if not self.checks:
            return 0.0
        return round(self.passed_checks / len(self.checks), 4)

    @property
    def met_minimum(self) -> bool:
        """Whether the response is substantial enough to be evidence at all."""
        return any(check.code == "length" and check.passed for check in self.checks)


def normalise_text(text: str) -> str:
    """Lowercase, fold the curly apostrophe (U+2019), and drop punctuation.

    Punctuation must go, not just whitespace: connectives are matched as
    space-delimited words, so "However, the journey" would otherwise fail to
    match "however" and silently under-count a learner's linking.
    """
    folded = text.replace("\u2019", "'").lower()
    return " ".join(_PUNCTUATION.sub(" ", folded).split())


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def count_sentences(text: str) -> int:
    """Count sentence-final punctuation, treating a trailing fragment as one.

    A learner who writes without full stops still wrote something; they get one
    sentence, and the connective and length checks carry the rest.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    parts = [part for part in _SENTENCE_SPLIT.split(stripped) if part.strip()]
    return max(len(parts), 1)


def find_connectives(text: str) -> tuple[str, ...]:
    normalised = f" {normalise_text(text)} "
    found = {connective for connective in CONNECTIVES if f" {connective} " in normalised}
    return tuple(sorted(found))


def analyse(text: str, requirements: WritingRequirements) -> WritingAnalysis:
    """Analyse a response against a prompt's requirements.

    Total: never raises, whatever the learner submits.
    """
    words = _WORD.findall(text)
    word_count = len(words)
    sentence_count = count_sentences(text)
    distinct = len({word.lower() for word in words})
    connectives = find_connectives(text)

    normalised = normalise_text(text)
    missing = tuple(
        element for element in requirements.required_elements if element.lower() not in normalised
    )

    checks: list[WritingCheck] = [
        WritingCheck(
            code="length",
            passed=requirements.min_words <= word_count <= requirements.max_words,
            message=_length_message(word_count, requirements),
        ),
        WritingCheck(
            code="sentences",
            passed=sentence_count >= requirements.min_sentences,
            message=(
                f"You wrote {sentence_count} sentence"
                f"{'' if sentence_count == 1 else 's'}; "
                f"aim for at least {requirements.min_sentences}."
                if sentence_count < requirements.min_sentences
                else f"{sentence_count} sentences."
            ),
        ),
        WritingCheck(
            code="connectives",
            passed=len(connectives) >= requirements.min_connectives,
            message=(
                "Try joining your ideas with words like 'because', 'but' or 'so'."
                if len(connectives) < requirements.min_connectives
                else f"You linked ideas using: {', '.join(connectives)}."
            ),
        ),
    ]

    if requirements.required_elements:
        checks.append(
            WritingCheck(
                code="content",
                passed=not missing,
                message=(
                    f"The task also asked you to mention: {', '.join(missing)}."
                    if missing
                    else "You covered everything the task asked for."
                ),
            )
        )

    return WritingAnalysis(
        word_count=word_count,
        sentence_count=sentence_count,
        distinct_words=distinct,
        connectives_used=connectives,
        missing_elements=missing,
        checks=tuple(checks),
    )


def _length_message(word_count: int, requirements: WritingRequirements) -> str:
    if word_count < requirements.min_words:
        return f"{word_count} words. This task asks for at least {requirements.min_words}."
    if word_count > requirements.max_words:
        return f"{word_count} words. Try to keep it under {requirements.max_words}."
    return f"{word_count} words — a good length."


def summarise(analysis: WritingAnalysis) -> str:
    """A learner-facing summary that never claims to have judged accuracy."""
    if not analysis.met_minimum:
        return (
            "Too short to say much yet. Write a bit more and the checks below will tell you more."
        )
    return (
        "These are automatic checks on length, structure and content. "
        "They do not judge grammar or word choice."
    )
