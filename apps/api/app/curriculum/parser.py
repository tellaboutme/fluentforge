"""Parse and validate the versioned curriculum source in `curriculum/`.

This module has no database dependency so the validator can run in CI without
infrastructure (`make test-curriculum`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..models.enums import CefrLevel, EvidenceType, SkillDomain

OBJECTIVE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

#: Objective id prefixes map onto the capability domains in `docs/PRODUCT_SPEC.md`.
#: The curriculum uses shorter authoring names than the domain enum.
DOMAIN_PREFIXES: dict[str, SkillDomain] = {
    "listening": SkillDomain.LISTENING,
    "speaking": SkillDomain.SPOKEN_PRODUCTION,
    "interaction": SkillDomain.SPOKEN_INTERACTION,
    "pronunciation": SkillDomain.PRONUNCIATION,
    "reading": SkillDomain.READING,
    "writing": SkillDomain.WRITTEN_PRODUCTION,
    "written_interaction": SkillDomain.WRITTEN_INTERACTION,
    "vocabulary": SkillDomain.VOCABULARY,
    "grammar": SkillDomain.GRAMMAR,
    "fluency": SkillDomain.FLUENCY,
    "discourse": SkillDomain.DISCOURSE,
    "pragmatics": SkillDomain.PRAGMATICS,
    "mediation": SkillDomain.MEDIATION,
    "strategies": SkillDomain.LEARNING_STRATEGIES,
}


class CurriculumError(Exception):
    """Raised when curriculum source data is invalid."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "curriculum validation failed")


@dataclass(frozen=True)
class ParsedObjective:
    key: str
    domain: SkillDomain
    subdomain: str
    level: CefrLevel
    can_do: str
    evidence_types: tuple[EvidenceType, ...]
    min_contexts: int

    @property
    def title(self) -> str:
        return self.subdomain.replace("_", " ").capitalize()


@dataclass(frozen=True)
class ParsedCurriculum:
    semantic_version: str
    source_hash: str
    objectives: tuple[ParsedObjective, ...]
    framework: dict[str, Any] = field(default_factory=dict)

    def by_level(self, level: CefrLevel) -> tuple[ParsedObjective, ...]:
        return tuple(obj for obj in self.objectives if obj.level is level)


def compute_source_hash(curriculum_dir: Path) -> str:
    """Stable hash of every curriculum file.

    Any edit changes the hash, which is how the loader detects an attempt to
    mutate an already-published version.
    """
    digest = hashlib.sha256()
    for path in sorted(curriculum_dir.rglob("*.yml")):
        digest.update(path.relative_to(curriculum_dir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_yaml(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errors.append(f"{path.name}: invalid YAML ({exc.__class__.__name__})")
        return {}
    if not isinstance(loaded, dict):
        errors.append(f"{path.name}: expected a mapping at the top level")
        return {}
    return loaded


def _parse_objective(
    raw: Any, level: CefrLevel, filename: str, errors: list[str]
) -> ParsedObjective | None:
    if not isinstance(raw, dict):
        errors.append(f"{filename}: objective entries must be mappings")
        return None

    key = raw.get("id")
    if not isinstance(key, str) or not OBJECTIVE_ID_PATTERN.match(key):
        errors.append(f"{filename}: invalid objective id {key!r}")
        return None

    prefix = key.split(".", 1)[0]
    domain = DOMAIN_PREFIXES.get(prefix)
    if domain is None:
        errors.append(
            f"{filename}: objective {key} has unknown domain prefix {prefix!r} "
            f"(expected one of {sorted(DOMAIN_PREFIXES)})"
        )
        return None

    can_do = raw.get("can_do")
    if not isinstance(can_do, str) or not can_do.strip():
        errors.append(f"{filename}: objective {key} has no can_do statement")
        return None

    raw_evidence = raw.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        errors.append(f"{filename}: objective {key} has no evidence requirements")
        return None

    evidence: list[EvidenceType] = []
    for item in raw_evidence:
        try:
            evidence.append(EvidenceType(item))
        except ValueError:
            errors.append(f"{filename}: objective {key} has unknown evidence type {item!r}")
    if not evidence:
        return None

    min_contexts = raw.get("min_contexts", 3)
    if not isinstance(min_contexts, int) or min_contexts < 1:
        errors.append(f"{filename}: objective {key} has invalid min_contexts {min_contexts!r}")
        return None

    return ParsedObjective(
        key=key,
        domain=domain,
        subdomain=key.split(".", 1)[1],
        level=level,
        can_do=can_do.strip(),
        evidence_types=tuple(evidence),
        min_contexts=min_contexts,
    )


def parse_curriculum(curriculum_dir: Path) -> ParsedCurriculum:
    """Parse and validate the curriculum tree.

    Raises:
        CurriculumError: with every problem found, not just the first.
    """
    errors: list[str] = []

    if not curriculum_dir.is_dir():
        raise CurriculumError([f"curriculum directory not found: {curriculum_dir}"])

    framework = _read_yaml(curriculum_dir / "framework.yml", errors)
    semantic_version = framework.get("version", "")
    if not isinstance(semantic_version, str) or not SEMVER_PATTERN.match(semantic_version):
        errors.append(f"framework.yml: version must be semantic (got {semantic_version!r})")
        semantic_version = "0.0.0"

    levels_dir = curriculum_dir / "levels"
    expected_levels = {level.value.lower() for level in CefrLevel}
    present_levels = {path.stem.lower() for path in levels_dir.glob("*.yml")}
    for missing in sorted(expected_levels - present_levels):
        errors.append(f"levels/: missing level file {missing}.yml")

    objectives: list[ParsedObjective] = []
    seen: set[str] = set()

    for path in sorted(levels_dir.glob("*.yml")):
        document = _read_yaml(path, errors)
        if not document:
            continue

        try:
            level = CefrLevel(str(document.get("level", "")).upper())
        except ValueError:
            errors.append(f"{path.name}: missing or invalid level {document.get('level')!r}")
            continue

        if level.value.lower() != path.stem.lower():
            errors.append(f"{path.name}: declares level {level.value} but is named {path.stem}")

        raw_objectives = document.get("objectives")
        if not isinstance(raw_objectives, list) or not raw_objectives:
            errors.append(f"{path.name}: no objectives")
            continue

        for raw in raw_objectives:
            parsed = _parse_objective(raw, level, path.name, errors)
            if parsed is None:
                continue
            if parsed.key in seen:
                errors.append(f"{path.name}: duplicate objective id {parsed.key}")
                continue
            seen.add(parsed.key)
            objectives.append(parsed)

    if errors:
        raise CurriculumError(errors)

    return ParsedCurriculum(
        semantic_version=semantic_version,
        source_hash=compute_source_hash(curriculum_dir),
        objectives=tuple(objectives),
        framework=framework,
    )
