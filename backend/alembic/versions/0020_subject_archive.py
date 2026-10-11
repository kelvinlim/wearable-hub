"""Soft-delete / archive columns on `subjects`.

Adds nullable `archived_at` / `archived_by` so study staff can hide finished
participants from the default Subjects list without destroying health data.
Unarchive clears both columns. Permanent delete stays a separate, superuser-only
action and now requires the subject to be archived first.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column(
        "subjects",
        sa.Column("archived_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_subjects_archived_at", "subjects", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_subjects_archived_at", table_name="subjects")
    op.drop_column("subjects", "archived_by")
    op.drop_column("subjects", "archived_at")
