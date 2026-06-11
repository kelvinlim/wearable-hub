"""Initial fresh normalized schema.

Revision ID: 0001
Revises:
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("google_sub", sa.String(255), unique=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255)),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "studies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("study_id", sa.Integer, sa.ForeignKey("studies.id"), nullable=False),
        sa.Column("subject_label", sa.String(255)),
        sa.Column("entry_code", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "provider_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("state", sa.String(255)),
        sa.Column("code_verifier", sa.String(255)),
        sa.Column("access_token", sa.Text),
        sa.Column("refresh_token", sa.Text),
        sa.Column("token_expires_at", sa.DateTime),
        sa.Column("scope", sa.Text),
        sa.Column("provider_user_id", sa.String(255)),
        sa.Column("raw_token_json", sa.JSON),
        sa.Column("registered", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_provider_accounts_state", "provider_accounts", ["state"])
    op.create_index(
        "ix_provider_accounts_provider_user_id", "provider_accounts", ["provider_user_id"]
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "provider_account_id",
            sa.Integer,
            sa.ForeignKey("provider_accounts.id"),
            nullable=False,
        ),
        sa.Column("subscriber_id", sa.String(255)),
        sa.Column("provider_subscription_id", sa.String(255)),
        sa.Column("data_types", sa.JSON),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_subscriptions_provider_subscription_id",
        "subscriptions",
        ["provider_subscription_id"],
    )

    op.create_table(
        "health_data",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider_account_id", sa.Integer, sa.ForeignKey("provider_accounts.id")),
        sa.Column("provider", sa.String(32)),
        sa.Column("datatype", sa.String(128)),
        sa.Column("start_time", sa.DateTime),
        sa.Column("payload", sa.JSON),
        sa.Column("received_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_health_data_provider", "health_data", ["provider"])
    op.create_index("ix_health_data_datatype", "health_data", ["datatype"])


def downgrade() -> None:
    op.drop_table("health_data")
    op.drop_table("subscriptions")
    op.drop_table("provider_accounts")
    op.drop_table("subjects")
    op.drop_table("studies")
    op.drop_table("users")
