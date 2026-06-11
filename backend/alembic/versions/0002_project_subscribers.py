"""Add project_subscribers (Tier-1 subscriber registry).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_subscribers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, unique=True),
        sa.Column("subscriber_id", sa.String(255)),
        sa.Column("subscriber_name", sa.String(512)),
        sa.Column("webhook_url", sa.Text),
        sa.Column("raw_json", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("project_subscribers")
