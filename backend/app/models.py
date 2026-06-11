"""Fresh normalized ORM schema for the wearable hub.

Designed for the full product; Milestone 1 (Fitbit/Google-Health OAuth) exercises
`studies`, `subjects`, `provider_accounts`, `subscriptions`, `health_data`. `users` is
created now but populated later when researcher auth/RBAC lands.

Do NOT reuse the legacy flat `accounts`/`garmindata` tables from `garmin_django`.
Encrypted token columns (`access_token`, `refresh_token`) hold Fernet ciphertext —
see `app/crypto.py`.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    """Researchers / admins. Populated later when Google-login auth lands."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    studies: Mapped[list["Study"]] = relationship(back_populates="created_by")


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    created_by: Mapped["User | None"] = relationship(back_populates="studies")
    subjects: Mapped[list["Subject"]] = relationship(
        back_populates="study", cascade="all, delete-orphan"
    )


class Subject(Base):
    """A research participant. Enrolled by entering a pre-issued `entry_code`."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), nullable=False)
    subject_label: Mapped[str | None] = mapped_column(String(255))
    entry_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    study: Mapped["Study"] = relationship(back_populates="subjects")
    provider_accounts: Mapped[list["ProviderAccount"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )


class ProviderAccount(Base):
    """One row per subject+provider. Holds OAuth state and encrypted tokens.

    `state` keys the OAuth callback lookup (persisted here, NOT in process globals).
    """

    __tablename__ = "provider_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # 'fitbit_gh' | 'garmin'

    # OAuth flow state
    state: Mapped[str | None] = mapped_column(String(255), index=True)
    code_verifier: Mapped[str | None] = mapped_column(String(255))  # PKCE

    # Tokens (Fernet ciphertext for access/refresh)
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    scope: Mapped[str | None] = mapped_column(Text)
    provider_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    raw_token_json: Mapped[dict | None] = mapped_column(JSON)

    registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    subject: Mapped["Subject"] = relationship(back_populates="provider_accounts")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="provider_account", cascade="all, delete-orphan"
    )


class ProjectSubscriber(Base):
    """Tier-1: the project's webhook subscriber, registered once with project credentials.

    One row per project. Persisted so per-user (Tier-2) subscriptions can reference it
    without re-registering. See PLAN.md finding (2026-06-11).
    """

    __tablename__ = "project_subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    subscriber_id: Mapped[str | None] = mapped_column(String(255))
    subscriber_name: Mapped[str | None] = mapped_column(String(512))  # full resource name
    webhook_url: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Subscription(Base):
    """A per-user data subscription (Google Health two-tier subscriber model)."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_account_id: Mapped[int] = mapped_column(
        ForeignKey("provider_accounts.id"), nullable=False
    )
    subscriber_id: Mapped[str | None] = mapped_column(String(255))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255), index=True)
    data_types: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    provider_account: Mapped["ProviderAccount"] = relationship(back_populates="subscriptions")


class HealthData(Base):
    """Raw webhook landing zone. Insert fast, process async/later."""

    __tablename__ = "health_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_account_id: Mapped[int | None] = mapped_column(ForeignKey("provider_accounts.id"))
    provider: Mapped[str | None] = mapped_column(String(32), index=True)
    datatype: Mapped[str | None] = mapped_column(String(128), index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    payload: Mapped[dict | None] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
