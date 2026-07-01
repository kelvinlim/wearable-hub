"""Link Tier-1 subscribers to their credential set (per-project real-time push, Phase 2).

Adds nullable `project_subscribers.credential_set_id` (null = the global env project) so each GCP
project's subscriber registration is tied to its `google_credential_sets` row.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_subscribers",
        sa.Column(
            "credential_set_id",
            sa.Integer,
            sa.ForeignKey("google_credential_sets.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("project_subscribers", "credential_set_id")
