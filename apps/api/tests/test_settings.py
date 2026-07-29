"""Deployed environments must not inherit development conveniences."""

from __future__ import annotations

import pytest

from apps.api.app.settings import (
    DEVELOPMENT_JWT_SECRET,
    InsecureConfigurationError,
    Settings,
)

REAL_SECRET = "s" * 48
REAL_DATABASE = "postgresql+psycopg://user:pass@db:5432/fluentforge"


def _settings(**overrides: object) -> Settings:
    """A `Settings` built from the declared defaults and nothing else.

    `_env_file=None` matters. Without it these tests read whatever `.env` the
    developer happens to have, so the moment somebody configured a real AI
    provider -- which `docs/TESTING.md` asks them to do -- the assertions
    about defaults started failing. That is a test reaching into the
    environment, not a product defect, and it fails in the most confusing way
    available: a green suite turns red because of a file nobody edited in
    this repository.

    `_env_file` is a pydantic-settings init argument, so it is not part of
    the model's own fields and does not need to be declared.
    """
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type,call-arg]


def test_development_defaults_are_allowed_in_development() -> None:
    """A clean clone must run with no configuration at all."""
    _settings(app_env="development").assert_deployable()


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_default_secret_is_refused_when_deployed(environment: str) -> None:
    with pytest.raises(InsecureConfigurationError, match="JWT_SECRET"):
        _settings(
            app_env=environment,
            jwt_secret=DEVELOPMENT_JWT_SECRET,
            database_url=REAL_DATABASE,
        ).assert_deployable()


def test_short_secret_is_refused_when_deployed() -> None:
    with pytest.raises(InsecureConfigurationError, match="at least"):
        _settings(
            app_env="production", jwt_secret="short", database_url=REAL_DATABASE
        ).assert_deployable()


def test_sqlite_is_refused_when_deployed() -> None:
    with pytest.raises(InsecureConfigurationError, match="SQLite"):
        _settings(
            app_env="production",
            jwt_secret=REAL_SECRET,
            database_url="sqlite+pysqlite:///./local.db",
        ).assert_deployable()


def test_wildcard_origin_is_refused_when_deployed() -> None:
    with pytest.raises(InsecureConfigurationError, match="wildcard"):
        _settings(
            app_env="production",
            jwt_secret=REAL_SECRET,
            database_url=REAL_DATABASE,
            allowed_origins=["*"],
        ).assert_deployable()


def test_every_problem_is_reported_at_once() -> None:
    """One restart should surface the whole list, not the first item."""
    with pytest.raises(InsecureConfigurationError) as exc_info:
        _settings(app_env="production", allowed_origins=["*"]).assert_deployable()

    message = str(exc_info.value)
    assert "JWT_SECRET" in message
    assert "SQLite" in message
    assert "wildcard" in message


def test_properly_configured_production_starts() -> None:
    _settings(
        app_env="production", jwt_secret=REAL_SECRET, database_url=REAL_DATABASE
    ).assert_deployable()


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValueError, match="app_env"):
        _settings(app_env="prod")


def test_ai_and_speech_default_to_disabled() -> None:
    """Core learning must never depend on a paid provider."""
    settings = _settings()
    assert settings.ai_provider == "disabled"
    assert settings.speech_provider == "disabled"
