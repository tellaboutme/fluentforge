"""Parse and validate the seed lexical bank.

Phrase-first: an entry may be a single word or a multiword chunk, and the chunk
is often what a learner actually needs. Each entry declares which retrieval
modes are worth scheduling, because recognising a word and producing it are
different memories (`docs/SKILL_MATRIX.md`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..models.enums import CefrLevel, ReviewMode
from .parser import CurriculumError

LEXIS_RELATIVE_PATH = Path("vocabulary") / "core-lexis.yml"

#: Grammatical categories the bank may use. Kept closed so a typo is a build
#: failure rather than a silently unsearchable entry.
KNOWN_POS = frozenset(
    {"noun", "verb", "adjective", "adverb", "phrase", "phrasal_verb", "idiom", "collocation"}
)


@dataclass(frozen=True)
class LexicalEntry:
    key: str
    lemma: str
    pos: str
    cefr_level: CefrLevel
    skill_key: str
    meaning: str
    example: str
    modes: tuple[ReviewMode, ...]

    @property
    def is_multiword(self) -> bool:
        return " " in self.lemma

    def as_card(self, mode: ReviewMode) -> dict[str, Any]:
        """The client-safe shape for one review card.

        The answer is included — a review card has to show it eventually — so
        callers must only send this *after* the learner has committed.
        """
        return {
            "key": self.key,
            "lemma": self.lemma,
            "pos": self.pos,
            "cefr_level": self.cefr_level.value,
            "skill_key": self.skill_key,
            "meaning": self.meaning,
            "example": self.example,
            "review_mode": mode.value,
        }


def parse_lexis(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[LexicalEntry, ...]:
    """Parse the lexical bank, reporting every problem at once."""
    path = curriculum_dir / LEXIS_RELATIVE_PATH
    if not path.is_file():
        raise CurriculumError([f"lexical bank not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CurriculumError([f"{path.name}: no entries"])

    errors: list[str] = []
    entries: list[LexicalEntry] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_entries):
        entry = _parse_entry(raw, index, path.name, known_skill_keys, errors)
        if entry is None:
            continue
        if entry.key in seen:
            errors.append(f"{path.name}: duplicate entry {entry.key}")
            continue
        seen.add(entry.key)
        entries.append(entry)

    if errors:
        raise CurriculumError(errors)

    return tuple(entries)


def _uses(sentence: str, word: str) -> bool:
    """Whether `sentence` contains `word` as a word rather than a fragment.

    Word boundaries, plus the inflections English adds to a head word without
    changing which item is being demonstrated: `put`/`puts`/`putting`,
    `hedge`/`hedges`/`hedged`, `stop`/`stopped`.

    The doubled final consonant is handled explicitly because leaving it out
    rejected "Putting off the choice helped nobody" as an example of `put
    off`, which is a perfectly good example. A validator that refuses correct
    content costs more than one that occasionally accepts careless content:
    the first teaches authors to write stilted citation forms to satisfy it,
    the second lets one weak example through.

    Deliberately shallow, and it stops short in two places. Irregular forms
    are not covered -- "took" will not match `take` -- which is a false
    negative an author fixes by choosing a different example, and arguably
    the better example anyway. And it cannot tell sense apart: an example
    using the head word in an unrelated meaning still passes. Closing that
    needs a lemmatiser and a sense inventory, which is a large dependency for
    one check in a content validator.
    """
    stem = re.escape(word.lower())
    # `put` -> `putting`, `stop` -> `stopped`: the final consonant doubles.
    doubled = re.escape(word[-1].lower() * 2) if word[-1].isalpha() else ""
    endings = ["s", "es", "ed", "d", "ing"]
    if doubled:
        stem_without_last = re.escape(word[:-1].lower())
        alternatives = "|".join(
            [rf"{stem}(?:{'|'.join(endings)})?", rf"{stem_without_last}{doubled}(?:ed|ing)"]
        )
        pattern = rf"\b(?:{alternatives})\b"
    else:
        pattern = rf"\b{stem}(?:{'|'.join(endings)})?\b"
    return re.search(pattern, sentence.lower()) is not None


def _parse_entry(
    raw: Any,
    index: int,
    filename: str,
    known_skill_keys: set[str] | None,
    errors: list[str],
) -> LexicalEntry | None:
    where = f"{filename}: entry {index}"

    if not isinstance(raw, dict):
        errors.append(f"{where} is not a mapping")
        return None

    lemma = raw.get("lemma")
    if not isinstance(lemma, str) or not lemma.strip():
        errors.append(f"{where} has no lemma")
        return None
    where = f"{filename}: {lemma}"

    pos = str(raw.get("pos", "")).strip()
    if pos not in KNOWN_POS:
        errors.append(f"{where} has unknown part of speech {pos!r}")
        return None

    try:
        level = CefrLevel(str(raw.get("level", "")).upper())
    except ValueError:
        errors.append(f"{where} has invalid level {raw.get('level')!r}")
        return None

    skill_key = raw.get("skill")
    if not isinstance(skill_key, str) or not skill_key:
        errors.append(f"{where} has no skill")
        return None
    if known_skill_keys is not None and skill_key not in known_skill_keys:
        errors.append(f"{where} references unknown skill {skill_key!r}")
        return None

    meaning = raw.get("meaning")
    if not isinstance(meaning, str) or not meaning.strip():
        errors.append(f"{where} has no meaning")
        return None

    example = raw.get("example")
    if not isinstance(example, str) or not example.strip():
        errors.append(f"{where} has no example")
        return None
    # An example that does not contain the item teaches the wrong thing: the
    # learner is shown a sentence, told it demonstrates a phrase, and the
    # phrase is not in it.
    #
    # Matched on the head word as a *word*, not as a substring. The substring
    # version passed "She took responsibility for the mistake." as an example
    # of `take responsibility for`, because "mistake" contains "take" -- so
    # the check was satisfied by a sentence that does not use the item at all.
    #
    # The head word rather than the whole phrase, because English inflects:
    # "They put off the meeting" is the right example for `put off`, and
    # requiring the exact string would push authors towards stilted citation
    # forms. That leaves a gap -- an example using the head word in the wrong
    # sense would still pass -- and closing it needs a lemmatiser, which is a
    # dependency this validator does not have and probably should not gain
    # for one check.
    if not _uses(example, lemma.split()[0]):
        errors.append(
            f"{where} has an example that does not use the item "
            f"(looked for the word {lemma.split()[0]!r})"
        )
        return None

    raw_modes = raw.get("modes")
    if not isinstance(raw_modes, list) or not raw_modes:
        errors.append(f"{where} declares no review modes")
        return None

    modes: list[ReviewMode] = []
    for value in raw_modes:
        try:
            modes.append(ReviewMode(value))
        except ValueError:
            errors.append(f"{where} has unknown review mode {value!r}")
    if not modes:
        return None

    return LexicalEntry(
        key=lemma.strip().lower().replace(" ", "_"),
        lemma=lemma.strip(),
        pos=pos,
        cefr_level=level,
        skill_key=skill_key,
        meaning=meaning.strip(),
        example=example.strip(),
        modes=tuple(modes),
    )
