"""A taxonomy of linguistic features, used to name what went wrong.

Why this exists
---------------
Until now an error was logged as ``item.<skill_key>`` — "something in
`grammar.past_future_basic` went wrong". That is too coarse to act on.
`docs/LEARNING_SCIENCE.md` asks that corrections prioritise errors which
*block meaning*, *repeat*, or *match the current objective*; none of the three
is decidable when the only label is the skill the item happened to belong to.
A learner who confuses `since` and `for` and a learner who cannot form a
question would be filed identically.

So an error names a **feature**: a small, stable, linguistically meaningful
thing that can be practised on its own. Two occurrences share a pattern only
when they are the same feature, which is what makes "repeated" mean something.

Design rules
------------
- Codes are ``domain.area.feature`` and are **stable machine codes**. Never
  rename one; add a new code and leave the old one readable.
- The set is closed. An unknown code is a validation failure, not a new
  pattern, so a typo in curriculum source cannot create an unpracticeable
  error category.
- Deliberately coarse-grained. Around thirty features a curriculum author can
  hold in their head beats two hundred nobody selects correctly. It grows
  when content needs it to, not in anticipation.
- ``typically_blocks_meaning`` is a *default*, not a verdict. Whether a
  particular slip destroyed the message depends on the utterance, so content
  and evaluators may override it per occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.enums import SkillDomain

TAXONOMY_VERSION = "0.1.0"

#: Errors logged before the feature taxonomy existed use this prefix. They are
#: still displayed and still schedule practice; they simply cannot be grouped
#: as precisely. See `migrate_legacy_code`.
LEGACY_PREFIX = "item."


@dataclass(frozen=True)
class Feature:
    """One practisable linguistic feature."""

    code: str
    #: Short learner-facing name. Appears in the review queue, so it must read
    #: as a thing to work on rather than as a diagnosis.
    label: str
    #: What the mistake actually looks like, for the error log and for content
    #: authors choosing a code.
    description: str
    domain: SkillDomain
    #: Whether a slip of this kind usually costs the listener the message.
    typically_blocks_meaning: bool


def _f(
    code: str,
    label: str,
    description: str,
    domain: SkillDomain,
    blocks: bool,
) -> Feature:
    return Feature(
        code=code,
        label=label,
        description=description,
        domain=domain,
        typically_blocks_meaning=blocks,
    )


_ALL: tuple[Feature, ...] = (
    # --- Grammar: time and aspect ------------------------------------------
    # Tense errors are meaning-blocking by default: putting an event in the
    # wrong time is not a surface slip, it is a different statement.
    _f(
        "grammar.tense.past_simple_form",
        "Past simple forms",
        "Wrong form for a finished past action, including irregular verbs "
        "and negatives or questions with 'did'.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.tense.present_simple_form",
        "Present simple forms",
        "Missing third-person -s, or wrong use of 'do'/'does' in negatives and questions.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.tense.progressive_vs_simple",
        "Simple or continuous",
        "Choosing a continuous form for a habit or state, or a simple form "
        "for something in progress.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.tense.perfect_vs_past",
        "Present perfect or past simple",
        "Using the present perfect with a finished time, or the past simple "
        "where the link to now is the point.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.tense.future_reference",
        "Talking about the future",
        "Choosing between 'will', 'going to', and present forms for "
        "arrangements, predictions, and decisions.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.tense.sequence_backshift",
        "Time in reported speech",
        "Failing to shift the tense back when reporting what someone said.",
        SkillDomain.GRAMMAR,
        True,
    ),
    # --- Grammar: noun phrase ----------------------------------------------
    _f(
        "grammar.article.definite_indefinite",
        "a, the, or nothing",
        "Choosing the wrong article, or leaving one out where English requires it.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.noun.countability",
        "Countable and uncountable",
        "Treating an uncountable noun as countable, or the reverse — "
        "'an advice', 'many informations'.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.quantifier.choice",
        "Quantifiers",
        "Wrong quantifier for the noun: 'much people', 'a few water'.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.pronoun.reference",
        "Pronoun reference",
        "A pronoun with no clear antecedent, or one that points at the wrong thing.",
        SkillDomain.GRAMMAR,
        True,
    ),
    # --- Grammar: clause and sentence --------------------------------------
    _f(
        "grammar.agreement.subject_verb",
        "Subject and verb agreement",
        "Verb does not agree with its subject, especially across an intervening phrase.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.word_order.statement",
        "Word order in statements",
        "Constituents in an order English does not allow, typically the "
        "object or an adverb in the wrong place.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.word_order.question",
        "Question formation",
        "Missing inversion or auxiliary in a direct question, or wrongly "
        "inverting an indirect one.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.negation.form",
        "Negation",
        "Wrong negative form, double negation, or negation attached to the wrong element.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.clause.subordination",
        "Joining clauses",
        "Wrong subordinator, or a subordinate clause left without the main clause it depends on.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.clause.relative",
        "Relative clauses",
        "Wrong relative pronoun, a resumptive pronoun, or a relative clause "
        "attached to the wrong noun.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.conditional.form",
        "Conditionals",
        "Mismatched tenses across the 'if' clause and the result clause.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.passive.form",
        "Passive forms",
        "Wrong auxiliary or participle in a passive, or a passive where the agent was the point.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.modality.obligation",
        "Modal verbs",
        "Wrong modal for obligation, permission, ability, or likelihood.",
        SkillDomain.GRAMMAR,
        True,
    ),
    _f(
        "grammar.verb_pattern.complementation",
        "What follows a verb",
        "Wrong pattern after a verb: infinitive for gerund, a missing "
        "object, or a wrong preposition in the pattern.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.preposition.time_place",
        "Prepositions of time and place",
        "Wrong preposition in a time or place expression.",
        SkillDomain.GRAMMAR,
        False,
    ),
    _f(
        "grammar.comparison.form",
        "Comparatives and superlatives",
        "Wrong comparative or superlative form, or a doubled one such as 'more easier'.",
        SkillDomain.GRAMMAR,
        False,
    ),
    # --- Vocabulary ---------------------------------------------------------
    _f(
        "lexis.collocation.verb_noun",
        "Words that go together",
        "A combination English does not use — 'do a mistake', 'make homework'.",
        SkillDomain.VOCABULARY,
        False,
    ),
    _f(
        "lexis.word_form.derivation",
        "Word forms",
        "Right root, wrong part of speech: 'a success decision', 'he is very succeed'.",
        SkillDomain.VOCABULARY,
        False,
    ),
    _f(
        "lexis.confusable.pair",
        "Easily confused words",
        "Two words the learner reliably swaps, such as 'lend'/'borrow' or 'affect'/'effect'.",
        SkillDomain.VOCABULARY,
        True,
    ),
    _f(
        "lexis.phrasal_verb.meaning",
        "Phrasal verbs",
        "Wrong particle, or a phrasal verb used with a meaning it does not carry.",
        SkillDomain.VOCABULARY,
        True,
    ),
    _f(
        "lexis.precision.approximation",
        "Precise word choice",
        "A word close enough to be understood but not the one a competent user would pick.",
        SkillDomain.VOCABULARY,
        False,
    ),
    # --- Discourse ----------------------------------------------------------
    _f(
        "discourse.cohesion.connective",
        "Linking ideas",
        "Ideas left unjoined, or a connective that signals the wrong relationship between them.",
        SkillDomain.DISCOURSE,
        True,
    ),
    _f(
        "discourse.organisation.paragraphing",
        "Organising a text",
        "No visible structure: no opening, no grouping of related points, or no close.",
        SkillDomain.DISCOURSE,
        False,
    ),
    _f(
        "discourse.reference.given_new",
        "Introducing and tracking things",
        "Referring to something as though already known when it has not been introduced.",
        SkillDomain.DISCOURSE,
        True,
    ),
    # --- Pragmatics ---------------------------------------------------------
    _f(
        "pragmatics.register.formality",
        "Formal and informal",
        "Level of formality that does not fit the reader or the situation.",
        SkillDomain.PRAGMATICS,
        False,
    ),
    _f(
        "pragmatics.politeness.directness",
        "Softening a request",
        "A request or disagreement more blunt than the situation allows.",
        SkillDomain.PRAGMATICS,
        False,
    ),
    # --- Mechanics ----------------------------------------------------------
    _f(
        "mechanics.punctuation.sentence_boundary",
        "Sentence boundaries",
        "Run-on sentences, comma splices, or missing full stops.",
        SkillDomain.WRITTEN_PRODUCTION,
        True,
    ),
    _f(
        "mechanics.spelling.common",
        "Spelling",
        "Misspelling of a word the learner is expected to know at this level.",
        SkillDomain.WRITTEN_PRODUCTION,
        False,
    ),
    # --- Pronunciation ------------------------------------------------------
    _f(
        "pronunciation.segment.contrast",
        "Sounds that change meaning",
        "Two sounds merged where the contrast carries meaning.",
        SkillDomain.PRONUNCIATION,
        True,
    ),
    _f(
        "pronunciation.stress.word",
        "Word stress",
        "Stress on the wrong syllable, which can make a familiar word unrecognisable.",
        SkillDomain.PRONUNCIATION,
        True,
    ),
)

FEATURES: dict[str, Feature] = {feature.code: feature for feature in _ALL}


def is_known(code: str) -> bool:
    return code in FEATURES


def get(code: str) -> Feature | None:
    return FEATURES.get(code)


def require(code: str) -> Feature:
    """Look up a feature, failing loudly. For validated curriculum source."""
    feature = FEATURES.get(code)
    if feature is None:
        raise KeyError(f"unknown feature code: {code}")
    return feature


def codes() -> tuple[str, ...]:
    return tuple(sorted(FEATURES))


def label_for(code: str) -> str:
    """A display label for any error code, including legacy ones.

    Never raises. The error log has to render whatever is stored in it, and a
    row that predates the taxonomy is still a row the learner should see.
    """
    feature = FEATURES.get(code)
    if feature is not None:
        return feature.label
    if code.startswith(LEGACY_PREFIX):
        return code.removeprefix(LEGACY_PREFIX).replace(".", " · ")
    return code


def describe(code: str) -> str:
    """A learner-facing description for any error code. Never raises."""
    feature = FEATURES.get(code)
    if feature is not None:
        return feature.description
    return "Recorded before this error could be named precisely."


def blocks_meaning_default(code: str) -> bool:
    """Whether an error of this kind usually costs the reader the message."""
    feature = FEATURES.get(code)
    return feature.typically_blocks_meaning if feature is not None else False


def is_legacy(code: str) -> bool:
    return code.startswith(LEGACY_PREFIX) and code not in FEATURES


__all__ = [
    "FEATURES",
    "LEGACY_PREFIX",
    "TAXONOMY_VERSION",
    "Feature",
    "blocks_meaning_default",
    "codes",
    "describe",
    "get",
    "is_known",
    "is_legacy",
    "label_for",
    "require",
]
