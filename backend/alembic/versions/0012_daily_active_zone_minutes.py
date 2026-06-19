"""Daily Active Zone Minutes total on daily_health.

AZM is a pull-only daily rollup (`active-zone-minutes` -> `activeZoneMinutes` with per-zone
sums). We store the Fitbit-weighted total here; the per-zone breakdown lives in `metrics`.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("daily_health", sa.Column("azm_total", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("daily_health", "azm_total")
