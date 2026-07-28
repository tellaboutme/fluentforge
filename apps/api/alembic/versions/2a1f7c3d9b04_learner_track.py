"""learner track

The tracks in `curriculum/tracks/` were parsed and validated and nothing
selected one, so a learner had no way to say what they were learning English
*for*. `learner_profiles.track_key` is that choice.

A string rather than an enum on purpose: tracks are versioned curriculum
source, and adding one must be an authoring action rather than a schema
migration.

Revision ID: 2a1f7c3d9b04
Revises: 10810fac474c
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2a1f7c3d9b04"
down_revision: str | None = "10810fac474c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing learners become `general`, which is what they were being
    # planned as. Nothing about their plans changes on deploy.
    #
    # The server default exists only to backfill: the column is NOT NULL and
    # the table already has rows, so there has to be something to put in them.
    # It is dropped immediately afterwards, because the model declares a
    # Python-side default and no server default -- leaving one behind is
    # schema drift, and `alembic check` in CI fails on exactly that.
    op.add_column(
        "learner_profiles",
        sa.Column("track_key", sa.String(length=64), nullable=False, server_default="general"),
    )
    with op.batch_alter_table("learner_profiles") as batch_op:
        batch_op.alter_column("track_key", server_default=None)


def downgrade() -> None:
    op.drop_column("learner_profiles", "track_key")
