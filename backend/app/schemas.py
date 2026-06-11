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
    created_at: datetime | None


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
