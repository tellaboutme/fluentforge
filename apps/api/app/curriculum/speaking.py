"""Parse and validate spoken output tasks.

What a speaking task can and cannot evidence
--------------------------------------------
No audio leaves the browser and no speech provider is required, so what
reaches the server is a **transcript** the browser produced, plus how long
the learner spoke. That supports some real claims and forbids others, and the
line between them is the whole design.

It supports: that the learner produced connected spoken language, at length,
covering the content the task asked for. Those are countable, and they are
the same countable checks writing uses.

It forbids **any claim about pronunciation**. A transcript is normalised text;
it cannot distinguish a learner who said a word clearly from one who said it
badly and was guessed correctly. `prompts/evaluators/speaking.md` states the
rule directly: do not infer pronunciation quality from spelling in a
transcript. So a speaking task records evidence against speaking skills and
never against a `pronunciation.*` skill, and the parser enforces that.

It also forbids using **recognition confidence** as a proxy for anything.
Browser speech recognition is measurably less accurate on non-native and
accented speech — which is this product's entire audience. A low-confidence
transcript may mean unclear speech, or a poor microphone, or a recogniser
trained mostly on native speakers. Those cannot be told apart from here, and
scoring the learner down for the third would be discrimination dressed as
assessment. Confidence is stored for audit and never scored.
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

SPEAKING_RELATIVE_PATH = Path("content") / "speaking.yml"

#: What kind of speaking the task asks for. Closed so the planner can avoid
#: offering the same shape twice in a week.
FORMATS = frozenset({"monologue", "narrative", "description", "opinion", "roleplay", "summary"})

#: Below this a learner has not produced connected speech, only an utterance.
MIN_ALLOWED_SECONDS = 20

#: Skills a spoken task may target. Pronunciation is excluded deliberately:
#: see the module docstring. A task claiming to evidence it would be making a
#: claim its own data cannot support.
ALLOWED_SKILL_PREFIXES = ("speaking.", "interaction.", "fluency.", "mediation.")


@dataclass(frozen=True)
class SpeakingTask:
    key: str
    cefr_level: CefrLevel
    skill_key: str
    title: str
    speaking_format: str
    #: The situation, said plainly. Speaking without a listener in mind is a
    #: recitation, not communication.
    prompt: str
    guidance: tuple[str, ...]
    minutes: int
    #: How long the learner should speak for. The floor is what makes this
    #: connected speech rather than a sentence.
    min_seconds: int
    max_seconds: int
    #: Seconds to think before recording. `docs/LEARNING_SCIENCE.md`: planning
    #: time changes what a speaking task measures, so it is a property of the
    #: task rather than a UI whim.
    preparation_seconds: int
    requirements: WritingRequirements
    #: What a rubric evaluator should judge once one exists for speech.
    target_features: tuple[str, ...]

    def as_prompt(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "cefr_level": self.cefr_level.value,
            "skill_key": self.skill_key,
            "title": self.title,
            "format": self.speaking_format,
            "prompt": self.prompt,
            "guidance": list(self.guidance),
            "minutes": self.minutes,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "preparation_seconds": self.preparation_seconds,
            "min_words": self.requirements.min_words,
            "required_elements": list(self.requirements.required_elements),
        }


def parse_speaking_tasks(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[SpeakingTask, ...]:
    """Parse the speaking bank, reporting every problem at once."""
    path = curriculum_dir / SPEAKING_RELATIVE_PATH
    if not path.is_file():
        raise CurriculumError([f"speaking bank not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_tasks = document.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise CurriculumError([f"{path.name}: no speaking tasks"])

    errors: list[str] = []
    tasks: list[SpeakingTask] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_tasks):
        task = _parse_task(raw, index, path.name, known_skill_keys, errors)
        if task is None:
            continue
        if task.key in seen:
            errors.append(f"{path.name}: duplicate speaking task {task.key}")
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
) -> SpeakingTask | None:
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

    # The rule the whole lab rests on. A transcript cannot evidence
    # pronunciation, so a task may not aim at it however tempting.
    if not skill_key.startswith(ALLOWED_SKILL_PREFIXES):
        errors.append(
            f"{where} targets {skill_key!r}; a transcript cannot evidence that. "
            f"Spoken tasks may target only {', '.join(ALLOWED_SKILL_PREFIXES)}"
        )
        return None

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{where} has no title")
        return None

    speaking_format = str(raw.get("format", "")).strip()
    if speaking_format not in FORMATS:
        errors.append(f"{where} has unknown format {speaking_format!r}")
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

    numbers: dict[str, int] = {}
    for name, default in (
        ("minutes", 8),
        ("min_seconds", 45),
        ("max_seconds", 180),
        ("preparation_seconds", 30),
        ("min_words", 50),
    ):
        value = raw.get(name, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{where} has invalid {name} {value!r}")
            return None
        numbers[name] = value

    if numbers["min_seconds"] < MIN_ALLOWED_SECONDS:
        errors.append(f"{where} asks for under {MIN_ALLOWED_SECONDS} seconds of speech")
        return None
    if numbers["max_seconds"] <= numbers["min_seconds"]:
        errors.append(f"{where} has max_seconds at or below min_seconds")
        return None

    raw_elements = raw.get("required_elements", [])
    if not isinstance(raw_elements, list):
        errors.append(f"{where} has a non-list required_elements")
        return None
    elements = tuple(str(element).strip().lower() for element in raw_elements)
    if any(not element for element in elements):
        errors.append(f"{where} has an empty required element")
        return None

    # Same fairness rule as writing: a required word the task never says is a
    # trap, and worse here because a recogniser may mishear it.
    stated = f"{prompt} {' '.join(guidance)}".lower()
    unstated = [element for element in elements if element not in stated]
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

    return SpeakingTask(
        key=key,
        cefr_level=level,
        skill_key=skill_key,
        title=title.strip(),
        speaking_format=speaking_format,
        prompt=prompt.strip(),
        guidance=guidance,
        minutes=numbers["minutes"],
        min_seconds=numbers["min_seconds"],
        max_seconds=numbers["max_seconds"],
        preparation_seconds=numbers["preparation_seconds"],
        requirements=WritingRequirements(
            min_words=numbers["min_words"],
            # Speech has no upper word bound worth enforcing: a fluent
            # learner talking freely is the goal, not a fault.
            max_words=100_000,
            required_elements=elements,
            # Spoken sentence boundaries are a transcription artefact, not
            # something the learner controls, so this check is neutralised.
            min_sentences=0,
            min_connectives=1,
        ),
        target_features=features,
    )


__all__ = [
    "ALLOWED_SKILL_PREFIXES",
    "FORMATS",
    "MIN_ALLOWED_SECONDS",
    "SPEAKING_RELATIVE_PATH",
    "SpeakingTask",
    "parse_speaking_tasks",
]
