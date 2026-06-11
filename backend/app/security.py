"""Researcher session + RBAC helpers.

Session = a Fernet-encrypted, TTL'd cookie holding the user id (reuses FERNET_KEY). Access
model: **superusers** (`users.is_superuser`) can do anything; everyone else is scoped to the
studies they have a `study_memberships` row for, where role 'admin' can manage the study's
subjects + members and 'member' is read-only.

Subject-facing `/enroll` and provider `/webhooks` stay unauthenticated; only `/admin` routes
depend on these.
"""

import json

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import StudyMembership, Subject, User

COOKIE_NAME = "wh_session"
STATE_COOKIE = "wh_oauth_state"


def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_key.encode())


def make_session(user_id: int) -> str:
    return _fernet().encrypt(json.dumps({"uid": user_id}).encode()).decode()


def _read_session(token: str) -> int | None:
    try:
        raw = _fernet().decrypt(token.encode(), ttl=get_settings().session_ttl_seconds)
        return json.loads(raw).get("uid")
    except (InvalidToken, ValueError):
        return None


def cookie_secure() -> bool:
    """Send the cookie over HTTPS only when the configured callback is HTTPS (so localhost works)."""
    return get_settings().researcher_oauth_redirect_uri.lower().startswith("https")


# --- dependencies ---------------------------------------------------------------

def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    uid = _read_session(token)
    return db.get(User, uid) if uid is not None else None


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_superuser(user: User = Depends(get_current_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser only")
    return user


# --- study-scoped checks (called inside endpoints with a path study_id) ---------

def study_role(db: Session, user: User, study_id: int) -> str | None:
    """'super' | 'admin' | 'member' | None for this user on this study."""
    if user.is_superuser:
        return "super"
    m = db.scalar(
        select(StudyMembership).where(
            StudyMembership.user_id == user.id, StudyMembership.study_id == study_id
        )
    )
    return m.role if m else None


def assert_study_view(db: Session, user: User, study_id: int) -> None:
    if study_role(db, user, study_id) is None:
        raise HTTPException(status_code=403, detail="No access to this study")


def assert_study_admin(db: Session, user: User, study_id: int) -> None:
    if study_role(db, user, study_id) not in ("super", "admin"):
        raise HTTPException(status_code=403, detail="Study admin required")


def study_id_for_subject(db: Session, subject_id: int) -> int:
    subj = db.get(Subject, subject_id)
    if subj is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subj.study_id
