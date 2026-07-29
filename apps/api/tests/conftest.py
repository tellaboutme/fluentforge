"""Shared test fixtures.

Every test runs against a fresh in-memory SQLite database so tests are
order-independent and require no infrastructure.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, StaticPool, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app import models  # noqa: F401  (registers tables)
from apps.api.app.curriculum import load_curriculum
from apps.api.app.db.base import Base
from apps.api.app.db.session import get_session
from apps.api.app.main import create_app
from apps.api.app.security import rate_limit

REPO_ROOT = Path(__file__).resolve().parents[3]
CURRICULUM_DIR = REPO_ROOT / "curriculum"


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> Iterator[None]:
    """Rate limiters are module-level, so they outlive a test.

    Autouse because the alternative is remembering: a test that registers
    six accounts would otherwise fail depending on what ran before it, which
    is the kind of flake that gets a whole suite ignored.
    """
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


@pytest.fixture
def engine() -> Iterator[Engine]:
    # StaticPool keeps one connection so an in-memory database survives
    # across sessions within a single test.
    test_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def _fk_pragma(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(test_engine)
    try:
        yield test_engine
    finally:
        Base.metadata.drop_all(test_engine)
        test_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def curriculum_dir() -> Path:
    return CURRICULUM_DIR


@pytest.fixture
def loaded_curriculum(db_session: Session, curriculum_dir: Path) -> Session:
    load_curriculum(db_session, curriculum_dir, publish=True)
    db_session.commit()
    return db_session


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app()

    def override_get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_client(
    client: TestClient, session_factory: sessionmaker[Session], curriculum_dir: Path
) -> TestClient:
    session = session_factory()
    try:
        load_curriculum(session, curriculum_dir, publish=True)
        session.commit()
    finally:
        session.close()
    return client
