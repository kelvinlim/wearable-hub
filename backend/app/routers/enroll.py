"""Subject-facing enrollment + per-provider OAuth flow.

Enrollment is keyed by a **per-device entry code** on `provider_accounts` (a subject may register
both a Fitbit and a Garmin device, each with its own code). Entering the code picks the provider,
customizes the page copy, and launches that provider's OAuth:

  - **Fitbit (Google Health):** OAuth2 + PKCE — patterned on
    [fitbitreg/fitbit_flask.py](fitbitreg/fitbit_flask.py); state + PKCE verifier persisted on the
    row (keyed by `state`), request-safe across restart/concurrency.
  - **Garmin:** OAuth 1.0a — the request token / secret are persisted on the same row (`state` /
    `code_verifier`), keyed by the request token.

One `/enroll/callback` handles both, dispatching by which OAuth params are present.
"""

import logging

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.branding import page as _page
from app.config import get_settings
from app.crypto import encrypt
from app.db import get_db
from app.models import ProjectSubscriber, ProviderAccount, Study, Subject
from app.providers import fitbit_gh, garmin, gh_creds

log = logging.getLogger(__name__)
router = APIRouter(prefix="/enroll", tags=["enroll"])


def _provider_label(provider: str) -> str:
    return "Garmin" if provider == garmin.NAME else "Fitbit"


def _pfx() -> str:
    """Public path prefix the app is served under (e.g. "/wearable"), for in-page links/redirects."""
    return get_settings().public_path_prefix.rstrip("/")


@router.get("", response_class=HTMLResponse)
def enroll_form(error: str | None = None) -> HTMLResponse:
    pfx = _pfx()
    err = f"<p class='err'>{error}</p>" if error else ""
    body = (
        "<h1>Thank you for participating in University of Minnesota research</h1>"
        "<p class='lead'>Enter the code your study staff gave you. If it's valid, you'll be taken "
        "to your device provider (Fitbit or Garmin) to authorize sharing your wearable data with "
        "the research team.</p>"
        "<p class='steps'>What happens next</p>"
        "<ol>"
        "<li>Enter your study code below.</li>"
        "<li>Sign in with the account connected to your wearable (Google for Fitbit, or Garmin "
        "Connect for Garmin).</li>"
        "<li>Review and approve sharing your activity, sleep, and heart-rate data.</li>"
        "</ol>"
        # Prominent in-app disclosure (Google OAuth verification requirement): names the data
        # accessed and how it is used, shown during normal app use — not only in the policy.
        "<div class='disclosure'>University of Minnesota Wearable Hub collects your activity, "
        "sleep, heart-rate, blood-oxygen (SpO2), heart-rate-variability, and wearable-device "
        "information (such as battery level and last sync) from your connected Fitbit (via Google) "
        "or Garmin account to support the research study you enrolled in. Your data is used only by "
        "the research team for this study and is never sold or used for advertising. "
        "See our <a href='/privacy'>Privacy Policy</a> for details.</div>"
        "<div class='note'>Taking part is voluntary, and your data is used only for this research "
        "study. You can stop sharing at any time by contacting your study staff or removing the "
        "app's access in your Google or Garmin account settings.</div>"
        f"{err}"
        f"<form method='post' action='{pfx}/enroll/start'>"
        "<input name='entry_code' placeholder='ENTER YOUR CODE' required autofocus "
        "aria-label='Study code'>"
        "<button type='submit'>Continue</button>"
        "</form>"
    )
    return _page("Enroll", body)


@router.post("/start")
def enroll_start(entry_code: str = Form(...), db: Session = Depends(get_db)):
    """Validate the entry code, stash the OAuth handshake on its provider_account, redirect out.

    The code identifies a (subject, provider) registration; we branch on that provider.
    """
    pfx = _pfx()
    code = entry_code.strip().upper()
    acct = db.scalar(select(ProviderAccount).where(ProviderAccount.entry_code == code))
    if acct is None:
        return RedirectResponse(url=f"{pfx}/enroll?error=Invalid+entry+code", status_code=303)
    if acct.registered:
        return RedirectResponse(
            url=f"{pfx}/enroll?error=This+code+has+already+been+registered", status_code=303
        )

    if acct.provider == garmin.NAME:
        try:
            authorize_url, request_token, request_secret = garmin.start_auth()
        except Exception:  # noqa: BLE001 — surface a friendly error instead of a 500
            log.exception("Garmin request-token fetch failed for entry_code %s", code)
            return RedirectResponse(
                url=f"{pfx}/enroll?error=Could+not+start+Garmin+authorization", status_code=303
            )
        acct.state = request_token
        acct.code_verifier = request_secret
        db.commit()
        return RedirectResponse(url=authorize_url, status_code=303)

    # Default: Fitbit via Google Health (OAuth2 + PKCE). Enroll under the study's credential set
    # (which GCP project); pin it on the account so refresh/revoke use the issuing client.
    subject = db.get(Subject, acct.subject_id)
    study = db.get(Study, subject.study_id) if subject else None
    creds = gh_creds.resolve_for_study(db, study.id if study else None)
    acct.credential_set_id = study.credential_set_id if study else None
    code_verifier, code_challenge = fitbit_gh.generate_pkce()
    state = fitbit_gh.generate_state()
    acct.state = state
    acct.code_verifier = code_verifier
    db.commit()
    return RedirectResponse(
        url=fitbit_gh.build_authorization_url(creds, state, code_challenge), status_code=303
    )


