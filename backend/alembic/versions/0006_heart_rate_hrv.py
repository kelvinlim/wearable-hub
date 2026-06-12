"""Daily heart-rate + HRV columns on daily_health.

Heart rate / HRV are NOT webhook-subscribable, but they're pulled during consolidation
(heart-rate via dailyRollUp; resting-HR + HRV via a day-filtered list). Full detail lives in
`daily_health.metrics`; these are the headline typed columns.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("daily_health", sa.Column("hr_avg", sa.Float))
    op.add_column("daily_health", sa.Column("resting_hr", sa.Integer))
    op.add_column("daily_health", sa.Column("hrv_ms", sa.Float))


def downgrade() -> None:
    op.drop_column("daily_health", "hrv_ms")
    op.drop_column("daily_health", "resting_hr")
    op.drop_column("daily_health", "hr_avg")
