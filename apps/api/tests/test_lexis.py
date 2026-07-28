"""The lexical bank, and the check that keeps its examples honest.

An entry's example is the only place a learner sees the item in use. If the
example does not actually contain the item, the learner is shown a sentence,
told it demonstrates a phrase, and the phrase is not in it — which teaches
the wrong thing quietly and is invisible to review, because the sentence
reads perfectly well.

The validator has always had a check for this. It compared the head word as
a *substring*, and this file exists because that was not enough: it accepted

    take responsibility for  →  "She took responsibility for the mistake."

as valid, since "mistake" contains "take". The example does not use the item
at all, and the bank shipped it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.curriculum.lexis import parse_lexis
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.models.enums import CefrLevel, ReviewMode

# --- What ships -------------------------------------------------------------


def test_the_bank_is_valid(curriculum_dir: Path) -> None:
    assert len(parse_lexis(curriculum_dir)) > 0


def test_every_entry_targets_a_real_skill(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    known = {objective.key for objective in curriculum.objectives}
    for entry in parse_lexis(curriculum_dir, known_skill_keys=known):
        assert entry.skill_key in known


def test_every_example_actually_uses_its_item(curriculum_dir: Path) -> None:
    """The property the parser enforces, asserted against what ships rather
    than only against the fixtures below."""
    from apps.api.app.curriculum.lexis import _uses

    for entry in parse_lexis(curriculum_dir):
        head = entry.lemma.split()[0]
        assert _uses(entry.example, head), f"{entry.lemma}: {entry.example}"


def test_the_bank_spans_every_level(curriculum_dir: Path) -> None:
    """A bank that stops at B2 leaves the review queue empty for exactly the
    learners with the most to remember."""
    levels = {entry.cefr_level for entry in parse_lexis(curriculum_dir)}
    assert levels == set(CefrLevel)


def test_it_is_mostly_multiword(curriculum_dir: Path) -> None:
    """`docs/SKILL_MATRIX.md` asks for phrase-first, and the skill graph
    claims vocabulary gates production more tightly than grammar does: a
    learner works around a missing structure and stops dead at a missing
    word. The unit stored is the chunk, not the headword — "make a decision"
    rather than "decision", because the collocation is where errors live."""
    entries = parse_lexis(curriculum_dir)
    multiword = [entry for entry in entries if entry.is_multiword]
    assert len(multiword) > len(entries) / 2


def test_there_is_enough_to_schedule(curriculum_dir: Path) -> None:
    """The bank was 14 entries and 34 cards, which a learner cleared in two
    sittings — a spaced-repetition system with nothing left to space. This is
    a floor on usefulness rather than a target."""
    cards = sum(len(entry.modes) for entry in parse_lexis(curriculum_dir))
    assert cards >= 100


def test_recognition_and_production_are_scheduled_separately(
    curriculum_dir: Path,
) -> None:
    """`CLAUDE.md`: receptive and productive vocabulary are stored
    separately. An entry scheduling only production would claim a learner
    needs to say something they may only ever need to understand."""
    entries = parse_lexis(curriculum_dir)
    assert any(ReviewMode.MEANING_RECOGNITION in entry.modes for entry in entries)
    assert any(ReviewMode.CONTEXTUAL_PRODUCTION in entry.modes for entry in entries)
    for entry in entries:
        assert ReviewMode.MEANING_RECOGNITION in entry.modes, (
            f"{entry.lemma} is scheduled for production or recall without "
            f"recognition ever being established"
        )


# --- The check itself -------------------------------------------------------


def _bank(tmp_path: Path, lemma: str, example: str) -> Path:
    directory = tmp_path / "vocabulary"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "core-lexis.yml").write_text(
        "version: 0.1.0\nentries:\n"
        f"  - lemma: {lemma}\n"
        "    pos: phrase\n"
        "    level: B1\n"
        "    skill: vocabulary.independent_range\n"
        '    meaning: "a meaning"\n'
        f'    example: "{example}"\n'
        "    modes: [meaning_recognition]\n",
        encoding="utf-8",
    )
    return tmp_path


def test_an_example_using_the_item_is_accepted(tmp_path: Path) -> None:
    root = _bank(tmp_path, "put off", "They put off the meeting until Thursday.")
    assert parse_lexis(root)


@pytest.mark.parametrize(
    "example",
    [
        "They put off the meeting.",
        "She puts off every decision.",
        "He put off the call yesterday.",
        "Putting off the choice helped nobody.",
    ],
)
def test_ordinary_inflections_are_accepted(tmp_path: Path, example: str) -> None:
    """English inflects. Requiring the exact citation form would push authors
    towards stilted examples, which is a worse outcome than the one this
    check exists to prevent."""
    assert parse_lexis(_bank(tmp_path, "put off", example))


def test_the_substring_loophole_is_closed(tmp_path: Path) -> None:
    """The defect this file was written for. "mistake" contains "take", so
    the old substring check accepted a sentence that does not use the item.
    It shipped in the bank and nobody noticed, because the sentence reads
    perfectly well."""
    root = _bank(tmp_path, "take responsibility for", "She took responsibility for the mistake.")
    with pytest.raises(CurriculumError) as exc_info:
        parse_lexis(root)
    assert any("does not use the item" in error for error in exc_info.value.errors)


def test_the_failure_says_what_it_looked_for(tmp_path: Path) -> None:
    """ "Does not use the item" leaves an author guessing which word the
    validator wanted, and the answer is not obvious for a multiword entry."""
    root = _bank(tmp_path, "come up with", "She thought of a better plan.")
    with pytest.raises(CurriculumError) as exc_info:
        parse_lexis(root)
    assert any("'come'" in error for error in exc_info.value.errors)


def test_an_unrelated_example_is_refused(tmp_path: Path) -> None:
    root = _bank(tmp_path, "bear in mind", "The weather was cold that week.")
    with pytest.raises(CurriculumError):
        parse_lexis(root)


def test_a_word_hidden_inside_another_is_not_a_use(tmp_path: Path) -> None:
    """The general form of the loophole, not just the one instance of it."""
    root = _bank(tmp_path, "end up", "They were friendly and splendid company.")
    with pytest.raises(CurriculumError):
        parse_lexis(root)
