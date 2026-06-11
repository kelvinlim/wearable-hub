"""Daily consolidation: health_data_points, daily_health, consolidation_state.

Webhooks carry no values — they trigger pulls from the dataPoints API. Raw pulled points land
in health_data_points; one consolidated row per subject per local day lands in daily_health
(summable metrics from Google's dailyRollUp, sleep aggregated from listed stages);
consolidation_state is the durable dirty-day queue.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_data_points",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider_account_id", sa.Integer, sa.ForeignKey("provider_accounts.id"), nullable=False),
        sa.Column("datatype", sa.String(64), nullable=False, index=True),
        sa.Column("local_date", sa.Date, index=True),
        sa.Column("start_time", sa.DateTime),
        sa.Column("end_time", sa.DateTime),
        sa.Column("tz_offset_seconds", sa.Integer),
        sa.Column("value", sa.Float),
        sa.Column("point_key", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON),
        sa.Column("pulled_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("provider_account_id", "datatype", "point_key", name="uq_hdp_acct_dt_key"),
    )
    op.create_table(
        "daily_health",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider_account_id", sa.Integer, sa.ForeignKey("provider_accounts.id"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id"), index=True),
        sa.Column("local_date", sa.Date, nullable=False, index=True),
        sa.Column("tz_offset_seconds", sa.Integer),
        sa.Column("steps", sa.Integer),
        sa.Column("distance_m", sa.Float),
        sa.Column("calories", sa.Float),
        sa.Column("floors", sa.Integer),
        sa.Column("sleep_minutes", sa.Integer),
        sa.Column("metrics", sa.JSON),
        sa.Column("point_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pulled_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("provider_account_id", "local_date", name="uq_daily_acct_date"),
    )
    op.create_table(
        "consolidation_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider_account_id", sa.Integer, sa.ForeignKey("provider_accounts.id"), nullable=False),
        sa.Column("local_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("requested_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("detail", sa.Text),
        sa.UniqueConstraint("provider_account_id", "local_date", name="uq_consol_acct_date"),
    )


def downgrade() -> None:
    op.drop_table("consolidation_state")
    op.drop_table("daily_health")
    op.drop_table("health_data_points")
