"""Researcher Google-login auth (reuses the project's Google OAuth client).

Flow: GET /auth/login -> Google consent (openid email profile) -> GET /auth/callback ->
verify the id_token -> allowlist check (a `users` row, or a bootstrap superadmin email) ->
set a session cookie -> redirect to the console. The user's grant is only used to prove
identity; no tokens are stored.
"""

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import StudyMembership, User
from app.security import (
    COOKIE_NAME,
    STATE_COOKIE,
    cookie_secure,
    get_optional_user,
    make_session,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def _superadmin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().superadmin_emails.split(",") if e.strip()}


def _provision_user(db: Session, email: str, sub: str | None, name: str | None) -> User | None:
    """Return the User for a verified Google identity, or None if not allowlisted.

    Allowlist = an existing `users` row, OR an email in SUPERADMIN_EMAILS (bootstrap — created
    as a superuser on first login). Superadmin emails are (re)promoted on every login.
    """
    email = email.lower()
    user = db.scalar(select(User).where(User.email == email))
    is_boot_super = email in _superadmin_emails()
    if user is None:
        if not is_boot_super:
            return None
        user = User(email=email, google_sub=sub, name=name, is_superuser=True)
        db.add(user)
    else:
        if sub:
            user.google_sub = sub
        if name:
            user.name = name
        if is_boot_super:
            user.is_superuser = True
    db.commit()
    db.refresh(user)
    return user


@router.get("/login")
def login() -> RedirectResponse:
    s = get_settings()
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": s.google_client_id,
        "redirect_uri": s.researcher_oauth_redirect_uri,
        "scope": s.researcher_google_scopes,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{AUTH_ENDPOINT}?{urlencode(params)}")
    resp.set_cookie(
        STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=cookie_secure()
    )
    return resp


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    s = get_settings()
    if error:
        raise HTTPException(status_code=400, detail=f"Google sign-in failed: {error}")
    if not code or not state or request.cookies.get(STATE_COOKIE) != state:
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state")

    token_resp = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": s.researcher_oauth_redirect_uri,
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    id_token_str = token_resp.json().get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=400, detail="No id_token from Google")

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), s.google_client_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"id_token verification failed: {exc}") from exc

    if not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="Email not verified by Google")

    user = _provision_user(db, claims["email"], claims.get("sub"), claims.get("name"))
    if user is None:
        raise HTTPException(status_code=403, detail="This Google account is not authorized")

    # Land back on the console (same origin as the callback host).
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        make_session(user.id),
        max_age=s.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
    )
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.post("/logout")
def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


@router.get("/me")
def me(user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)) -> dict:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    memberships = db.scalars(
        select(StudyMembership).where(StudyMembership.user_id == user.id)
    )
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_superuser": user.is_superuser,
        "memberships": [{"study_id": m.study_id, "role": m.role} for m in memberships],
    }
