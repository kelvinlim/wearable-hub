"""Daily SpO2 column + paired_devices snapshot table.

SpO2 is NOT webhook-subscribable; it's pulled during consolidation like HRV (daily summary
via a day-filtered `daily-oxygen-saturation` list). `spo2_avg` is the headline typed column;
lower/upper bounds live in `daily_health.metrics`.

Paired devices are profile data (battery, last sync, model), fetched from the HealthProfile
service `GET /users/me/pairedDevices` — there is no dataType/webhook for them. One row per
(account, device); refreshed when consolidating a recent day.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("daily_health", sa.Column("spo2_avg", sa.Float))

    op.create_table(
        "paired_devices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "provider_account_id",
            sa.Integer,
            sa.ForeignKey("provider_accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("device_type", sa.String(32)),
        sa.Column("device_version", sa.String(255)),
        sa.Column("battery_level", sa.Integer),
        sa.Column("battery_status", sa.String(16)),
        sa.Column("last_sync_time", sa.DateTime),
        sa.Column("mac_address", sa.String(64)),
        sa.Column("features", sa.JSON),
        sa.Column("raw_json", sa.JSON),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider_account_id", "device_name", name="uq_paired_acct_device"
        ),
    )


def downgrade() -> None:
    op.drop_table("paired_devices")
    op.drop_column("daily_health", "spo2_avg")
