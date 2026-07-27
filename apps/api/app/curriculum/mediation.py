"""Parse and validate multi-source mediation tasks.

A mediation task gives the learner several sources and asks for one account
of them, written for a named reader who has not seen them. It is the
advanced work `docs/ROADMAP.md` Milestone 7 asks for, as opposed to the
harder vocabulary quiz it warns against.

Four invariants are enforced here, each because breaking it produces a task
that looks fine and marks unfairly.

**More than one source.** A single-source task is a summary. Summarising is
already in the writing bank; mediation is what happens when the sources have
to be reconciled.

**Anchors must exist in their own source.** An anchor is checked against the
learner's response as a literal phrase, so a typo in an anchor is a
requirement no learner can ever meet.

**Anchors must be distinctive.** An anchor appearing in two sources proves
nothing about which one was read, and coverage built on it is not coverage.

**The brief must name a reader.** Mediation without an audience is
paraphrase. Who the account is for is what decides which details survive.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..learning import taxonomy
from ..learning.mediation import (
    DEFAULT_MAX_VERBATIM_WORDS,
    MIN_ALLOWED_VERBATIM_WORDS,
    Source,
)
from ..learning.writing import WritingRequirements, count_words, normalise_text
from ..models.enums import CefrLevel
from .parser import CurriculumError

TASKS_RELATIVE_PATH = Path("content") / "mediation.yml"

#: Kinds of source a task may include. Closed so a task can be described as
#: "across three kinds of source" rather than "across three texts", which is
#: the property that makes mediation hard.
SOURCE_KINDS = frozenset(
    {
        "article",
        "email",
        "report_extract",
        "chart_summary",
        "transcript",
        "notice",
        "review",
        "forum_post",
    }
)

#: Fewer sources than this is a summary task, not a mediation task.
MIN_SOURCES = 2

#: Mediation is a B1+ activity. Below that a learner has neither the reading
#: to take in two sources nor the writing to reconcile them, and the CEFR
#: mediation scales start at B1 for the same reason.
MIN_LEVEL_RANK = 2


@dataclass(frozen=True)
class MediationTask:
    key: str
    cefr_level: CefrLevel
    skill_key: str
    title: str
    #: Who the account is for and why they need it. Not decoration: it is what
    #: decides which details from the sources matter.
    brief: str
    sources: tuple[Source, ...]
    guidance: tuple[str, ...]
    minutes: int
    requirements: WritingRequirements
    #: Longest run of words a response may share with a source before it is
    #: reported as copied rather than restated.
    max_verbatim_words: int
    #: What a rubric evaluator should attend to. Empty until one exists.
    target_features: tuple[str, ...]

    @property
    def source_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({source.kind for source in self.sources}))

    @property
    def source_words(self) -> int:
        return sum(count_words(source.text) for source in self.sources)

    def as_prompt(self) -> dict[str, Any]:
        """Client-safe view.

        The source texts **are** sent. They are the material, not an answer
        key: a learner who cannot read them cannot do the task at all. What
        is withheld is `anchors` — publishing the phrases coverage is checked
        against would turn a mediation task into a word hunt.
        """
        return {
            "key": self.key,
            "cefr_level": self.cefr_level.value,
            "skill_key": self.skill_key,
            "title": self.title,
            "brief": self.brief,
            "sources": [
                {
                    "key": source.key,
                    "title": source.title,
                    "kind": source.kind,
                    "text": source.text,
                    "word_count": count_words(source.text),
                }
                for source in self.sources
            ],
            "guidance": list(self.guidance),
            "minutes": self.minutes,
            "min_words": self.requirements.min_words,
            "max_words": self.requirements.max_words,
            "min_sentences": self.requirements.min_sentences,
            "required_elements": list(self.requirements.required_elements),
            "max_verbatim_words": self.max_verbatim_words,
        }


def parse_mediation_tasks(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[MediationTask, ...]:
    """Parse the mediation bank, reporting every problem at once."""
    path = curriculum_dir / TASKS_RELATIVE_PATH
    if not path.is_file():
        raise CurriculumError([f"mediation task bank not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_tasks = document.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise CurriculumError([f"{path.name}: no mediation tasks"])

    errors: list[str] = []
    tasks: list[MediationTask] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_tasks):
        task = _parse_task(raw, index, path.name, known_skill_keys, errors)
        if task is None:
            continue
        if task.key in seen:
            errors.append(f"{path.name}: duplicate mediation task {task.key}")
            continue
        seen.add(task.key)
        tasks.append(task)

    if errors:
        raise CurriculumError(errors)

    return tuple(tasks)


def _parse_sources(raw: Any, where: str, errors: list[str]) -> tuple[Source, ...] | None:
    if not isinstance(raw, list) or len(raw) < MIN_SOURCES:
        errors.append(
            f"{where} needs at least {MIN_SOURCES} sources. One source is a summary task, "
            f"and the writing bank already has those"
        )
        return None

    sources: list[Source] = []
    seen: set[str] = set()

    for index, entry in enumerate(raw):
        place = f"{where} source {index}"
        if not isinstance(entry, dict):
            errors.append(f"{place} is not a mapping")
            return None

        key = entry.get("key")
        if not isinstance(key, str) or not key:
            errors.append(f"{place} has no key")
            return None
        if key in seen:
            errors.append(f"{where} has two sources keyed {key!r}")
            return None
        seen.add(key)

        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{place} has no title")
            return None

        kind = str(entry.get("kind", "")).strip()
        if kind not in SOURCE_KINDS:
            errors.append(
                f"{place} has unknown kind {kind!r} (expected one of {sorted(SOURCE_KINDS)})"
            )
            return None

        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{place} has no text")
            return None

        raw_anchors = entry.get("anchors", [])
        if not isinstance(raw_anchors, list) or not raw_anchors:
            errors.append(
                f"{place} declares no anchors, so nothing can tell whether the learner used it"
            )
            return None
        anchors = tuple(" ".join(str(anchor).split()) for anchor in raw_anchors)
        if any(not anchor for anchor in anchors):
            errors.append(f"{place} has an empty anchor")
            return None

        sources.append(
            Source(
                key=key,
                title=title.strip(),
                kind=kind,
                text=text.strip(),
                anchors=anchors,
            )
        )

    if not _check_anchors(tuple(sources), where, errors):
        return None
    return tuple(sources)


def _check_anchors(sources: tuple[Source, ...], where: str, errors: list[str]) -> bool:
    """Anchors must be present in their own source and absent from the others.

    Both halves matter. An anchor missing from its own source is a
    requirement no learner can meet — a typo becomes a failed check. An
    anchor shared with another source proves nothing about which one was
    read, so coverage built on it is not coverage.
    """
    ok = True
    bodies = {source.key: f" {normalise_text(source.text)} " for source in sources}

    for source in sources:
        for anchor in source.anchors:
            needle = f" {normalise_text(anchor)} "
            if needle not in bodies[source.key]:
                errors.append(
                    f"{where} source {source.key!r} anchors on {anchor!r}, which does not "
                    f"appear in its own text. A learner could never satisfy it"
                )
                ok = False
                continue
            shared = [
                other.key
                for other in sources
                if other.key != source.key and needle in bodies[other.key]
            ]
            if shared:
                errors.append(
                    f"{where} anchor {anchor!r} appears in {source.key!r} and also in "
                    f"{', '.join(sorted(shared))}, so it cannot show which source was used"
                )
                ok = False
    return ok


def _parse_task(
    raw: Any,
    index: int,
    filename: str,
    known_skill_keys: set[str] | None,
    errors: list[str],
) -> MediationTask | None:
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
    if level.rank < MIN_LEVEL_RANK:
        errors.append(
            f"{where} is set at {level.value}. Mediation needs enough reading to take in "
            f"two sources and enough writing to reconcile them; the CEFR scales start at B1"
        )
        return None

    skill_key = raw.get("skill")
    if not isinstance(skill_key, str) or not skill_key:
        errors.append(f"{where} has no skill")
        return None
    if known_skill_keys is not None and skill_key not in known_skill_keys:
        errors.append(f"{where} references unknown skill {skill_key!r}")
        return None
    if not skill_key.startswith("mediation."):
        errors.append(
            f"{where} targets {skill_key!r}. A multi-source account evidences mediation; "
            f"recording it as plain writing would lose exactly what makes the task hard"
        )
        return None

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{where} has no title")
        return None

    brief = raw.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        errors.append(f"{where} has no brief")
        return None
    if not _names_a_reader(brief):
        errors.append(
            f"{where} has a brief that names no reader. Mediation without an audience is "
            f"paraphrase: who the account is for is what decides which details survive"
        )
        return None

    sources = _parse_sources(raw.get("sources"), where, errors)
    if sources is None:
        return None

    raw_guidance = raw.get("guidance", [])
    if not isinstance(raw_guidance, list) or not raw_guidance:
        errors.append(f"{where} needs at least one guidance point")
        return None
    guidance = tuple(" ".join(str(point).split()) for point in raw_guidance)

    minutes = raw.get("minutes", 20)
    if not isinstance(minutes, int) or minutes < 1:
        errors.append(f"{where} has invalid minutes {minutes!r}")
        return None

    requirements = _parse_requirements(raw, where, errors)
    if requirements is None:
        return None

    # The same fairness rule the writing bank enforces: required elements are
    # matched as literal substrings, so requiring wording the task never uses
    # marks a learner down for a word nobody asked for.
    stated = f"{brief} {' '.join(guidance)}".lower()
    unstated = [element for element in requirements.required_elements if element not in stated]
    if unstated:
        errors.append(
            f"{where} requires wording its brief and guidance never use: "
            f"{', '.join(sorted(unstated))}"
        )
        return None

    max_verbatim = raw.get("max_verbatim_words", DEFAULT_MAX_VERBATIM_WORDS)
    if not isinstance(max_verbatim, int) or max_verbatim < MIN_ALLOWED_VERBATIM_WORDS:
        errors.append(
            f"{where} allows a verbatim run of {max_verbatim!r}. Below "
            f"{MIN_ALLOWED_VERBATIM_WORDS} words, ordinary overlap — a name and a date — "
            f"would be reported as copying"
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

    return MediationTask(
        key=key,
        cefr_level=level,
        skill_key=skill_key,
        title=title.strip(),
        brief=brief.strip(),
        sources=sources,
        guidance=guidance,
        minutes=minutes,
        requirements=requirements,
        max_verbatim_words=max_verbatim,
        target_features=features,
    )


#: Words a brief uses when it says who the account is for. Deliberately
#: shallow — the point is to make the author state an audience at all, not to
#: parse English.
_READER_WORDS = (
    " for ",
    " to your ",
    " your colleague",
    " your manager",
    " your team",
    " a colleague",
    " who has not",
    " who have not",
    " reader",
    " audience",
)


def _names_a_reader(brief: str) -> bool:
    return any(word in f" {' '.join(brief.split()).lower()} " for word in _READER_WORDS)


def _parse_requirements(
    raw: dict[str, Any], where: str, errors: list[str]
) -> WritingRequirements | None:
    min_words = raw.get("min_words", 120)
    max_words = raw.get("max_words", 500)
    min_sentences = raw.get("min_sentences", 5)
    min_connectives = raw.get("min_connectives", 2)

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

    if max_words <= min_words:
        errors.append(f"{where} has max_words at or below min_words")
        return None

    raw_elements = raw.get("required_elements", [])
    if not isinstance(raw_elements, list):
        errors.append(f"{where} has a non-list required_elements")
        return None
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
    "MIN_LEVEL_RANK",
    "MIN_SOURCES",
    "SOURCE_KINDS",
    "TASKS_RELATIVE_PATH",
    "MediationTask",
    "parse_mediation_tasks",
]
