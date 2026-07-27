"""Portable column types.

The development database is SQLite and the production database is PostgreSQL
(see `docs/DECISION_LOG.md`). These type decorators keep a single set of models
valid on both without leaking dialect details into the domain layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import CHAR, DateTime, TypeDecorator
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.types import JSON

#: Spelled this way rather than ``datetime.UTC`` so the package imports on
#: Python 3.10 as well as 3.11+ (see `docs/DECISION_LOG.md`).
UTC = timezone.utc


class GUID(TypeDecorator[uuid.UUID]):
    """UUID column: native ``UUID`` on PostgreSQL, ``CHAR(36)`` elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return parsed
        return str(parsed)

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONB(TypeDecorator[Any]):
    """JSON column: ``JSONB`` on PostgreSQL, generic ``JSON`` elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(JSON())


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime normalised to UTC on write and read.

    SQLite discards timezone information, so naive values coming back from the
    database are re-tagged as UTC. Domain code must never see naive datetimes.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected: attach an explicit UTC timezone")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    """Explicit UTC timestamp helper (see coding standards in `CLAUDE.md`)."""
    return datetime.now(UTC)


def enum_column(enum_cls: type[Enum], name: str) -> SAEnum:
    """Portable string-backed enum column.

    ``native_enum=False`` avoids PostgreSQL ENUM types, which require a
    migration for every new member and are unsupported on SQLite.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=lambda members: [str(member.value) for member in members],
        length=64,
    )
