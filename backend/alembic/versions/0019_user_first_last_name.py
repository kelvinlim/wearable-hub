"""Staff-editable first/last name on `users`.

`users.name` is overwritten from the Google ID token on every login, so it can't hold a
researcher-managed name. Adds nullable `first_name`/`last_name` that login never touches,
backfilled by splitting the existing display name on its first space.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(128), nullable=True))

    # Backfill from the Google display name (a handful of rows — a Python loop keeps this
    # portable across MariaDB and the SQLite used in tests).
    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("first_name", sa.String),
        sa.column("last_name", sa.String),
    )
    bind = op.get_bind()
    for uid, name in bind.execute(sa.select(users.c.id, users.c.name)).all():
        full = (name or "").strip()
        if not full:
            continue
        first, _, last = full.partition(" ")
        bind.execute(
            sa.update(users)
            .where(users.c.id == uid)
            .values(first_name=first, last_name=last.strip() or None)
        )


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
