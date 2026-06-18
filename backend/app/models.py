"""Fresh normalized ORM schema for the wearable hub.

Designed for the full product; Milestone 1 (Fitbit/Google-Health OAuth) exercises
`studies`, `subjects`, `provider_accounts`, `subscriptions`, `health_data`. `users` is
created now but populated later when researcher auth/RBAC lands.

Do NOT reuse the legacy flat `accounts`/`garmindata` tables from `garmin_django`.
Encrypted token columns (`access_token`, `refresh_token`) hold Fernet ciphertext —
see `app/crypto.py`.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
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


class StudyMembership(Base):
    """Researcher ↔ study access. `role`: 'admin' (manage the study's subjects + members) or
    'member' (read-only). Superusers (`users.is_superuser`) bypass memberships entirely."""

    __tablename__ = "study_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "study_id", name="uq_membership_user_study"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # Opt-in: store downsampled intraday heart-rate for this study's subjects.
    ingest_intraday_hr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Opt-in: store raw intraday HRV / SpO2 samples (sleep-period, low-frequency — not downsampled).
    ingest_intraday_hrv: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ingest_intraday_spo2: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    # `subject_label` is the participant's Google/Fitbit account label; `participant_id` is the
    # study's own subject identifier (shown as "Study ID" in the console).
    subject_label: Mapped[str | None] = mapped_column(String(255))
    participant_id: Mapped[str | None] = mapped_column(String(255))
    entry_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # Optional inclusive data-collection window (subject-local days). When set, pulls are
    # clamped to it across every trigger (real-time webhook, nightly safety-net, on-demand).
    # Either bound may be null = unbounded on that side.
    collection_start: Mapped[date | None] = mapped_column(Date)
    collection_end: Mapped[date | None] = mapped_column(Date)
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
    # Google Health public per-user id (from a subscription's `user` field / webhook
    # payloads). Differs from the OAuth `sub` above; used to link inbound webhook data.
    health_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
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
    # Nullable: a subscription found via sync may not yet be linked to a local account.
    provider_account_id: Mapped[int | None] = mapped_column(ForeignKey("provider_accounts.id"))
    subscriber_id: Mapped[str | None] = mapped_column(String(255))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255), index=True)
    health_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    data_types: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    provider_account: Mapped["ProviderAccount"] = relationship(back_populates="subscriptions")


class HealthDataPoint(Base):
    """One pulled intraday data point (from the dataPoints `list` read).

    Google Health *webhooks carry no values* — they only say which (user, dataType, interval)
    changed. The actual numbers are pulled from the dataPoints API. This is the raw-point
    fidelity layer; the daily roll-up lives in `daily_health`. `point_key` makes re-pulls
    idempotent (dataPoint resource `name` if present, else `{datatype}|{startTime}`).
    """

    __tablename__ = "health_data_points"
    __table_args__ = (
        UniqueConstraint("provider_account_id", "datatype", "point_key", name="uq_hdp_acct_dt_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_account_id: Mapped[int] = mapped_column(
        ForeignKey("provider_accounts.id"), nullable=False
    )
    datatype: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    local_date: Mapped[date | None] = mapped_column(Date, index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime)  # UTC
    end_time: Mapped[datetime | None] = mapped_column(DateTime)  # UTC
    tz_offset_seconds: Mapped[int | None] = mapped_column()
    value: Mapped[float | None] = mapped_column(Float)  # scalar where applicable
    point_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON)  # full raw dataPoint
    pulled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyHealth(Base):
    """One consolidated row per subject per LOCAL day. Hybrid: typed key columns + JSON.

    Summable metrics come from Google's `dailyRollUp` (server-computed daily totals in the
    subject's local timezone); sleep is aggregated from listed stages. Recomputed (upsert) as
    new data for the day arrives, so values self-heal on corrections/deletes.
    """

    __tablename__ = "daily_health"
    __table_args__ = (
        UniqueConstraint("provider_account_id", "local_date", name="uq_daily_acct_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_account_id: Mapped[int] = mapped_column(
        ForeignKey("provider_accounts.id"), nullable=False
    )
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    local_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tz_offset_seconds: Mapped[int | None] = mapped_column()

    # Typed key columns (headline numbers); full per-metric detail lives in `metrics`.
    steps: Mapped[int | None] = mapped_column()
    distance_m: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    floors: Mapped[int | None] = mapped_column()
    sleep_minutes: Mapped[int | None] = mapped_column()
    hr_avg: Mapped[float | None] = mapped_column(Float)  # daily average BPM
    resting_hr: Mapped[int | None] = mapped_column()  # daily resting BPM
    hrv_ms: Mapped[float | None] = mapped_column(Float)  # daily HRV (avg ms)
    spo2_avg: Mapped[float | None] = mapped_column(Float)  # daily avg SpO2 % (typ. during sleep)

    metrics: Mapped[dict | None] = mapped_column(JSON)
    point_count: Mapped[int] = mapped_column(default=0, nullable=False)
    pulled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ConsolidationState(Base):
    """Durable dirty-day queue: which (account, local_date) need (re)consolidation.

    Webhooks mark days `pending`; the background drain / nightly job / on-demand endpoint
    process them. Survives restarts so no day is lost if a background task dies.
    """

    __tablename__ = "consolidation_state"
    __table_args__ = (
        UniqueConstraint("provider_account_id", "local_date", name="uq_consol_acct_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_account_id: Mapped[int] = mapped_column(
        ForeignKey("provider_accounts.id"), nullable=False
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    detail: Mapped[str | None] = mapped_column(Text)


class PairedDevice(Base):
    """Latest-known snapshot of a subject's paired Google Health tracker/scale.

    Profile data, NOT time-series: fetched from `GET /users/me/pairedDevices` (HealthProfile
    service, scope `…/googlehealth.settings.readonly`) — there is no dataType / webhook for it.
    Battery level/status is a "now" value, so the snapshot is refreshed only when consolidating
    a recent day (see `consolidation.refresh_paired_devices`). `device_name` is Google's resource
    name (e.g. `users/me/pairedDevices/123`) and keys the upsert.
    """

    __tablename__ = "paired_devices"
    __table_args__ = (
        UniqueConstraint("provider_account_id", "device_name", name="uq_paired_acct_device"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_account_id: Mapped[int] = mapped_column(
        ForeignKey("provider_accounts.id"), nullable=False, index=True
    )
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)  # Google resource name
    device_type: Mapped[str | None] = mapped_column(String(32))  # TRACKER | SCALE
    device_version: Mapped[str | None] = mapped_column(String(255))  # product name
    battery_level: Mapped[int | None] = mapped_column()  # percentage
    battery_status: Mapped[str | None] = mapped_column(String(16))  # High | Medium | Low | Empty
    last_sync_time: Mapped[datetime | None] = mapped_column(DateTime)  # UTC
    mac_address: Mapped[str | None] = mapped_column(String(64))
    features: Mapped[list | None] = mapped_column(JSON)
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


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
