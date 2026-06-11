"""Minimal researcher/admin API: create studies, create subjects (entry codes), list status.

UNPROTECTED for Milestone 1. TODO(auth-milestone): gate every route behind Google-login
+ RBAC; scope listings to studies the researcher can access.
"""

import secrets
import string

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ProjectSubscriber, ProviderAccount, Study, Subject
from app.providers import fitbit_gh
from app.schemas import (
    StudyCreate,
    StudyOut,
    SubjectCreate,
    SubjectOut,
    SubjectStatusOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_CODE_ALPHABET = string.ascii_uppercase + string.digits  # unambiguous-ish, uppercase
_CODE_LEN = 8


def _generate_entry_code(db: Session) -> str:
    """Generate a unique entry code. Retries on the (rare) collision."""
    for _ in range(10):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
        if db.scalar(select(Subject).where(Subject.entry_code == code)) is None:
            return code
    raise HTTPException(status_code=500, detail="Could not allocate a unique entry code")


@router.post("/studies", response_model=StudyOut, status_code=201)
def create_study(payload: StudyCreate, db: Session = Depends(get_db)) -> Study:
    study = Study(name=payload.name, description=payload.description)
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


@router.get("/studies", response_model=list[StudyOut])
def list_studies(db: Session = Depends(get_db)) -> list[Study]:
    return list(db.scalars(select(Study).order_by(Study.id)))


@router.post("/studies/{study_id}/subjects", response_model=SubjectOut, status_code=201)
def create_subject(
    study_id: int, payload: SubjectCreate, db: Session = Depends(get_db)
) -> Subject:
    if db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    subject = Subject(
        study_id=study_id,
        subject_label=payload.subject_label,
        entry_code=_generate_entry_code(db),
        status="pending",
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.post("/subscriber", status_code=201)
def ensure_project_subscriber(db: Session = Depends(get_db)) -> dict:
    """Tier-1 (one-time): register the project's webhook subscriber with project credentials.

    Idempotent at the app level — upserts the `project_subscribers` row. Run once after the
    service account is configured. Returns Google's raw response (or surfaces its error) so
    the exact subscriber shape can be confirmed against the live API.
    """
    settings = get_settings()
    raw: dict = {}
    try:
        raw = fitbit_gh.register_subscriber()
    except (fitbit_gh.ProjectCredentialsError, fitbit_gh.InvalidDataTypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        # 409 ALREADY_EXISTS → idempotent no-op: the subscriber is already registered, so
        # fall through and reconcile our DB row from the canonical resource below.
        if exc.response.status_code != 409:
            # Pass Google's status + body straight through for debugging the real API.
            raise HTTPException(
                status_code=502,
                detail={"google_status": exc.response.status_code, "google_body": exc.response.text},
            ) from exc

    # `raw` may be the subscriber resource OR a long-running Operation (async endpoint
    # verification). Don't parse it — re-read the canonical subscriber by its known id.
    resource = fitbit_gh.get_subscriber() or {}
    subscriber_name = resource.get("name")  # full path: projects/{num}/subscribers/{id}
    # Tier-2 create_subscription() interpolates this into the URL after /subscribers/, so it
    # must be the SHORT client id, not the full resource name.
    subscriber_id = settings.gh_subscriber_id

    row = db.scalar(
        select(ProjectSubscriber).where(ProjectSubscriber.project_id == settings.gh_project_id)
    )
    if row is None:
        row = ProjectSubscriber(project_id=settings.gh_project_id)
        db.add(row)
    row.subscriber_id = subscriber_id
    row.subscriber_name = subscriber_name
    row.webhook_url = settings.webhook_public_url
    row.raw_json = resource or raw
    db.commit()
    db.refresh(row)
    return {
        "project_id": row.project_id,
        "subscriber_id": row.subscriber_id,
        "subscriber_name": row.subscriber_name,
        "webhook_url": row.webhook_url,
    }


@router.get("/subscriber")
def get_project_subscriber(db: Session = Depends(get_db)) -> dict:
    """Show the registered project subscriber, if any."""
    settings = get_settings()
    row = db.scalar(
        select(ProjectSubscriber).where(ProjectSubscriber.project_id == settings.gh_project_id)
    )
    if row is None:
        return {"project_id": settings.gh_project_id, "registered": False}
    return {
        "project_id": row.project_id,
        "registered": bool(row.subscriber_id),
        "subscriber_id": row.subscriber_id,
        "subscriber_name": row.subscriber_name,
        "webhook_url": row.webhook_url,
    }


@router.get("/studies/{study_id}/subjects", response_model=list[SubjectStatusOut])
def list_subjects(study_id: int, db: Session = Depends(get_db)) -> list[SubjectStatusOut]:
    if db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    subjects = db.scalars(
        select(Subject).where(Subject.study_id == study_id).order_by(Subject.id)
    )
    out: list[SubjectStatusOut] = []
    for subj in subjects:
        acct = db.scalar(
            select(ProviderAccount).where(
                ProviderAccount.subject_id == subj.id,
                ProviderAccount.provider == fitbit_gh.NAME,
            )
        )
        item = SubjectStatusOut.model_validate(subj)
        item.registered = bool(acct and acct.registered)
        out.append(item)
    return out
