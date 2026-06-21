"""Pydantic request/response models for the admin and enroll APIs."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


# --- Admin: studies -------------------------------------------------------------

class StudyCreate(BaseModel):
    name: str
    description: str | None = None


class StudyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    ingest_intraday_hr: bool = False
    ingest_intraday_hrv: bool = False
    ingest_intraday_spo2: bool = False
    ingest_intraday_activity: bool = False
    created_at: datetime | None


class StudyUpdate(BaseModel):
    ingest_intraday_hr: bool | None = None
    ingest_intraday_hrv: bool | None = None
    ingest_intraday_spo2: bool | None = None
    ingest_intraday_activity: bool | None = None


# --- Admin: subjects ------------------------------------------------------------

class SubjectCreate(BaseModel):
    subject_label: str | None = None
    participant_id: str | None = None
    collection_start: date | None = None
    collection_end: date | None = None
    # Optional: also create the subject's first device registration (generates its entry code).
    provider: str | None = None  # 'fitbit_gh' | 'garmin'


class SubjectUpdate(BaseModel):
    """PATCH body for a subject. Only fields explicitly present are applied (a present field
    set to null clears that column), so the window bounds can be set, changed, or cleared."""

    subject_label: str | None = None
    participant_id: str | None = None
    collection_start: date | None = None
    collection_end: date | None = None


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_id: int
    subject_label: str | None
    participant_id: str | None = None
    status: str
    collection_start: date | None = None
    collection_end: date | None = None
    created_at: datetime | None


class RegistrationCreate(BaseModel):
    provider: str  # 'fitbit_gh' | 'garmin'


class RegistrationOut(BaseModel):
    """One device registration (provider_account) with its per-device health/freshness summary."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    entry_code: str | None = None
    registered: bool = False
    # Per-device battery + data freshness (computed for the list/detail views).
    battery_level: int | None = None
    battery_status: str | None = None  # High | Medium | Low | Empty
    battery_low: bool = False
    last_data_date: date | None = None
    days_with_data_7: int = 0
    data_stale: bool = False


class SubjectStatusOut(SubjectOut):
    """Subject plus its device registrations and a cross-device health/freshness summary.

    The flat fields are the *most concerning* values across the subject's devices (so the table's
    battery / staleness columns still work); `registrations` carries the per-device detail + codes.
    """

    registered: bool = False  # any device linked
    registrations: list[RegistrationOut] = []
    # Lowest battery across all the subject's paired devices (the most concerning one).
    battery_level: int | None = None
    battery_status: str | None = None  # High | Medium | Low | Empty
    battery_low: bool = False
    # Data freshness/completeness (best across devices).
    last_data_date: date | None = None
    days_with_data_7: int = 0  # days with consolidated data in the last 7 (0–7)
    data_stale: bool = False  # any linked device in-window but no data in the last 2 days


# --- Admin: researchers (users) + study membership ------------------------------

class UserCreate(BaseModel):
    email: str
    name: str | None = None
    is_superuser: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    is_superuser: bool


class MemberCreate(BaseModel):
    email: str
    role: str = "member"  # 'admin' | 'member'


class MemberOut(BaseModel):
    user_id: int
    email: str
    name: str | None
    role: str
