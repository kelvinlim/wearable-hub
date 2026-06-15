"""Subject participant_id + optional data-collection window.

Adds:
  - subjects.participant_id   — the study's own subject identifier ("Study ID" in the console)
  - subjects.collection_start — inclusive first local day to collect (nullable = unbounded)
  - subjects.collection_end   — inclusive last local day to collect (nullable = unbounded)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("participant_id", sa.String(255), nullable=True))
    op.add_column("subjects", sa.Column("collection_start", sa.Date, nullable=True))
    op.add_column("subjects", sa.Column("collection_end", sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column("subjects", "collection_end")
    op.drop_column("subjects", "collection_start")
    op.drop_column("subjects", "participant_id")
