"""Per-study opt-in flag for intraday steps/distance.

Gates pulling the listable `steps` / `distance` dataPoints into `health_data_points`,
downsampled to N-minute sum buckets (`STEPS_BUCKET_MINUTES`). Off by default — the daily
totals come from `dailyRollUp` independently, so intraday is only the within-day activity curve.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studies",
        sa.Column("ingest_intraday_activity", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("studies", "ingest_intraday_activity")
