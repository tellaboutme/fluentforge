"""Parse and validate the diagnostic item bank.

Validation is strict and runs in `make test-curriculum`: an item referencing a
skill that does not exist, or a multiple-choice item whose answer is not among
its own options, is a content bug that must never reach a learner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..learning.items import DiagnosticItem, ItemType
from ..learning.writing import WritingRequirements
from ..models.enums import CefrLevel
from .parser import CurriculumError

ITEM_BANK_RELATIVE_PATH = Path("items") / "diagnostic.yml"


def parse_item_bank(
    curriculum_dir: Path, *, known_skill_keys: set[str] | None = None
) -> tuple[DiagnosticItem, ...]:
    """Parse the item bank.

    Args:
        curriculum_dir: root of the curriculum tree.
        known_skill_keys: if given, every item's `skill` must be one of these.

    Raises:
        CurriculumError: with every problem found.
    """
    path = curriculum_dir / ITEM_BANK_RELATIVE_PATH
    errors: list[str] = []

    if not path.is_file():
        raise CurriculumError([f"item bank not found: {path}"])

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CurriculumError([f"{path.name}: invalid YAML ({exc.__class__.__name__})"]) from exc

    if not isinstance(document, dict):
        raise CurriculumError([f"{path.name}: expected a mapping at the top level"])

    raw_items = document.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise CurriculumError([f"{path.name}: no items"])

    items: list[DiagnosticItem] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_items):
        item = _parse_item(raw, index, path.name, known_skill_keys, errors)
        if item is None:
            continue
        if item.key in seen:
            errors.append(f"{path.name}: duplicate item key {item.key}")
            continue
        seen.add(item.key)
        items.append(item)

    if errors:
        raise CurriculumError(errors)

    return tuple(items)


def _parse_item(
    raw: Any,
    index: int,
    filename: str,
    known_skill_keys: set[str] | None,
    errors: list[str],
) -> DiagnosticItem | None:
    where = f"{filename}: item {index}"

    if not isinstance(raw, dict):
        errors.append(f"{where} is not a mapping")
        return None

    key = raw.get("key")
    if not isinstance(key, str) or not key:
        errors.append(f"{where} has no key")
        return None
    where = f"{filename}: {key}"

    try:
        item_type = ItemType(raw.get("type"))
    except ValueError:
        errors.append(f"{where} has unknown type {raw.get('type')!r}")
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

    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{where} has no prompt")
        return None

    options = tuple(str(option) for option in raw.get("options", []) or ())

    requirements: WritingRequirements | None = None

    if item_type is ItemType.SELF_ASSESSMENT:
        # A self-rating has no right answer; the scale is fixed at 0-4.
        answer_key: tuple[str, ...] = ("0", "1", "2", "3", "4")
    elif item_type is ItemType.WRITTEN_RESPONSE:
        # Free writing has no answer key; it has requirements.
        answer_key = ()
        requirements = _parse_requirements(raw, where, errors)
        if requirements is None:
            return None
    else:
        raw_answer = raw.get("answer")
        if not isinstance(raw_answer, list) or not raw_answer:
            errors.append(f"{where} has no answer")
            return None
        answer_key = tuple(str(value) for value in raw_answer)

    if item_type is ItemType.MULTIPLE_CHOICE:
        if len(options) < 2:
            errors.append(f"{where} needs at least two options")
            return None
        if not set(answer_key) <= set(options):
            errors.append(f"{where} has an answer that is not among its options")
            return None
        if len(set(options)) != len(options):
            errors.append(f"{where} has duplicate options")
            return None
    elif options:
        errors.append(f"{where} is {item_type.value} and must not declare options")
        return None

    difficulty = raw.get("difficulty", 0.5)
    if not isinstance(difficulty, int | float) or not 0.0 <= float(difficulty) <= 1.0:
        errors.append(f"{where} has difficulty outside 0..1 ({difficulty!r})")
        return None

    distractors = raw.get("distractors") or {}
    if not isinstance(distractors, dict):
        errors.append(f"{where} has a non-mapping distractors block")
        return None

    return DiagnosticItem(
        key=key,
        item_type=item_type,
        skill_key=skill_key,
        cefr_level=level,
        prompt=" ".join(prompt.split()),
        answer_key=answer_key,
        options=options,
        difficulty=float(difficulty),
        instructions=str(raw.get("instructions", "")).strip(),
        distractor_rationale={str(k): str(v) for k, v in distractors.items()},
        requirements=requirements,
    )


def _parse_requirements(
    raw: dict[str, Any], where: str, errors: list[str]
) -> WritingRequirements | None:
    """Parse a writing prompt's countable requirements."""
    block = raw.get("requirements")
    if block is None:
        block = {}
    if not isinstance(block, dict):
        errors.append(f"{where} has a non-mapping requirements block")
        return None

    min_words = block.get("min_words", 40)
    max_words = block.get("max_words", 400)
    if not isinstance(min_words, int) or not isinstance(max_words, int):
        errors.append(f"{where} has non-integer word bounds")
        return None
    if min_words < 1 or max_words < min_words:
        errors.append(f"{where} has impossible word bounds ({min_words}..{max_words})")
        return None

    raw_elements = block.get("required_elements", []) or []
    if not isinstance(raw_elements, list):
        errors.append(f"{where} has a non-list required_elements")
        return None

    min_sentences = block.get("min_sentences", 2)
    min_connectives = block.get("min_connectives", 1)
    if not isinstance(min_sentences, int) or not isinstance(min_connectives, int):
        errors.append(f"{where} has non-integer sentence or connective minimums")
        return None

    return WritingRequirements(
        min_words=min_words,
        max_words=max_words,
        required_elements=tuple(str(item).lower() for item in raw_elements),
        min_sentences=max(min_sentences, 0),
        min_connectives=max(min_connectives, 0),
    )
