"""Curriculum parsing, loading, and immutability guarantees."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.curriculum import (
    CurriculumError,
    ImmutableCurriculumError,
    compute_source_hash,
    load_curriculum,
    parse_curriculum,
)
from apps.api.app.models.curriculum import CurriculumVersion, SkillEdge, SkillNode
from apps.api.app.models.enums import CefrLevel, CurriculumStatus, SkillDomain, SkillRelation
from apps.api.tests.helpers import CURRICULUM_VERSION

# --- Parser ----------------------------------------------------------------------


def test_repository_curriculum_is_valid(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    assert curriculum.semantic_version == CURRICULUM_VERSION
    assert len(curriculum.objectives) > 0


def test_every_cefr_level_has_objectives(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    for level in CefrLevel:
        assert curriculum.by_level(level), f"{level.value} has no objectives"


def test_objective_ids_are_unique(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    keys = [objective.key for objective in curriculum.objectives]
    assert len(keys) == len(set(keys))


def test_domains_map_onto_the_skill_matrix(curriculum_dir: Path) -> None:
    curriculum = parse_curriculum(curriculum_dir)
    for objective in curriculum.objectives:
        assert isinstance(objective.domain, SkillDomain)


def test_source_hash_changes_when_source_changes(curriculum_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "curriculum"
    shutil.copytree(curriculum_dir, copy)
    original = compute_source_hash(copy)

    target = copy / "levels" / "a1.yml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")

    assert compute_source_hash(copy) != original


def test_missing_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(CurriculumError):
        parse_curriculum(tmp_path / "does-not-exist")


def test_invalid_objective_is_reported(curriculum_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "curriculum"
    shutil.copytree(curriculum_dir, copy)
    (copy / "levels" / "a1.yml").write_text(
        "level: A1\nobjectives:\n  - id: NOT VALID\n    can_do: x\n    evidence: [transfer]\n",
        encoding="utf-8",
    )

    with pytest.raises(CurriculumError) as exc_info:
        parse_curriculum(copy)
    assert any("invalid objective id" in error for error in exc_info.value.errors)


def test_unknown_evidence_type_is_reported(curriculum_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "curriculum"
    shutil.copytree(curriculum_dir, copy)
    (copy / "levels" / "a1.yml").write_text(
        "level: A1\nobjectives:\n  - id: listening.x\n    can_do: x\n    evidence: [vibes]\n",
        encoding="utf-8",
    )

    with pytest.raises(CurriculumError) as exc_info:
        parse_curriculum(copy)
    assert any("unknown evidence type" in error for error in exc_info.value.errors)


def test_all_errors_are_reported_together(curriculum_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "curriculum"
    shutil.copytree(curriculum_dir, copy)
    (copy / "levels" / "a1.yml").write_text(
        "level: A1\nobjectives:\n"
        "  - id: BAD ONE\n    can_do: x\n    evidence: [transfer]\n"
        "  - id: alsobad\n    can_do: x\n    evidence: [transfer]\n",
        encoding="utf-8",
    )

    with pytest.raises(CurriculumError) as exc_info:
        parse_curriculum(copy)
    assert len(exc_info.value.errors) >= 2


# --- Loader ----------------------------------------------------------------------


def test_load_creates_nodes_objectives_and_edges(db_session: Session, curriculum_dir: Path) -> None:
    result = load_curriculum(db_session, curriculum_dir)
    db_session.commit()

    assert result.created is True
    assert result.skill_nodes == result.objectives > 0
    assert result.edges > 0
    assert result.version.status is CurriculumStatus.DRAFT


def test_publish_marks_version_published(db_session: Session, curriculum_dir: Path) -> None:
    result = load_curriculum(db_session, curriculum_dir, publish=True)
    db_session.commit()

    assert result.version.status is CurriculumStatus.PUBLISHED
    assert result.version.published_at is not None
    assert result.version.is_immutable


def test_reload_with_unchanged_source_is_a_no_op(db_session: Session, curriculum_dir: Path) -> None:
    first = load_curriculum(db_session, curriculum_dir, publish=True)
    db_session.commit()
    node_count = len(db_session.execute(select(SkillNode.id)).scalars().all())

    second = load_curriculum(db_session, curriculum_dir, publish=True)
    db_session.commit()

    assert second.created is False
    assert second.version.id == first.version.id
    assert len(db_session.execute(select(SkillNode.id)).scalars().all()) == node_count


def test_modifying_published_source_is_rejected(
    db_session: Session, curriculum_dir: Path, tmp_path: Path
) -> None:
    """Historical curriculum versions must never be silently mutated."""
    copy = tmp_path / "curriculum"
    shutil.copytree(curriculum_dir, copy)

    load_curriculum(db_session, copy, publish=True)
    db_session.commit()

    target = copy / "levels" / "a1.yml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")

    with pytest.raises(ImmutableCurriculumError):
        load_curriculum(db_session, copy)


def test_draft_version_can_be_replaced(
    db_session: Session, curriculum_dir: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "curriculum"
    shutil.copytree(curriculum_dir, copy)

    load_curriculum(db_session, copy)
    db_session.commit()

    target = copy / "levels" / "a1.yml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")

    result = load_curriculum(db_session, copy)
    db_session.commit()

    assert result.created is True
    versions = db_session.execute(select(CurriculumVersion)).scalars().all()
    assert len(versions) == 1


def test_edges_are_loaded_from_the_authored_graph(
    db_session: Session, curriculum_dir: Path
) -> None:
    """Edges used to be derived here — same domain, adjacent level, weight 1.0,
    relation always `prerequisite`. They now come from `curriculum/graph.yml`,
    so the two things that derivation could never produce must be present:
    edges that cross a domain, and edges that do not block.

    The graph's own invariants are tested in `test_skill_graph.py`. This test
    is only about the loader honouring what it was given.
    """
    load_curriculum(db_session, curriculum_dir)
    db_session.commit()

    nodes = {node.id: node for node in db_session.execute(select(SkillNode)).scalars().all()}
    edges = db_session.execute(select(SkillEdge)).scalars().all()
    assert edges

    pairs = [(nodes[edge.from_skill_id], nodes[edge.to_skill_id]) for edge in edges]
    assert any(source.domain is not target.domain for source, target in pairs)
    assert {edge.relation for edge in edges} == {
        SkillRelation.PREREQUISITE,
        SkillRelation.SUPPORTS,
    }
    assert len({edge.weight for edge in edges}) > 1, "weights should vary by claim strength"

    # A prerequisite still may not run downhill, whatever else the graph says.
    for edge in edges:
        source, target = nodes[edge.from_skill_id], nodes[edge.to_skill_id]
        if edge.relation is SkillRelation.PREREQUISITE:
            assert source.cefr_min.rank <= target.cefr_min.rank


def test_difficulty_increases_with_level(db_session: Session, curriculum_dir: Path) -> None:
    load_curriculum(db_session, curriculum_dir)
    db_session.commit()

    nodes = db_session.execute(select(SkillNode)).scalars().all()
    by_level = {node.cefr_min: node.difficulty for node in nodes}
    ordered = [by_level[level] for level in CefrLevel if level in by_level]
    assert ordered == sorted(ordered)
    assert all(0 <= value <= 1 for value in ordered)


# --- API -------------------------------------------------------------------------


def test_curriculum_endpoint_requires_loaded_data(client: TestClient) -> None:
    response = client.get("/api/v1/curriculum")
    assert response.status_code == 503
    assert response.json()["code"] == "curriculum_not_loaded"


def test_curriculum_endpoint_returns_active_version(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/v1/curriculum")
    assert response.status_code == 200
    body = response.json()
    assert body["semantic_version"] == CURRICULUM_VERSION
    assert body["status"] == "published"
    assert body["skill_count"] == len(body["skills"])
    assert body["skills"][0]["can_do"]
