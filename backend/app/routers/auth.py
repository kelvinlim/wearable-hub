"""Researcher Google-login auth (reuses the project's Google OAuth client).

Flow: GET /auth/login -> Google consent (openid email profile) -> GET /auth/callback ->
verify the id_token -> allowlist check (a `users` row, or a bootstrap superadmin email) ->
set a session cookie -> redirect to the console. The user's grant is only used to prove
identity; no tokens are stored.

`/auth/callback` is a browser navigation (Google redirects the researcher here). Failures
return a LoginView-styled HTML page so the tab is not a raw FastAPI JSON error. Clients
that ask for `application/json` still get `{"detail": "..."}`.
"""

import html
import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

# Stable API detail for programmatic clients. Browser HTML uses friendlier copy.
UNAUTHORIZED_DETAIL = "This Google account is not authorized"

# Lucide `Activity` path — same mark as frontend LoginView.
_ACTIVITY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>'
)

# Mirrors frontend LoginView (centered card, UMN maroon/gold, dark-mode via prefers-color-scheme).
_LOGIN_ERROR_STYLE = """
:root{--maroon:#7A0019;--maroon-dark:#5A0013;--gold:#FFCC33}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
  font-family:'Open Sans',system-ui,-apple-system,sans-serif;background:#f9fafb;color:#111827}
.card{width:22rem;max-width:calc(100vw - 2rem);border-radius:1rem;border:1px solid #e5e7eb;
  background:#fff;padding:2.5rem;text-align:center;box-shadow:0 10px 15px -3px rgba(0,0,0,.1)}
.icon{margin:0 auto 1rem;display:flex;width:3.5rem;height:3.5rem;align-items:center;
  justify-content:center;border-radius:.75rem;background:var(--maroon);color:var(--gold)}
h1{margin:0;font-size:1.5rem;font-weight:700;color:var(--maroon)}
.sub{margin:.25rem 0 0;font-size:.875rem;color:#6b7280}
h2{margin:1.25rem 0 0;font-size:1.05rem;font-weight:700;color:#111827}
p{margin:.6rem 0 0;font-size:.9rem;line-height:1.5;color:#374151}
.email{font-weight:600;word-break:break-all}
.btn{display:block;margin-top:1.5rem;padding:.65rem 1rem;border-radius:.5rem;
  background:var(--maroon);color:#fff;font-weight:600;text-decoration:none}
.btn:hover{background:var(--maroon-dark)}
@media (prefers-color-scheme: dark){
  body{background:#0a0a0a;color:#f5f5f5}
  .card{background:#171717;border-color:#262626}
  h1{color:var(--gold)}
  h2{color:#f5f5f5}
  p{color:#d4d4d4}
  .sub{color:#a3a3a3}
}
"""


def _console_base() -> str:
    """Console root derived from the researcher OAuth callback URI."""
    return get_settings().researcher_oauth_redirect_uri.split("/auth/callback")[0] + "/"


def _prefers_html(request: Request) -> bool:
    """Browser navigations get HTML; clients that only ask for JSON get JSON."""
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept:
        return True
    # OAuth callback is a browser endpoint; default to a readable page.
    return "application/json" not in accept


def _researcher_error_page(
    *,
    title: str,
    lead: str,
    extra_html: str = "",
    status_code: int = 403,
) -> HTMLResponse:
    """LoginView-styled HTML so a failed Google callback does not look like a broken API."""
    login_href = html.escape(_console_base(), quote=True)
    heading = html.escape(title)
    body = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{heading} — Wearable Hub</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap' "
        "rel='stylesheet'>"
        f"<style>{_LOGIN_ERROR_STYLE}</style></head><body>"
        "<div class='card'>"
        f"<div class='icon'>{_ACTIVITY_SVG}</div>"
        "<h1>Wearable Hub</h1>"
        "<p class='sub'>Researcher console</p>"
        f"<h2>{heading}</h2>"
        f"<p>{html.escape(lead)}</p>"
        f"{extra_html}"
        f"<a class='btn' href='{login_href}'>Back to sign in</a>"
        "</div></body></html>"
    )
    return HTMLResponse(body, status_code=status_code)


