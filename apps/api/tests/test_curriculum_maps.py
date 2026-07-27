"""The progression maps and learner tracks.

These four files have been in the repository since the beginning and until
now nothing read them. They were hashed into every curriculum version — so
editing one minted a new version and froze the old — while
`make test-curriculum` reported the curriculum valid without having looked
at a line of them.

That combination is worse than not having them: they carried the authority
of versioned curriculum source and none of the checking.

The tests split into what the *shipped* files say, and what the parser
refuses. The second group matters more: every failure it catches is one that
would otherwise sit in the repository looking correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.curriculum.maps import (
    MIN_SCENARIOS,
    REQUIRED_POLICY,
    parse_maps,
)
from apps.api.app.curriculum.parser import CurriculumError
from apps.api.app.models.enums import CefrLevel

# --- What ships -------------------------------------------------------------


def test_the_maps_are_valid(curriculum_dir: Path) -> None:
    maps = parse_maps(curriculum_dir)
    assert maps.functions.item_count > 0
    assert maps.grammar.item_count > 0
    assert maps.tracks


def test_every_map_covers_every_level(curriculum_dir: Path) -> None:
    """A progression with a hole in it is invisible until somebody plans a
    syllabus around it."""
    maps = parse_maps(curriculum_dir)
    for level in CefrLevel:
        assert maps.functions.at(level), f"no functions at {level.value}"
        assert maps.grammar.at(level), f"no grammar at {level.value}"


def test_nothing_is_introduced_twice(curriculum_dir: Path) -> None:
    maps = parse_maps(curriculum_dir)
    for levelled in (maps.functions, maps.grammar):
        seen: set[str] = set()
        for levels in levelled.strands.values():
            for items in levels.values():
                for item in items:
                    assert item not in seen, f"{item} appears twice in {levelled.name}"
                    seen.add(item)


def test_the_pronunciation_policy_refuses_to_score_accent(curriculum_dir: Path) -> None:
    """The one check here that guards a promise to learners rather than the
    integrity of a data file. The speaking lab refuses to evidence
    pronunciation from a transcript for the same reason, and a policy file
    that could be edited to say otherwise without anything failing is not a
    policy."""
    parse_maps(curriculum_dir)  # would raise
    assert REQUIRED_POLICY["score_accent_identity"] is False
    assert REQUIRED_POLICY["target_native_accent"] is False


def test_every_track_spans_a_contiguous_range(curriculum_dir: Path) -> None:
    for track in parse_maps(curriculum_dir).tracks:
        ranks = [level.rank for level in track.levels]
        assert ranks == list(range(ranks[0], ranks[0] + len(ranks))), track.key


def test_every_track_would_change_what_a_learner_is_offered(
    curriculum_dir: Path,
) -> None:
    """A track with neither scenarios nor priority domains is a name and a
    level range."""
    for track in parse_maps(curriculum_dir).tracks:
        assert len(track.scenarios) >= MIN_SCENARIOS or track.priority_domains


def test_the_advanced_tracks_start_above_a1(curriculum_dir: Path) -> None:
    """Academic and professional English are not things to learn first. A
    track offering them at A1 would route a beginner into work they cannot
    read."""
    tracks = {track.key: track for track in parse_maps(curriculum_dir).tracks}
    for key in ("academic", "technology-career"):
        assert tracks[key].levels[0].rank > 0, key


# --- What the parser refuses ------------------------------------------------


def _copy(tmp_path: Path, curriculum_dir: Path) -> Path:
    import shutil

    target = tmp_path / "curriculum"
    shutil.copytree(curriculum_dir, target)
    return target


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_a_map_that_skips_a_level_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "functions" / "communication-functions.yml",
        "version: 0.1.0\nfunctions:\n  A1: [greet]\n  A2: [invite]\n  C2: [imply]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("skips" in error for error in exc_info.value.errors)


def test_an_item_listed_at_two_levels_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    """A copy-paste slip and a claim that something is learned twice look
    identical from the file."""
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "functions" / "communication-functions.yml",
        "version: 0.1.0\nfunctions:\n"
        "  A1: [greet]\n  A2: [invite]\n  B1: [compare]\n"
        "  B2: [persuade]\n  C1: [hedge]\n  C2: [greet]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("at both" in error for error in exc_info.value.errors)


def test_an_empty_level_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "functions" / "communication-functions.yml",
        "version: 0.1.0\nfunctions:\n"
        "  A1: [greet]\n  A2: []\n  B1: [compare]\n"
        "  B2: [persuade]\n  C1: [hedge]\n  C2: [imply]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("lists nothing" in error for error in exc_info.value.errors)


def test_scoring_accent_identity_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    """The load-bearing refusal. Everything the speaking lab promises rests
    on this staying false."""
    root = _copy(tmp_path, curriculum_dir)
    path = root / "pronunciation" / "map.yml"
    _write(
        path,
        path.read_text(encoding="utf-8").replace(
            "score_accent_identity: false", "score_accent_identity: true"
        ),
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("score_accent_identity" in error for error in exc_info.value.errors)


def test_targeting_a_native_accent_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    root = _copy(tmp_path, curriculum_dir)
    path = root / "pronunciation" / "map.yml"
    _write(
        path,
        path.read_text(encoding="utf-8").replace(
            "target_native_accent: false", "target_native_accent: true"
        ),
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("target_native_accent" in error for error in exc_info.value.errors)


def test_a_missing_policy_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    """Silence is not consent here. A file with no policy would leave the
    promise unstated and unchecked, which is how it went unchecked for this
    long in the first place."""
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "pronunciation" / "map.yml",
        "version: 0.1.0\npriorities: [intelligibility]\nstrands:\n  segmentals: [contrasts]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("no policy" in error for error in exc_info.value.errors)


def test_a_track_with_a_gap_in_its_levels_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    """A learner reaching the end of one band would have nowhere to go."""
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "tracks" / "academic.yml",
        "id: academic\nname: Academic English\nlevels: [B1, C1, C2]\n"
        "scenarios: [read_and_annotate, summarise_source, build_argument]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("not contiguous" in error for error in exc_info.value.errors)


def test_a_track_that_changes_nothing_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "tracks" / "academic.yml",
        "id: academic\nname: Academic English\nlevels: [B1, B2]\nscenarios: [one]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("would change what a learner is offered" in e for e in exc_info.value.errors) or any(
        "neither" in e for e in exc_info.value.errors
    )


def test_a_duplicated_scenario_is_refused(tmp_path: Path, curriculum_dir: Path) -> None:
    """It would show the learner the same thing twice and read as a bug."""
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "tracks" / "academic.yml",
        "id: academic\nname: Academic English\nlevels: [B1, B2, C1]\n"
        "scenarios: [summarise_source, summarise_source, build_argument]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("same scenario twice" in error for error in exc_info.value.errors)


def test_a_track_whose_id_disagrees_with_its_filename_is_refused(
    tmp_path: Path, curriculum_dir: Path
) -> None:
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "tracks" / "academic.yml",
        "id: scholarly\nname: Academic English\nlevels: [B1, B2, C1]\nscenarios: [a, b, c]\n",
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert any("but is named" in error for error in exc_info.value.errors)


def test_every_problem_is_reported_at_once(tmp_path: Path, curriculum_dir: Path) -> None:
    """A content author fixing these should see the whole list, not one item
    per run."""
    root = _copy(tmp_path, curriculum_dir)
    _write(
        root / "tracks" / "academic.yml",
        "id: wrong\nname: Academic English\nlevels: [B1, B2]\nscenarios: [a]\n",
    )
    path = root / "pronunciation" / "map.yml"
    _write(
        path,
        path.read_text(encoding="utf-8").replace(
            "score_accent_identity: false", "score_accent_identity: true"
        ),
    )
    with pytest.raises(CurriculumError) as exc_info:
        parse_maps(root)
    assert len(exc_info.value.errors) >= 2
