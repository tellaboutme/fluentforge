"""Validate the curriculum source tree. Runs with no database or network.

Usage:
    python scripts/validate_curriculum.py [curriculum_dir]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.app.curriculum.content import parse_library
from apps.api.app.curriculum.items import parse_item_bank
from apps.api.app.curriculum.lexis import parse_lexis
from apps.api.app.curriculum.listening import parse_listening
from apps.api.app.curriculum.parser import CurriculumError, parse_curriculum
from apps.api.app.curriculum.study import parse_study_units
from apps.api.app.curriculum.tasks import parse_writing_tasks
from apps.api.app.learning import taxonomy


def main(argv: list[str]) -> int:
    curriculum_dir = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "curriculum"

    try:
        curriculum = parse_curriculum(curriculum_dir)
        # Every item must reference a skill that exists in this same version.
        known = {objective.key for objective in curriculum.objectives}
        items = parse_item_bank(curriculum_dir, known_skill_keys=known)
        entries = parse_lexis(curriculum_dir, known_skill_keys=known)
        texts = parse_library(curriculum_dir, known_skill_keys=known)
        units = parse_study_units(curriculum_dir, known_skill_keys=known)
        tasks = parse_writing_tasks(curriculum_dir, known_skill_keys=known)
        clips = parse_listening(curriculum_dir, known_skill_keys=known)
    except CurriculumError as exc:
        print("Curriculum validation failed:")
        for error in exc.errors:
            print(f"- {error}")
        return 1

    by_level = Counter(objective.level.value for objective in curriculum.objectives)
    by_domain = Counter(objective.domain.value for objective in curriculum.objectives)

    print(
        f"Curriculum validation passed: version {curriculum.semantic_version}, "
        f"{len(curriculum.objectives)} objectives, "
        f"{len(by_domain)} domains, source hash {curriculum.source_hash[:12]}."
    )
    for level, count in sorted(by_level.items()):
        print(f"  {level}: {count} objectives")

    by_item_type = Counter(item.item_type.value for item in items)
    print(f"Item bank: {len(items)} items across {len({i.skill_key for i in items})} skills.")
    for item_type, count in sorted(by_item_type.items()):
        print(f"  {item_type}: {count}")

    cards = sum(len(entry.modes) for entry in entries)
    multiword = sum(1 for entry in entries if entry.is_multiword)
    print(
        f"Lexical bank: {len(entries)} entries ({multiword} multiword), "
        f"{cards} review cards across all modes."
    )

    questions = sum(len(text.questions) for text in texts)
    words = sum(text.word_count for text in texts)
    print(
        f"Reading library: {len(texts)} texts ({words} words), {questions} comprehension questions."
    )

    practice_items = sum(len(unit.items) for unit in units)
    covered = {feature for unit in units for feature in unit.features}
    print(
        f"Study bank: {len(units)} units, {practice_items} practice items, "
        f"{len(covered)} of {len(taxonomy.codes())} features covered."
    )

    clip_questions = sum(len(clip.questions) for clip in clips)
    clip_words = sum(clip.word_count for clip in clips)
    synthesised = sum(1 for clip in clips if clip.is_synthesised)
    print(
        f"Listening library: {len(clips)} clips ({clip_words} words), "
        f"{clip_questions} comprehension questions."
    )
    if synthesised:
        # Not a failure. Synthetic speech under-represents connected speech,
        # so the count is reported rather than left for someone to discover.
        print(f"  {synthesised} of {len(clips)} rely on browser speech synthesis.")

    genres = Counter(task.genre for task in tasks)
    print(f"Writing tasks: {len(tasks)} across {len(genres)} genres.")
    for genre, count in sorted(genres.items()):
        print(f"  {genre}: {count}")

    # A feature nothing practises is a category the error log can name but the
    # plan can never answer. Reported, not fatal: the taxonomy is allowed to
    # run ahead of the content that fills it.
    uncovered = sorted(set(taxonomy.codes()) - covered)
    if uncovered:
        print(f"Note: {len(uncovered)} features have no study unit yet:")
        for code in uncovered:
            print(f"  {code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
