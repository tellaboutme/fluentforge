"""feedback reports

`docs/PRIVACY_SAFETY.md` asks the product to permit reporting bad feedback and
nothing did, so a learner marked wrong by a check that had misread them could
watch the verdict feed their profile with no way to say it was wrong.

One report per attempt, enforced by a unique constraint rather than only in
the service: reporting the same thing five times is one complaint, and letting
it repeat would turn the confidence reduction it causes into a way to zero an
observation out entirely.

Revision ID: 3c4d8e1a2b57
Revises: 2a1f7c3d9b04
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from apps.api.app.db.types import GUID, UTCDateTime

revision: str = "3c4d8e1a2b57"
down_revision: str | None = "2a1f7c3d9b04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_reports",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("attempt_id", GUID(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evaluator_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_feedback_reports_attempt"),
    )
    with op.batch_alter_table("feedback_reports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_feedback_reports_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_feedback_reports_attempt_id"), ["attempt_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("feedback_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_feedback_reports_attempt_id"))
        batch_op.drop_index(batch_op.f("ix_feedback_reports_user_id"))
    op.drop_table("feedback_reports")
