"""Per-study opt-in flag for intraday stress level.

Gates storing the Garmin stress push's `timeOffsetStressLevelValues` into `health_data_points`
(datatype `stress`), downsampled to N-minute average buckets (`STRESS_DOWNSAMPLE_MINUTES`). Off by
default — the daily avg/max stress stay in `daily_health.metrics.stress` regardless, so this is only
the within-day stress curve.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studies",
        sa.Column("ingest_intraday_stress", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("studies", "ingest_intraday_stress")
