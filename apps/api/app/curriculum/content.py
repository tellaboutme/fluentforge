"""Parse and validate the reading library.

Meaning first: a text is a text, and the questions follow it. Validation is
strict because a comprehension question whose answer is not among its options,
or which asks about something the text never says, teaches the learner that the
system is unreliable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..models.enums import CefrLevel
from .parser import CurriculumError
from .questions import QUESTION_TYPES, Question, parse_questions

LIBRARY_RELATIVE_PATH = Path("content") / "library.yml"


@dataclass(frozen=True)
class LibraryText:
    key: str
    cefr_level: CefrLevel
    skill_key: str
    title: str
    body: str
    minutes: int
    questions: tuple[Question, ...]

    @property
    def word_count(self) -> int:
        return len(self.body.split())

    def as_prompt(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "cefr_level": self.cefr_level.value,
            "skill_key": self.skill_key,
            "title": self.title,
            "body": self.body,
            "minutes": self.minutes,
            "questions": [question.as_prompt() for question in self.questions],
        }


def parse_library(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[LibraryText, ...]:
    """Parse the reading library, reporting every problem at once."""
    path = curriculum_dir / LIBRARY_RELATIVE_PATH
    if not path.is_file():
        raise CurriculumError([f"content library not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_texts = document.get("texts")
    if not isinstance(raw_texts, list) or not raw_texts:
        raise CurriculumError([f"{path.name}: no texts"])

    errors: list[str] = []
    texts: list[LibraryText] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_texts):
        text = _parse_text(raw, index, path.name, known_skill_keys, errors)
        if text is None:
            continue
        if text.key in seen:
            errors.append(f"{path.name}: duplicate text {text.key}")
            continue
        seen.add(text.key)
        texts.append(text)

    if errors:
        raise CurriculumError(errors)

    return tuple(texts)


def _parse_text(
    raw: Any,
    index: int,
    filename: str,
    known_skill_keys: set[str] | None,
    errors: list[str],
) -> LibraryText | None:
    where = f"{filename}: text {index}"

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

    body = raw.get("body")
    if not isinstance(body, str) or not body.strip():
        errors.append(f"{where} has no body")
        return None

    minutes = raw.get("minutes", 5)
    if not isinstance(minutes, int) or minutes < 1:
        errors.append(f"{where} has invalid minutes {minutes!r}")
        return None

    # A text a learner reads for meaning should ask about the meaning
    # first, so the gist requirement is enforced rather than suggested.
    questions = parse_questions(raw.get("questions"), where, errors)
    if questions is None:
        return None

    return LibraryText(
        key=key,
        cefr_level=level,
        skill_key=skill_key,
        title=title.strip(),
        body=body.rstrip(),
        minutes=minutes,
        questions=questions,
    )


#: Re-exported: questions moved to `curriculum/questions.py` when the
#: listening lab began sharing them, and callers should not have to care.
__all__ = [
    "LIBRARY_RELATIVE_PATH",
    "QUESTION_TYPES",
    "LibraryText",
    "Question",
    "parse_library",
]
