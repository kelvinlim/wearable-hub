"""Researcher RBAC: study_memberships (users table already exists from 0001).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_memberships",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("study_id", sa.Integer, sa.ForeignKey("studies.id"), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "study_id", name="uq_membership_user_study"),
    )


def downgrade() -> None:
    op.drop_table("study_memberships")
