"""Add health_user_id for Tier-2 account linking; allow unlinked subscriptions.

The Google Health `healthUserId` (the public per-user id used in subscription `user`
fields and webhook payloads) differs from the OAuth `sub` we store as
`provider_accounts.provider_user_id`, and is not available from the user's token. We
capture it from the auto-created subscription's `user` field (see /admin/subscriptions/sync)
and persist it so webhooks can link data to the right account.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "provider_accounts",
        sa.Column("health_user_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_provider_accounts_health_user_id", "provider_accounts", ["health_user_id"]
    )
    op.add_column(
        "subscriptions",
        sa.Column("health_user_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_subscriptions_health_user_id", "subscriptions", ["health_user_id"])
    # A subscription discovered via sync may not yet be linkable to an account.
    op.alter_column(
        "subscriptions", "provider_account_id", existing_type=sa.Integer(), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "subscriptions", "provider_account_id", existing_type=sa.Integer(), nullable=False
    )
    op.drop_index("ix_subscriptions_health_user_id", table_name="subscriptions")
    op.drop_column("subscriptions", "health_user_id")
    op.drop_index("ix_provider_accounts_health_user_id", table_name="provider_accounts")
    op.drop_column("provider_accounts", "health_user_id")
