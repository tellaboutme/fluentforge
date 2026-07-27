"""Alembic environment.

The database URL always comes from application settings so a migration can
never be applied to a different database than the API is using.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from apps.api.app import models  # noqa: F401  (registers tables on Base.metadata)
from apps.api.app.db.base import Base
from apps.api.app.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A caller (tests, tooling) may inject a URL explicitly; otherwise use settings.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.database_url)

DATABASE_URL = config.get_main_option("sqlalchemy.url") or settings.database_url

target_metadata = Base.metadata


_CUSTOM_TYPES = {"GUID", "JSONB", "UTCDateTime"}


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render project type decorators unqualified.

    Autogenerate would otherwise emit ``apps.api.app.db.types.GUID()``, which
    the migration template does not import.
    """
    if type_ == "type" and obj.__class__.__name__ in _CUSTOM_TYPES:
        return f"{obj.__class__.__name__}()"
    return False


def _configure_kwargs() -> dict[str, object]:
    return {
        "target_metadata": target_metadata,
        "render_item": render_item,
        "compare_type": True,
        "compare_server_default": True,
        # SQLite cannot ALTER most columns; batch mode rewrites the table.
        "render_as_batch": DATABASE_URL.startswith("sqlite"),
    }


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, **_configure_kwargs())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
