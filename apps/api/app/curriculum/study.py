"""Parse and validate focused study units.

A study unit is the `study` slot in a session template: a short explanation of
one point, then a handful of practice items on exactly that point. The
explanation stays on screen while the learner practises, which makes this
*scaffolded* work — deliberately so, and the evidence it produces is recorded
at reduced independence to say as much (`apps/api/app/services/activities.py`).

Every practice item names the linguistic feature it exercises
(`apps/api/app/learning/taxonomy.py`), so a wrong answer becomes a specific,
practisable error rather than "something in this skill".

Validation is strict for the same reason the reading library's is: a gap-fill
whose accepted answers do not include its own answer, or an item naming a
feature that does not exist, teaches the learner the system is unreliable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..learning import taxonomy
from ..models.enums import CefrLevel
from .parser import CurriculumError

STUDY_RELATIVE_PATH = Path("content") / "study.yml"

#: How a practice item is answered.
#:
#: ``choice``   — pick one of the given options. Recognition-adjacent, but the
#:                distractors are the feature's real confusions.
#: ``gap_fill`` — type the missing form. Closer to production; graded against
#:                an explicit list of accepted spellings and contractions, so
#:                it stays deterministic and works with AI disabled.
ITEM_TYPES = frozenset({"choice", "gap_fill"})

#: The marker a prompt uses for the gap. Checked so an item cannot silently
#: ship without showing the learner where the answer goes.
GAP_MARKER = "___"


@dataclass(frozen=True)
class StudyItem:
    key: str
    item_type: str
    feature: str
    prompt: str
    options: tuple[str, ...]
    answer: str
    #: Every form accepted as correct, normalised. Always contains `answer`.
    accepted: tuple[str, ...]
    #: Shown after answering, right or wrong. The point of a study unit is the
    #: explanation, not the mark.
    note: str

    def as_prompt(self) -> dict[str, Any]:
        """Client-safe view. Deliberately excludes the answer and the note."""
        return {
            "key": self.key,
            "item_type": self.item_type,
            "feature": self.feature,
            "prompt": self.prompt,
            "options": list(self.options),
        }

    def matches(self, response: str) -> bool:
        return normalise_answer(response) in self.accepted


@dataclass(frozen=True)
class StudyUnit:
    key: str
    cefr_level: CefrLevel
    skill_key: str
    title: str
    #: The teaching text. Markdown-free plain paragraphs: it is rendered as
    #: prose, and a study unit that needs formatting is really two units.
    explanation: str
    examples: tuple[str, ...]
    minutes: int
    items: tuple[StudyItem, ...]

    @property
    def features(self) -> tuple[str, ...]:
        """Every feature this unit gives practice on, in order of appearance."""
        seen: list[str] = []
        for item in self.items:
            if item.feature not in seen:
                seen.append(item.feature)
        return tuple(seen)

    def covers(self, feature_code: str) -> bool:
        return feature_code in self.features

    def as_prompt(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "cefr_level": self.cefr_level.value,
            "skill_key": self.skill_key,
            "title": self.title,
            "explanation": self.explanation,
            "examples": list(self.examples),
            "minutes": self.minutes,
            "items": [item.as_prompt() for item in self.items],
        }


def normalise_answer(text: str) -> str:
    """Fold everything a learner could reasonably vary and we do not grade.

    Case, surrounding space, internal run-on space, and the curly apostrophe.
    Punctuation is *not* stripped: a gap-fill answer is a form, and a stray
    full stop inside one is worth leaving visible to the accepted-forms list
    rather than silently forgiving everywhere.

    U+2019 is written as an escape, not as a literal: the two apostrophes are
    visually identical in source, so a literal here is exactly the confusable
    that `learning/writing.py` also avoids.
    """
    return " ".join(text.replace("\u2019", "'").strip().lower().split())


def parse_study_units(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[StudyUnit, ...]:
    """Parse the study bank, reporting every problem at once."""
    path = curriculum_dir / STUDY_RELATIVE_PATH
    if not path.is_file():
        raise CurriculumError([f"study bank not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_units = document.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        raise CurriculumError([f"{path.name}: no study units"])

    errors: list[str] = []
    units: list[StudyUnit] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_units):
        unit = _parse_unit(raw, index, path.name, known_skill_keys, errors)
        if unit is None:
            continue
        if unit.key in seen:
            errors.append(f"{path.name}: duplicate study unit {unit.key}")
            continue
        seen.add(unit.key)
        units.append(unit)

    if errors:
        raise CurriculumError(errors)

    return tuple(units)


def _parse_unit(
    raw: Any,
    index: int,
    filename: str,
    known_skill_keys: set[str] | None,
    errors: list[str],
) -> StudyUnit | None:
    where = f"{filename}: unit {index}"

    if not isinstance(raw, dict):
        errors.append(f"{where} is not a mapping")
        return None

    key = raw.get("key")
    if not isinstance(key, str) or not key:
        errors.append(f"{where} has no key")
        return None
    where = f"{filename}: {key}"

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

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{where} has no title")
        return None

    explanation = raw.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        errors.append(f"{where} has no explanation")
        return None

    raw_examples = raw.get("examples", [])
    if not isinstance(raw_examples, list) or not raw_examples:
        errors.append(f"{where} needs at least one example")
        return None
    examples = tuple(str(example).strip() for example in raw_examples)

    minutes = raw.get("minutes", 8)
    if not isinstance(minutes, int) or minutes < 1:
        errors.append(f"{where} has invalid minutes {minutes!r}")
        return None

    raw_items = raw.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        errors.append(f"{where} has no practice items")
        return None

    items: list[StudyItem] = []
    item_keys: set[str] = set()
    for position, raw_item in enumerate(raw_items):
        item = _parse_item(raw_item, position, where, errors)
        if item is None:
            continue
        if item.key in item_keys:
            errors.append(f"{where} has duplicate item key {item.key}")
            continue
        item_keys.add(item.key)
        items.append(item)

    if not items:
        return None

    return StudyUnit(
        key=key,
        cefr_level=level,
        skill_key=skill_key,
        title=title.strip(),
        explanation=explanation.strip(),
        examples=examples,
        minutes=minutes,
        items=tuple(items),
    )


def _parse_item(raw: Any, position: int, where: str, errors: list[str]) -> StudyItem | None:
    if not isinstance(raw, dict):
        errors.append(f"{where} item {position} is not a mapping")
        return None

    key = raw.get("key")
    if not isinstance(key, str) or not key:
        errors.append(f"{where} item {position} has no key")
        return None

    item_type = str(raw.get("type", "")).strip()
    if item_type not in ITEM_TYPES:
        errors.append(f"{where}/{key} has unknown item type {item_type!r}")
        return None

    feature = raw.get("feature")
    if not isinstance(feature, str) or not taxonomy.is_known(feature):
        errors.append(f"{where}/{key} names unknown feature {feature!r}")
        return None

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{where}/{key} has no prompt")
        return None
    prompt = " ".join(prompt.split())
    if GAP_MARKER not in prompt:
        errors.append(f"{where}/{key} has no {GAP_MARKER} gap in its prompt")
        return None

    answer = raw.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        errors.append(f"{where}/{key} has no answer")
        return None

    note = raw.get("note")
    if not isinstance(note, str) or not note.strip():
        errors.append(f"{where}/{key} has no note explaining the answer")
        return None

    options: tuple[str, ...] = ()
    if item_type == "choice":
        raw_options = raw.get("options")
        if not isinstance(raw_options, list) or len(raw_options) < 2:
            errors.append(f"{where}/{key} needs at least two options")
            return None
        options = tuple(str(option) for option in raw_options)
        if len(set(options)) != len(options):
            errors.append(f"{where}/{key} has duplicate options")
            return None
        if answer not in options:
            errors.append(f"{where}/{key} has an answer that is not among its options")
            return None
    elif raw.get("options") is not None:
        errors.append(f"{where}/{key} is a gap_fill but also lists options")
        return None

    raw_accept = raw.get("accept", [])
    if not isinstance(raw_accept, list):
        errors.append(f"{where}/{key} has a non-list accept")
        return None
    # The answer is always accepted; `accept` only widens it. Listing spelling
    # and contraction variants is how a gap-fill stays fair without needing a
    # model to judge it.
    accepted = tuple(
        sorted({normalise_answer(answer), *(normalise_answer(str(a)) for a in raw_accept)})
    )
    if item_type == "choice" and raw_accept:
        errors.append(f"{where}/{key} is a choice item, so accept does nothing")
        return None

    return StudyItem(
        key=key,
        item_type=item_type,
        feature=feature,
        prompt=prompt,
        options=options,
        answer=answer,
        accepted=accepted,
        note=" ".join(note.split()),
    )


__all__ = [
    "GAP_MARKER",
    "ITEM_TYPES",
    "STUDY_RELATIVE_PATH",
    "StudyItem",
    "StudyUnit",
    "normalise_answer",
    "parse_study_units",
]
