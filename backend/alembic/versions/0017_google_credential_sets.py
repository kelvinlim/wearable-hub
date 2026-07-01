"""Per-study Google credentials via shared credential sets + study PI/IRB metadata.

Creates `google_credential_sets` (each = one GCP project's creds; secrets Fernet-encrypted) and
wires studies/accounts to it: `studies.credential_set_id` (which project a study enrolls under;
null -> global env creds), `provider_accounts.credential_set_id` (the set that ISSUED an account's
token, pinned at enrollment; drives refresh/revoke). Also adds study-level `pi_name` and
`irb_approval_number`.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "google_credential_sets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("oauth_client_id", sa.Text),
        sa.Column("oauth_client_secret", sa.Text),  # Fernet ciphertext
        sa.Column("health_scopes", sa.Text),
        sa.Column("gh_project_id", sa.String(255)),
        sa.Column("gh_project_number", sa.String(255)),
        sa.Column("gh_subscriber_id", sa.String(255)),
        sa.Column("gh_subscription_create_policy", sa.String(32)),
        sa.Column("gh_subscription_data_types", sa.Text),
        sa.Column("sa_json", sa.Text),  # Fernet ciphertext
        sa.Column("webhook_secret", sa.Text),  # Fernet ciphertext
        sa.Column("console_url", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.add_column(
        "studies",
        sa.Column(
            "credential_set_id",
            sa.Integer,
            sa.ForeignKey("google_credential_sets.id"),
            nullable=True,
        ),
    )
    op.add_column("studies", sa.Column("pi_name", sa.String(255), nullable=True))
    op.add_column("studies", sa.Column("irb_approval_number", sa.String(128), nullable=True))
    op.add_column(
        "provider_accounts",
        sa.Column(
            "credential_set_id",
            sa.Integer,
            sa.ForeignKey("google_credential_sets.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_accounts", "credential_set_id")
    op.drop_column("studies", "irb_approval_number")
    op.drop_column("studies", "pi_name")
    op.drop_column("studies", "credential_set_id")
    op.drop_table("google_credential_sets")
