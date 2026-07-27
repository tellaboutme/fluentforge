"""Migrations must produce exactly the schema the models declare.

A drift between `Base.metadata` and the migration chain is the single most
common source of "works locally, breaks in production".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def migrated_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(_alembic_config(database_url), "head")
    return database_url


def test_upgrade_creates_every_model_table(migrated_url: str) -> None:
    from apps.api.app import models  # noqa: F401
    from apps.api.app.db.base import Base

    engine = create_engine(migrated_url)
    try:
        migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()

    assert migrated == set(Base.metadata.tables)


def test_migrations_match_models_with_no_drift(migrated_url: str) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from apps.api.app import models  # noqa: F401
    from apps.api.app.db.base import Base

    engine = create_engine(migrated_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "target_metadata": Base.metadata}
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"models and migrations have drifted: {diff}"


def test_downgrade_to_base_is_clean(migrated_url: str) -> None:
    command.downgrade(_alembic_config(migrated_url), "base")

    engine = create_engine(migrated_url)
    try:
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()

    assert remaining == set()


def test_alembic_ini_does_not_hardcode_a_database_url() -> None:
    """The URL must come from settings so migrations cannot target the wrong database."""
    content = (REPO_ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert not any(line.strip().startswith("sqlalchemy.url") for line in content.splitlines())
