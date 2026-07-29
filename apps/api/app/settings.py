"""Application settings.

Defaults are chosen so that a clean clone runs with zero external
infrastructure (SQLite, AI disabled). Docker/PostgreSQL is opt-in via `.env`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SQLITE_PATH = REPO_ROOT / "local-data" / "fluentforge.db"

#: Sentinel value. `assert_deployable` rejects it outside development.
DEVELOPMENT_JWT_SECRET = "development-only-secret-replace-in-any-shared-environment"
MIN_PRODUCTION_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    database_url: str = f"sqlite+pysqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
    allowed_origins: list[str] = ["http://localhost:3000"]

    # Authentication
    jwt_secret: str = DEVELOPMENT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=60 * 12, gt=0)
    password_min_length: int = Field(default=10, ge=8)

    # Learning content
    curriculum_dir: Path = REPO_ROOT / "curriculum"

    # Provider abstraction; "disabled" keeps the product fully usable offline.
    ai_provider: str = "disabled"
    #: Required for "cloud" and "compatible", optional for "local". Absent,
    #: the evaluator abstains rather than raising: a missing key must not turn
    #: a learner's submission into a stack trace.
    ai_api_key: str = ""
    ai_model: str = "claude-sonnet-4-5"
    ai_base_url: str = "https://api.anthropic.com"
    speech_provider: str = "disabled"

    #: Whether the auth rate limits apply. On everywhere that matters.
    #:
    #: Turned off only by the Playwright launcher, which registers dozens of
    #: accounts from one address in a few minutes -- precisely the shape the
    #: limiter exists to stop. Leaving it on there would mean the browser
    #: suite spent its time testing the limiter instead of the product, and
    #: the limiter is already covered directly in the API tests.
    auth_rate_limits_enabled: bool = True
    retention_raw_audio_days: int = Field(default=7, ge=0)

    @field_validator("app_env")
    @classmethod
    def _known_env(cls, value: str) -> str:
        allowed = {"development", "test", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"app_env must be one of {sorted(allowed)}")
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def ensure_local_storage(self) -> None:
        """Create the SQLite parent directory when using the default dev database."""
        if self.database_url.startswith("sqlite") and "local-data" in self.database_url:
            DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

    def assert_deployable(self) -> None:
        """Refuse to run a deployed environment with development defaults.

        Convenience defaults are what make a clean clone work offline; they are
        also exactly what gets shipped by accident. Fail loudly at startup
        rather than issuing forgeable tokens.

        Raises:
            InsecureConfigurationError: listing every unsafe setting.
        """
        if self.app_env not in ("production", "staging"):
            return

        problems: list[str] = []
        if self.jwt_secret == DEVELOPMENT_JWT_SECRET:
            problems.append("JWT_SECRET is still the development default")
        if len(self.jwt_secret) < MIN_PRODUCTION_SECRET_LENGTH:
            problems.append(
                f"JWT_SECRET must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters"
            )
        if self.database_url.startswith("sqlite"):
            problems.append("SQLite is not supported outside development; set DATABASE_URL")
        if "*" in self.allowed_origins:
            problems.append("ALLOWED_ORIGINS must not be a wildcard")

        if problems:
            raise InsecureConfigurationError(
                f"Refusing to start in {self.app_env}: "
                + "; ".join(problems)
                + ". Generate a secret with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )


class InsecureConfigurationError(RuntimeError):
    """Raised when a deployed environment is configured with development defaults."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    resolved = Settings()
    resolved.ensure_local_storage()
    resolved.assert_deployable()
    return resolved


settings = get_settings()
