"""Per-study opt-in flags for raw intraday HRV + SpO2 samples.

Like `ingest_intraday_hr`, these gate pulling the sample-time `heart-rate-variability` /
`oxygen-saturation` dataTypes into `health_data_points`. They're sleep-period, low-frequency
(tens of points/day), so unlike HR they're stored raw without downsampling.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "studies",
        sa.Column("ingest_intraday_hrv", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "studies",
        sa.Column("ingest_intraday_spo2", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("studies", "ingest_intraday_spo2")
    op.drop_column("studies", "ingest_intraday_hrv")
