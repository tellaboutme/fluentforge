"""Parse and validate the four progression maps and the learner tracks.

`curriculum/functions/`, `curriculum/grammar/`, `curriculum/pronunciation/`
and `curriculum/tracks/` have been in the repository since the beginning and
until now nothing read them. They were hashed into every curriculum version,
so a change to them minted a new version and made the old one immutable —
while `make test-curriculum` reported the curriculum valid without having
looked at a single line of them.

That is the worst arrangement available: the files carry the authority of
versioned curriculum source and none of the checking. Anything could be in
them. This module reads them.

What it enforces, and why each one is a real failure rather than tidiness:

**Levels are the CEFR levels, all six, in order.** A map that skips B1 is a
progression with a hole in it, and the hole is invisible until someone plans
a syllabus around it.

**No item repeats within a strand.** An item listed at both B1 and C1 is
either a copy-paste slip or a claim that the same thing is learned twice, and
the two are indistinguishable from the file.

**Nothing is empty.** An empty level in a strand says "there is nothing to
learn here", which is never true and is always a truncated edit.

**Every track names levels that exist, and scenarios that are distinct.** A
track is what a learner picks; one with a duplicated scenario shows them the
same thing twice and looks like a bug in the product.

**The pronunciation policy keeps its three commitments.** `docs/PRODUCT_SPEC.md`
and the speaking lab both rest on not scoring accent identity, and a policy
file that can be edited to say otherwise without anything failing is not a
policy. This is the one check here that guards a promise to learners rather
than the integrity of a data file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..models.enums import CefrLevel
from .parser import CurriculumError

FUNCTIONS_PATH = Path("functions") / "communication-functions.yml"
GRAMMAR_PATH = Path("grammar") / "grammar-map.yml"
PRONUNCIATION_PATH = Path("pronunciation") / "map.yml"
TRACKS_DIR = Path("tracks")

#: Commitments the pronunciation policy may not quietly drop. Each is load
#: bearing somewhere else in the product: the speaking lab refuses to
#: evidence pronunciation from a transcript for the same reasons.
REQUIRED_POLICY: dict[str, bool] = {
    "target_native_accent": False,
    "score_accent_identity": False,
    "require_contextual_intelligibility": True,
}

#: A track with fewer scenarios than this is a name, not a track.
MIN_SCENARIOS = 3


@dataclass(frozen=True)
class LevelledMap:
    """A progression: strands, each with an ordered list per CEFR level."""

    name: str
    strands: dict[str, dict[CefrLevel, tuple[str, ...]]]

    @property
    def item_count(self) -> int:
        return sum(len(items) for levels in self.strands.values() for items in levels.values())

    def at(self, level: CefrLevel) -> tuple[str, ...]:
        """Everything introduced at one level, across every strand."""
        return tuple(item for levels in self.strands.values() for item in levels.get(level, ()))


@dataclass(frozen=True)
class Track:
    """A themed route through the curriculum that a learner can choose."""

    key: str
    name: str
    levels: tuple[CefrLevel, ...]
    scenarios: tuple[str, ...]
    priority_domains: tuple[str, ...]


@dataclass(frozen=True)
class ParsedMaps:
    functions: LevelledMap
    grammar: LevelledMap
    pronunciation_strands: dict[str, tuple[str, ...]]
    pronunciation_priorities: tuple[str, ...]
    tracks: tuple[Track, ...]


def _read(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"{path.name}: not found at {path}")
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errors.append(f"{path.name}: invalid YAML ({exc.__class__.__name__})")
        return {}
    if not isinstance(loaded, dict):
        errors.append(f"{path.name}: expected a mapping at the top level")
        return {}
    return loaded


def _levelled(
    raw: Any,
    where: str,
    errors: list[str],
    *,
    require_all_levels: bool,
) -> dict[CefrLevel, tuple[str, ...]] | None:
    if not isinstance(raw, dict) or not raw:
        errors.append(f"{where} has no levels")
        return None

    out: dict[CefrLevel, tuple[str, ...]] = {}
    for key, value in raw.items():
        try:
            level = CefrLevel(str(key).upper())
        except ValueError:
            errors.append(f"{where} has unknown level {key!r}")
            return None
        if not isinstance(value, list) or not value:
            errors.append(
                f"{where} lists nothing at {level.value}. An empty level says there is "
                f"nothing to learn there, which is always a truncated edit"
            )
            return None
        items = tuple(str(item).strip() for item in value)
        if any(not item for item in items):
            errors.append(f"{where} has an empty item at {level.value}")
            return None
        out[level] = items

    if require_all_levels:
        missing = [level.value for level in CefrLevel if level not in out]
        if missing:
            errors.append(
                f"{where} skips {', '.join(missing)}. A progression with a hole in it is "
                f"invisible until somebody plans a syllabus around it"
            )
            return None

    seen: dict[str, str] = {}
    for level, items in out.items():
        for item in items:
            if item in seen:
                errors.append(
                    f"{where} lists {item!r} at both {seen[item]} and {level.value}. "
                    f"A copy-paste slip and a claim that it is learned twice look "
                    f"identical from here"
                )
                return None
            seen[item] = level.value

    return out


def _parse_map(
    path: Path,
    key: str,
    name: str,
    errors: list[str],
    *,
    strands: bool,
) -> LevelledMap | None:
    document = _read(path, errors)
    if not document:
        return None

    raw = document.get(key)
    if not isinstance(raw, dict) or not raw:
        errors.append(f"{path.name}: no {key}")
        return None

    parsed: dict[str, dict[CefrLevel, tuple[str, ...]]] = {}

    if strands:
        for strand, levels in raw.items():
            where = f"{path.name}: strand {strand!r}"
            result = _levelled(levels, where, errors, require_all_levels=True)
            if result is None:
                return None
            parsed[str(strand)] = result
    else:
        result = _levelled(raw, f"{path.name}: {key}", errors, require_all_levels=True)
        if result is None:
            return None
        parsed["all"] = result

    return LevelledMap(name=name, strands=parsed)


def _parse_pronunciation(
    path: Path, errors: list[str]
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]] | None:
    document = _read(path, errors)
    if not document:
        return None

    raw_strands = document.get("strands")
    if not isinstance(raw_strands, dict) or not raw_strands:
        errors.append(f"{path.name}: no strands")
        return None

    strands: dict[str, tuple[str, ...]] = {}
    for strand, items in raw_strands.items():
        if not isinstance(items, list) or not items:
            errors.append(f"{path.name}: strand {strand!r} lists nothing")
            return None
        strands[str(strand)] = tuple(str(item).strip() for item in items)

    raw_priorities = document.get("priorities")
    if not isinstance(raw_priorities, list) or not raw_priorities:
        errors.append(f"{path.name}: no priorities")
        return None

    policy = document.get("policy")
    if not isinstance(policy, dict):
        errors.append(f"{path.name}: no policy")
        return None

    for setting, expected in REQUIRED_POLICY.items():
        actual = policy.get(setting)
        if actual is not expected:
            errors.append(
                f"{path.name}: policy.{setting} is {actual!r}, and must be {expected!r}. "
                f"This is a promise to learners, not a preference: the speaking lab "
                f"refuses to evidence pronunciation from a transcript for the same reason"
            )

    if errors:
        return None
    return strands, tuple(str(item) for item in raw_priorities)


def _parse_track(path: Path, errors: list[str]) -> Track | None:
    document = _read(path, errors)
    if not document:
        return None

    key = document.get("id")
    if not isinstance(key, str) or not key:
        errors.append(f"{path.name}: no id")
        return None
    if key != path.stem:
        errors.append(f"{path.name}: declares id {key!r} but is named {path.stem!r}")
        return None

    name = document.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{path.name}: no name")
        return None

    raw_levels = document.get("levels")
    if not isinstance(raw_levels, list) or not raw_levels:
        errors.append(f"{path.name}: no levels")
        return None

    levels: list[CefrLevel] = []
    for entry in raw_levels:
        try:
            levels.append(CefrLevel(str(entry).upper()))
        except ValueError:
            errors.append(f"{path.name}: unknown level {entry!r}")
            return None

    ranks = [level.rank for level in levels]
    if ranks != sorted(ranks):
        errors.append(f"{path.name}: levels are out of order")
        return None
    if len(set(ranks)) != len(ranks):
        errors.append(f"{path.name}: lists a level twice")
        return None
    # Contiguous, because a track that runs A2 then C1 has a gap a learner
    # falls into: nothing routes them across it.
    if ranks != list(range(ranks[0], ranks[0] + len(ranks))):
        errors.append(
            f"{path.name}: levels {[level.value for level in levels]} are not contiguous, "
            f"so a learner reaching the end of one band has nowhere to go"
        )
        return None

    raw_scenarios = document.get("scenarios", [])
    if not isinstance(raw_scenarios, list):
        errors.append(f"{path.name}: scenarios must be a list")
        return None
    scenarios = tuple(str(item).strip() for item in raw_scenarios)
    if any(not item for item in scenarios):
        errors.append(f"{path.name}: has an empty scenario")
        return None
    if len(set(scenarios)) != len(scenarios):
        errors.append(f"{path.name}: lists the same scenario twice")
        return None

    raw_domains = document.get("priority_domains", [])
    if not isinstance(raw_domains, list):
        errors.append(f"{path.name}: priority_domains must be a list")
        return None

    # A track is either scenario-led or domain-led. One with neither is a
    # name and a level range, which routes nobody anywhere.
    if len(scenarios) < MIN_SCENARIOS and not raw_domains:
        errors.append(
            f"{path.name}: has neither {MIN_SCENARIOS} scenarios nor any priority "
            f"domains, so nothing about it would change what a learner is offered"
        )
        return None

    return Track(
        key=key,
        name=name.strip(),
        levels=tuple(levels),
        scenarios=scenarios,
        priority_domains=tuple(str(domain) for domain in raw_domains),
    )


def parse_maps(curriculum_dir: Path) -> ParsedMaps:
    """Parse the progression maps and tracks, reporting every problem at once."""
    errors: list[str] = []

    functions = _parse_map(
        curriculum_dir / FUNCTIONS_PATH,
        "functions",
        "communication functions",
        errors,
        strands=False,
    )
    grammar = _parse_map(curriculum_dir / GRAMMAR_PATH, "strands", "grammar", errors, strands=True)
    pronunciation = _parse_pronunciation(curriculum_dir / PRONUNCIATION_PATH, errors)

    tracks_dir = curriculum_dir / TRACKS_DIR
    tracks: list[Track] = []
    if not tracks_dir.is_dir():
        errors.append(f"tracks/: not found at {tracks_dir}")
    else:
        paths = sorted(tracks_dir.glob("*.yml"))
        if not paths:
            errors.append("tracks/: no tracks")
        for path in paths:
            track = _parse_track(path, errors)
            if track is not None:
                tracks.append(track)

    if errors:
        raise CurriculumError(errors)

    assert functions is not None
    assert grammar is not None
    assert pronunciation is not None
    strands, priorities = pronunciation

    return ParsedMaps(
        functions=functions,
        grammar=grammar,
        pronunciation_strands=strands,
        pronunciation_priorities=priorities,
        tracks=tuple(tracks),
    )


__all__ = [
    "MIN_SCENARIOS",
    "REQUIRED_POLICY",
    "LevelledMap",
    "ParsedMaps",
    "Track",
    "parse_maps",
]