def _auth_error(
    request: Request,
    status_code: int,
    detail: str,
    *,
    title: str = "Sign-in failed",
    lead: str | None = None,
    extra_html: str = "",
) -> HTMLResponse | JSONResponse:
    if not _prefers_html(request):
        return JSONResponse({"detail": detail}, status_code=status_code)
    return _researcher_error_page(
        title=title,
        lead=lead or detail,
        extra_html=extra_html,
        status_code=status_code,
    )


def _unauthorized_response(request: Request, email: str | None) -> HTMLResponse | JSONResponse:
    extra = (
        "<p>Contact your study PI or administrator and ask them to add you on "
        "Research staff or as a study member.</p>"
    )
    if email:
        extra += f"<p>You signed in as <span class='email'>{html.escape(email)}</span>.</p>"
    extra += (
        "<p>If you have more than one Google account, try signing in again with the one "
        "your study team set up.</p>"
    )
    return _auth_error(
        request,
        403,
        UNAUTHORIZED_DETAIL,
        title="Account not set up",
        lead="This Google account is not set up for Wearable Hub yet.",
        extra_html=extra,
    )


def _superadmin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().superadmin_emails.split(",") if e.strip()}


def _split_name(name: str | None) -> tuple[str | None, str | None]:
    """Split a Google display name into (first, last) on its first space."""
    full = (name or "").strip()
    if not full:
        return None, None
    first, _, last = full.partition(" ")
    return first, last.strip() or None


def _provision_user(db: Session, email: str, sub: str | None, name: str | None) -> User | None:
    """Return the User for a verified Google identity, or None if not allowlisted.

    Allowlist = an existing `users` row, OR an email in SUPERADMIN_EMAILS (bootstrap — created
    as a superuser on first login). Superadmin emails are (re)promoted on every login.

    Only `name` tracks Google. `first_name`/`last_name` are staff-editable (see
    `PATCH /admin/users/{id}`) and are seeded once at creation, never overwritten here.
    """
    email = email.lower()
    user = db.scalar(select(User).where(User.email == email))
    is_boot_super = email in _superadmin_emails()
    if user is None:
        if not is_boot_super:
            return None
        first, last = _split_name(name)
        user = User(
            email=email,
            google_sub=sub,
            name=name,
            first_name=first,
            last_name=last,
            is_superuser=True,
        )
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
        return _auth_error(
            request,
            400,
            f"Google sign-in failed: {error}",
            title="Sign-in cancelled",
            lead="Google sign-in did not complete. You can try again from the login page.",
        )
    if not code or not state or request.cookies.get(STATE_COOKIE) != state:
        return _auth_error(
            request,
            400,
            "Invalid or missing OAuth state",
            title="Sign-in expired",
            lead="This sign-in link is invalid or has expired. Please start again from the login page.",
        )

    try:
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
    except httpx.HTTPError:
        log.exception("Google token exchange failed")
        return _auth_error(
            request,
            400,
            "Google sign-in failed: could not exchange authorization code",
            title="Sign-in failed",
            lead="Wearable Hub could not finish signing you in with Google. Please try again.",
        )
    id_token_str = token_resp.json().get("id_token")
    if not id_token_str:
        return _auth_error(
            request,
            400,
            "No id_token from Google",
            title="Sign-in failed",
            lead="Google did not return the information needed to sign you in. Please try again.",
        )

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), s.google_client_id
        )
    except ValueError as exc:
        log.warning("id_token verification failed: %s", exc)
        return _auth_error(
            request,
            400,
            f"id_token verification failed: {exc}",
            title="Sign-in failed",
            lead="Wearable Hub could not verify your Google sign-in. Please try again.",
        )

    if not claims.get("email_verified"):
        return _auth_error(
            request,
            403,
            "Email not verified by Google",
            title="Email not verified",
            lead="Google has not verified this email address, so Wearable Hub cannot sign you in.",
        )

    user = _provision_user(db, claims["email"], claims.get("sub"), claims.get("name"))
    if user is None:
        return _unauthorized_response(request, claims.get("email"))

    # Land back on the console root (derived from the callback URI: strip the /auth/callback
    # suffix, leaving e.g. https://omnikog.asuscomm.com/wearable/).
    resp = RedirectResponse(_console_base(), status_code=303)
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
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_superuser": user.is_superuser,
        "memberships": [{"study_id": m.study_id, "role": m.role} for m in memberships],
    }
