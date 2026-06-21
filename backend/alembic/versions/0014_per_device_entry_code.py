"""Move the enrollment entry_code from subjects to provider_accounts (per-device registration).

A subject may now register more than one device (Fitbit and/or Garmin); each device is a
`provider_accounts` row carrying its own unique `entry_code`. The code previously lived on
`subjects` (one per subject). This migration:

  1. adds `provider_accounts.entry_code` (nullable, unique),
  2. copies every existing `subjects.entry_code` onto that subject's `fitbit_gh` provider_account,
     creating one (registered=0) for subjects that never enrolled, so no code is lost and existing
     Fitbit enrollments keep resolving,
  3. relaxes `subjects.entry_code` to nullable (kept for history; no longer written).

Production-safe / additive: it only adds a column + back-fills; it does not drop data.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("provider_accounts", sa.Column("entry_code", sa.String(64), nullable=True))
    op.create_index(
        "ix_provider_accounts_entry_code", "provider_accounts", ["entry_code"], unique=True
    )

    bind = op.get_bind()
    # Back-fill: copy each subject's code onto its fitbit_gh account, creating one if absent.
    rows = bind.execute(
        sa.text("SELECT id, entry_code FROM subjects WHERE entry_code IS NOT NULL")
    ).fetchall()
    for subject_id, entry_code in rows:
        acct_id = bind.execute(
            sa.text(
                "SELECT id FROM provider_accounts "
                "WHERE subject_id = :sid AND provider = 'fitbit_gh' LIMIT 1"
            ),
            {"sid": subject_id},
        ).scalar()
        if acct_id is not None:
            bind.execute(
                sa.text("UPDATE provider_accounts SET entry_code = :code WHERE id = :id"),
                {"code": entry_code, "id": acct_id},
            )
        else:
            bind.execute(
                sa.text(
                    "INSERT INTO provider_accounts (subject_id, provider, entry_code, registered) "
                    "VALUES (:sid, 'fitbit_gh', :code, 0)"
                ),
                {"sid": subject_id, "code": entry_code},
            )

    op.alter_column("subjects", "entry_code", existing_type=sa.String(64), nullable=True)


def downgrade() -> None:
    op.alter_column("subjects", "entry_code", existing_type=sa.String(64), nullable=False)
    op.drop_index("ix_provider_accounts_entry_code", table_name="provider_accounts")
    op.drop_column("provider_accounts", "entry_code")
