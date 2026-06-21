"""Per-study wearable provider (chosen at creation, immutable).

Each study now declares which provider its subjects use ('fitbit_gh' or 'garmin'). The column is
added with a `server_default` of 'fitbit_gh', which grandfathers every existing study to Fitbit in
one additive, production-safe step. New studies set it explicitly at creation; there is no update
path (immutable).

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studies",
        sa.Column("provider", sa.String(32), nullable=False, server_default="fitbit_gh"),
    )


def downgrade() -> None:
    op.drop_column("studies", "provider")