@router.get("/callback", response_class=HTMLResponse)
def enroll_callback(
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_token: str | None = None,
    oauth_verifier: str | None = None,
) -> HTMLResponse:
    """Provider redirects here. Dispatch by which OAuth params are present.

    `code` + `state` → Google (Fitbit); `oauth_token` + `oauth_verifier` → Garmin (OAuth1a).
    """
    if error:
        return _page("Enrollment failed", f"<h1>Authorization denied</h1><p>{error}</p>", 400)

    if oauth_token and oauth_verifier:
        return _garmin_callback(db, oauth_token, oauth_verifier)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    return _fitbit_callback(db, code, state)


def _fitbit_callback(db: Session, code: str, state: str) -> HTMLResponse:
    acct = db.scalar(select(ProviderAccount).where(ProviderAccount.state == state))
    if acct is None:
        raise HTTPException(status_code=400, detail="Unknown or expired state")
    if not acct.code_verifier:
        raise HTTPException(status_code=400, detail="No PKCE verifier on record for this state")

    # Use the set pinned at enroll_start (the client that will issue this token).
    creds = gh_creds.resolve_for_account(db, acct)
    result = fitbit_gh.exchange(creds, code, acct.code_verifier)

    acct.access_token = encrypt(result.access_token)
    if result.refresh_token:  # Google omits it on re-auth without prompt=consent; keep prior otherwise
        acct.refresh_token = encrypt(result.refresh_token)
    acct.token_expires_at = result.expires_at
    acct.scope = result.scope
    acct.provider_user_id = result.provider_user_id
    acct.raw_token_json = result.raw
    acct.registered = True
    acct.state = None
    acct.code_verifier = None

    subject = db.get(Subject, acct.subject_id)
    if subject:
        subject.status = "registered"
    db.commit()

    _maybe_subscribe(db, acct)
    return _enrolled_page("Fitbit")


def _garmin_callback(db: Session, oauth_token: str, oauth_verifier: str) -> HTMLResponse:
    """Exchange the authorized Garmin request token for a user access token and store it."""
    acct = db.scalar(select(ProviderAccount).where(ProviderAccount.state == oauth_token))
    if acct is None:
        raise HTTPException(status_code=400, detail="Unknown or expired oauth_token")
    if not acct.code_verifier:
        raise HTTPException(status_code=400, detail="No request-token secret on record")

    result = garmin.exchange(oauth_token, oauth_verifier, acct.code_verifier)

    acct.access_token = encrypt(result.access_token)  # Garmin user access token (UAT)
    acct.refresh_token = encrypt(result.refresh_token) if result.refresh_token else None  # token secret
    acct.token_expires_at = None  # Garmin tokens don't expire
    acct.scope = result.scope
    acct.provider_user_id = result.provider_user_id  # Garmin userId (webhook identity key)
    acct.raw_token_json = result.raw
    acct.registered = True
    acct.state = None
    acct.code_verifier = None

    subject = db.get(Subject, acct.subject_id)
    if subject:
        subject.status = "registered"
    db.commit()
    return _enrolled_page("Garmin")


def _enrolled_page(provider_label: str) -> HTMLResponse:
    return _page(
        "Enrolled",
        "<h1>You're enrolled 🎉</h1>"
        f"<p class='lead'>Your {provider_label} device is now linked to the study. There's nothing "
        "else to do — your data will sync automatically over the coming days.</p>"
        "<div class='note'>You can stop sharing at any time by contacting your study staff or "
        f"removing the app's access in your {provider_label} account settings. You may now close "
        "this window.</div>",
    )


def _maybe_subscribe(db: Session, acct: ProviderAccount) -> None:
    """Best-effort Tier-2: create a per-user subscription under the project subscriber.

    Requires the project subscriber to already be registered (Tier-1, via the admin path).
    If it isn't, we skip — enrollment still succeeds; the subscription can be created later.
    Never breaks enrollment (tokens are already stored). Fitbit/Google only.
    """
    settings = fitbit_gh.get_settings()

    # With AUTOMATIC subscriptionCreatePolicy, Google creates per-user subscriptions on
    # consent — we do nothing here and learn of them via webhooks. Only MANUAL needs a call.
    if settings.gh_subscription_create_policy.upper() == "AUTOMATIC":
        log.info(
            "subscriptionCreatePolicy=AUTOMATIC; Google auto-subscribes provider_account %s",
            acct.id,
        )
        return

    subscriber = db.scalar(
        select(ProjectSubscriber).where(ProjectSubscriber.project_id == settings.gh_project_id)
    )
    if subscriber is None or not subscriber.subscriber_id:
        log.info(
            "No project subscriber registered (run POST /admin/subscriber); "
            "skipping Tier-2 subscription for provider_account %s",
            acct.id,
        )
        return

    # MANUAL path needs the public healthUserId, which is NOT available at enrollment (the
    # OAuth `sub` we store is rejected by the subscriptions API). It only arrives via webhook
    # payloads / an auto-created subscription's `user` field. So we can't create a MANUAL
    # subscription here yet. TODO(tier2-manual): if MANUAL is adopted, resolve healthUserId
    # first (e.g. fitbit_gh.list_subscriptions(...) or capture it from the first webhook),
    # persist it on provider_account, then call fitbit_gh.create_subscription(sub_id, hid, dts).
    log.warning(
        "MANUAL subscriptionCreatePolicy set but healthUserId for provider_account %s is "
        "unknown at enrollment; deferring Tier-2 subscription creation.",
        acct.id,
    )
