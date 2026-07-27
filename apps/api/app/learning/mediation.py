"""Deterministic analysis of a mediation response.

Mediation is the C-level task the CEFR actually cares about and that a harder
vocabulary quiz cannot stand in for: several sources go in, one account comes
out, aimed at a reader who has not seen them. `docs/ROADMAP.md` Milestone 7
names it, and warns against the substitution.

What can be checked without a model, and what cannot
----------------------------------------------------
Everything `learning/writing.py` checks still applies — length, sentences,
linking, prompted content — and this module adds the two that are specific
to mediation:

**Was every source drawn on?** Approximated by anchors: names, figures and
dates that survive paraphrase. Each source declares its own, the curriculum
parser proves they are distinctive, and a source whose anchors are all
absent was very likely not used. This is an approximation and is described
to the learner as one.

**Was it restated, or transcribed?** The longest run of consecutive words
shared with any source. Copying a paragraph is the characteristic failure of
this task, and unlike most things worth knowing about writing it is exactly
measurable.

Quoted spans are removed before that count. Quoting a source is legitimate
mediation when it is marked as a quote; the check is about passing someone
else's sentence off as your own account, which is a different act.

What none of this shows is whether the sources were conveyed *accurately*.
An anchor proves a figure was mentioned, not that it was reported correctly
— a learner can name the number and misrepresent it entirely. That is why
mediation evidence carries the lowest deterministic confidence of any
written task.

No model call, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .writing import (
    WritingAnalysis,
    WritingCheck,
    WritingRequirements,
    analyse,
    normalise_text,
)

#: How much to trust deterministic checks as a judgement of mediation.
#: Below writing's 0.45 on purpose: the central claim of a mediation task —
#: that the sources were conveyed faithfully — is precisely the one no
#: countable check can reach.
DETERMINISTIC_CONFIDENCE = 0.40

#: Runs at or below this length are ordinary overlap, not copying. A shared
#: seven-word run between an account and its source is unremarkable when the
#: source names an organisation and a date; a shared fifteen-word run is a
#: sentence someone did not write.
DEFAULT_MAX_VERBATIM_WORDS = 8

#: The shortest run worth reporting at all, whatever a task asks for.
MIN_ALLOWED_VERBATIM_WORDS = 4

#: Straight and curly quotation marks, written as escapes: the curly ones are
#: visually ambiguous in source and ruff rejects them on sight (RUF001).
#: Bounded repetition on purpose -- an unbalanced quote in a long submission
#: should not make the matcher walk the whole text.
_QUOTED = re.compile(
    "[\"\u201c\u2018']"  # opening: straight, curly double, curly single
    "([^\"\u201d\u2019']{0,400})"
    "[\"\u201d\u2019']"  # closing
)


@dataclass(frozen=True)
class Source:
    """One thing the learner has to read and then account for."""

    key: str
    title: str
    #: What kind of thing it is — `article`, `email`, `chart_summary`, and so
    #: on. Mediation across *different* kinds of source is harder and more
    #: realistic than across three articles, so the planner can see the mix.
    kind: str
    text: str
    #: Names, figures and dates that survive paraphrase. Distinctive to this
    #: source, proven so by the curriculum parser.
    anchors: tuple[str, ...]


@dataclass(frozen=True)
class MediationAnalysis:
    """Everything the deterministic pass found, learner-facing."""

    writing: WritingAnalysis
    used_sources: tuple[str, ...]
    unused_sources: tuple[str, ...]
    longest_copied_run: int
    copied_from: str | None
    checks: tuple[WritingCheck, ...]

    @property
    def word_count(self) -> int:
        return self.writing.word_count

    @property
    def passed_checks(self) -> int:
        return sum(1 for check in self.checks if check.passed)

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        return round(self.passed_checks / len(self.checks), 4)

    @property
    def met_minimum(self) -> bool:
        """Substantial enough to be evidence at all."""
        return self.writing.met_minimum

    @property
    def drew_on_every_source(self) -> bool:
        return not self.unused_sources

    @property
    def was_copied(self) -> bool:
        return self.copied_from is not None


def strip_quotations(text: str) -> str:
    """Remove marked quotations.

    A learner who quotes a source and marks it as a quote has done something
    legitimate. Counting those words as copying would teach them to stop
    attributing, which is the opposite of the lesson.
    """
    return _QUOTED.sub(" ", text)


def _words(text: str) -> list[str]:
    """Normalised tokens that actually carry a word.

    `normalise_text` keeps hyphens and apostrophes, which is right for the
    writing checks — "well-known" is one word — but it means a stray "--"
    survives as a token of its own. Left in, a learner could break a copied
    sentence into unmatched fragments by scattering dashes through it, and
    the copy check would report a much shorter run than was really lifted.
    Tokens with no letter or digit in them are dropped here for that reason.
    """
    return [token for token in normalise_text(text).split() if any(c.isalnum() for c in token)]


def longest_shared_run(response: str, source: str) -> int:
    """Length, in words, of the longest run the two texts share.

    Compared on normalised words, so re-punctuating or re-casing a copied
    sentence does not hide it.

    Dynamic programming over the two word lists — the classic longest common
    substring. Both texts are at most a few hundred words, so the quadratic
    table is nothing, and the alternative (hashing every n-gram) would need a
    length guessed in advance.
    """
    left = _words(response)
    right = _words(source)
    if not left or not right:
        return 0

    previous = [0] * (len(right) + 1)
    best = 0
    for i in range(1, len(left) + 1):
        current = [0] * (len(right) + 1)
        word = left[i - 1]
        for j in range(1, len(right) + 1):
            if word == right[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best:
                    best = current[j]
        previous = current
    return best


def sources_drawn_on(response: str, sources: tuple[Source, ...]) -> tuple[str, ...]:
    """Which sources the response shows a trace of.

    One anchor is enough. Requiring all of them would mark down a learner who
    summarised a source well but selectively, which is what summarising is.
    """
    normalised = f" {normalise_text(response)} "
    used = [
        source.key
        for source in sources
        if any(f" {normalise_text(anchor)} " in normalised for anchor in source.anchors)
    ]
    return tuple(used)


def analyse_mediation(
    text: str,
    requirements: WritingRequirements,
    sources: tuple[Source, ...],
    *,
    max_verbatim_words: int = DEFAULT_MAX_VERBATIM_WORDS,
) -> MediationAnalysis:
    """Analyse a mediation response. Total: never raises.

    The writing checks run first and unchanged, so a mediation task is not a
    different standard of English, only an additional demand on top of one.
    """
    base = analyse(text, requirements)

    used = sources_drawn_on(text, sources)
    unused = tuple(source.key for source in sources if source.key not in used)

    unquoted = strip_quotations(text)
    runs = {source.key: longest_shared_run(unquoted, source.text) for source in sources}
    longest = max(runs.values(), default=0)
    # Ties break on key so the same submission always names the same source.
    copied_from = (
        min((key for key, run in runs.items() if run == longest), default=None)
        if longest > max_verbatim_words
        else None
    )

    titles = {source.key: source.title for source in sources}

    checks = [
        *base.checks,
        WritingCheck(
            code="sources",
            passed=not unused,
            message=(
                "You drew on every source."
                if not unused
                else "These sources do not seem to appear in your account: "
                + ", ".join(titles[key] for key in unused)
            ),
        ),
        WritingCheck(
            code="restated",
            passed=copied_from is None,
            message=(
                f"The longest run you share with a source is {longest} words — "
                f"this is your account, not a copy of theirs."
                if copied_from is None
                else f"{longest} consecutive words match {titles[copied_from]!r} exactly. "
                f"Mediation means restating, not transcribing. Quote it and mark "
                f"the quotation, or say it in your own words."
            ),
        ),
    ]

    return MediationAnalysis(
        writing=base,
        used_sources=used,
        unused_sources=unused,
        longest_copied_run=longest,
        copied_from=copied_from,
        checks=tuple(checks),
    )


def summarise(analysis: MediationAnalysis) -> str:
    """A learner-facing summary that never claims to have judged fidelity."""
    if not analysis.met_minimum:
        return (
            "Too short to say much yet. A reader who has not seen the sources "
            "needs more than this to go on."
        )
    if analysis.was_copied:
        return (
            "Some of this is copied rather than restated. The checks below say "
            "where; nothing here has judged how accurately you reported the sources."
        )
    if not analysis.drew_on_every_source:
        return (
            "Part of the material has not made it into your account. The checks "
            "below say which, and this is an approximation — if you covered a "
            "source without naming anything in it, say so and move on."
        )
    return (
        "These are automatic checks on length, structure, source coverage and "
        "whether you restated rather than copied. Nothing here has judged how "
        "accurately you conveyed what the sources said."
    )


__all__ = [
    "DEFAULT_MAX_VERBATIM_WORDS",
    "DETERMINISTIC_CONFIDENCE",
    "MIN_ALLOWED_VERBATIM_WORDS",
    "MediationAnalysis",
    "Source",
    "analyse_mediation",
    "longest_shared_run",
    "sources_drawn_on",
    "strip_quotations",
    "summarise",
]
