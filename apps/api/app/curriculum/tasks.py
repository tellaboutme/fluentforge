"""Parse and validate written output tasks.

A writing task is the `output` slot in a session template: a prompt with a
genre, a reader, and a stated purpose, plus the countable requirements its
response is checked against (`apps/api/app/learning/writing.py`).

The requirements live in curriculum source rather than in code because they
are pedagogy, not configuration: how long an A2 email should be, and whether
it must link its ideas, is a decision about the level and belongs beside the
prompt it applies to.

What this deliberately does not encode is a rubric. Deterministic checks can
confirm a learner wrote enough, joined their ideas, and covered the points
asked for; they cannot judge accuracy or register. `target_features` names
what a *rubric evaluator* should look at when one is configured, so the gap is
recorded in the content rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..learning import taxonomy
from ..learning.writing import WritingRequirements
from ..models.enums import CefrLevel
from .parser import CurriculumError

TASKS_RELATIVE_PATH = Path("content") / "writing.yml"

#: Genres a task may declare. Closed so the portfolio can group by genre and
#: the planner can avoid offering the same genre twice in a week.
GENRES = frozenset(
    {
        "message",
        "email",
        "description",
        "narrative",
        "review",
        "report",
        "argument",
        "summary",
        "proposal",
    }
)

#: A task asking for fewer words than this cannot evidence connected writing.
MIN_ALLOWED_WORDS = 20


@dataclass(frozen=True)
class WritingTask:
    key: str
    cefr_level: CefrLevel
    skill_key: str
    title: str
    genre: str
    #: The task itself, as the learner reads it.
    prompt: str
    #: Concrete things to do. Not a rubric — a checklist before writing.
    guidance: tuple[str, ...]
    minutes: int
    requirements: WritingRequirements
    #: What a rubric evaluator should attend to. Empty until one exists.
    target_features: tuple[str, ...]

    def as_prompt(self) -> dict[str, Any]:
        """Client-safe view. Nothing here is secret — a writing task has no
        answer to withhold — but the shape is stated explicitly so a future
        field cannot leak by accident."""
        return {
            "key": self.key,
            "cefr_level": self.cefr_level.value,
            "skill_key": self.skill_key,
            "title": self.title,
            "genre": self.genre,
            "prompt": self.prompt,
            "guidance": list(self.guidance),
            "minutes": self.minutes,
            "min_words": self.requirements.min_words,
            "max_words": self.requirements.max_words,
            "min_sentences": self.requirements.min_sentences,
            "required_elements": list(self.requirements.required_elements),
        }


def parse_writing_tasks(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[WritingTask, ...]:
    """Parse the writing task bank, reporting every problem at once."""
    path = curriculum_dir / TASKS_RELATIVE_PATH
    if not path.is_file():
        raise CurriculumError([f"writing task bank not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_tasks = document.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise CurriculumError([f"{path.name}: no writing tasks"])

    errors: list[str] = []
    tasks: list[WritingTask] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_tasks):
        task = _parse_task(raw, index, path.name, known_skill_keys, errors)
        if task is None:
            continue
        if task.key in seen:
            errors.append(f"{path.name}: duplicate writing task {task.key}")
            continue
        seen.add(task.key)
        tasks.append(task)

    if errors:
        raise CurriculumError(errors)

    return tuple(tasks)


def _parse_task(
    raw: Any,
    index: int,
    filename: str,
    known_skill_keys: set[str] | None,
    errors: list[str],
) -> WritingTask | None:
    where = f"{filename}: task {index}"

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

    genre = str(raw.get("genre", "")).strip()
    if genre not in GENRES:
        errors.append(f"{where} has unknown genre {genre!r}")
        return None

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{where} has no prompt")
        return None

    raw_guidance = raw.get("guidance", [])
    if not isinstance(raw_guidance, list) or not raw_guidance:
        errors.append(f"{where} needs at least one guidance point")
        return None
    guidance = tuple(" ".join(str(point).split()) for point in raw_guidance)

    minutes = raw.get("minutes", 10)
    if not isinstance(minutes, int) or minutes < 1:
        errors.append(f"{where} has invalid minutes {minutes!r}")
        return None

    requirements = _parse_requirements(raw, where, errors)
    if requirements is None:
        return None

    # A required element the task never mentions is a trap: the learner is
    # marked down for a word nobody asked them to use. `analyse` matches
    # required elements as literal substrings, so fairness has to be enforced
    # here, where the prompt and the requirement sit side by side.
    stated = f"{prompt} {' '.join(guidance)}".lower()
    unstated = [element for element in requirements.required_elements if element not in stated]
    if unstated:
        errors.append(
            f"{where} requires wording its prompt and guidance never use: "
            f"{', '.join(sorted(unstated))}"
        )
        return None

    raw_features = raw.get("target_features", [])
    if not isinstance(raw_features, list):
        errors.append(f"{where} has a non-list target_features")
        return None
    features = tuple(str(code) for code in raw_features)
    unknown = [code for code in features if not taxonomy.is_known(code)]
    if unknown:
        errors.append(f"{where} names unknown target features: {', '.join(sorted(unknown))}")
        return None

    return WritingTask(
        key=key,
        cefr_level=level,
        skill_key=skill_key,
        title=title.strip(),
        genre=genre,
        prompt=prompt.strip(),
        guidance=guidance,
        minutes=minutes,
        requirements=requirements,
        target_features=features,
    )


def _parse_requirements(
    raw: dict[str, Any], where: str, errors: list[str]
) -> WritingRequirements | None:
    min_words = raw.get("min_words", 40)
    max_words = raw.get("max_words", 400)
    min_sentences = raw.get("min_sentences", 2)
    min_connectives = raw.get("min_connectives", 1)

    for name, value in (
        ("min_words", min_words),
        ("max_words", max_words),
        ("min_sentences", min_sentences),
        ("min_connectives", min_connectives),
    ):
        if not isinstance(value, int) or value < 0:
            errors.append(f"{where} has invalid {name} {value!r}")
            return None

    assert isinstance(min_words, int) and isinstance(max_words, int)
    assert isinstance(min_sentences, int) and isinstance(min_connectives, int)

    if min_words < MIN_ALLOWED_WORDS:
        errors.append(f"{where} asks for fewer than {MIN_ALLOWED_WORDS} words")
        return None
    if max_words <= min_words:
        errors.append(f"{where} has max_words at or below min_words")
        return None

    raw_elements = raw.get("required_elements", [])
    if not isinstance(raw_elements, list):
        errors.append(f"{where} has a non-list required_elements")
        return None
    # Lowercased here rather than at check time: `analyse` matches against
    # normalised text, and a capitalised requirement would never match.
    elements = tuple(str(element).strip().lower() for element in raw_elements)
    if any(not element for element in elements):
        errors.append(f"{where} has an empty required element")
        return None

    return WritingRequirements(
        min_words=min_words,
        max_words=max_words,
        required_elements=elements,
        min_sentences=min_sentences,
        min_connectives=min_connectives,
    )


__all__ = [
    "GENRES",
    "TASKS_RELATIVE_PATH",
    "WritingTask",
    "parse_writing_tasks",
]
