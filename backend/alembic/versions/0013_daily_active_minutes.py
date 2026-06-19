"""Daily MVPA (active-minutes) on daily_health.

`active-minutes` is a pull-only daily rollup (`activeMinutes.activeMinutesRollupByActivityLevel`
with LIGHT/MODERATE/VIGOROUS sums). We store MVPA (moderate + vigorous) here; the per-level
breakdown lives in `metrics.active_minutes`.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("daily_health", sa.Column("mvpa_minutes", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("daily_health", "mvpa_minutes")
