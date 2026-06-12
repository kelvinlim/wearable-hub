"""Pydantic request/response models for the admin and enroll APIs."""

from datetime import datetime

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
    created_at: datetime | None


class StudyUpdate(BaseModel):
    ingest_intraday_hr: bool | None = None


# --- Admin: subjects ------------------------------------------------------------

class SubjectCreate(BaseModel):
    subject_label: str | None = None


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_id: int
    subject_label: str | None
    entry_code: str
    status: str
    created_at: datetime | None


class SubjectStatusOut(SubjectOut):
    """Subject plus registration status of its Fitbit/Google-Health account."""

    registered: bool = False


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
