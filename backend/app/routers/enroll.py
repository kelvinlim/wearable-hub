"""Subject-facing enrollment + Google-Health OAuth flow.

Patterned on [fitbitreg/fitbit_flask.py](fitbitreg/fitbit_flask.py) lines 74–189, adapted
to Google OAuth2 and to persisting OAuth state on the `provider_accounts` row (keyed by
`state`) instead of a signed session — request-safe across restart/concurrency.

The HTML here is a minimal placeholder so the flow is browser-testable now.
TODO(frontend-slice): replace `/enroll` and the result pages with the React app.
"""

import logging

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import encrypt
from app.db import get_db
from app.models import ProjectSubscriber, ProviderAccount, Subject, Subscription
from app.providers import fitbit_gh

log = logging.getLogger(__name__)
router = APIRouter(prefix="/enroll", tags=["enroll"])


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:36rem;margin:4rem auto;"
        "padding:0 1rem;line-height:1.5}input{padding:.5rem;font-size:1rem}"
        "button{padding:.5rem 1rem;font-size:1rem;cursor:pointer}.err{color:#b00020}</style>"
        f"</head><body>{body}</body></html>"
    )
    return HTMLResponse(html, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def enroll_form(error: str | None = None) -> HTMLResponse:
    err = f"<p class='err'>{error}</p>" if error else ""
    body = (
        "<h1>Wearable enrollment</h1>"
        "<p>Enter the entry code provided by the study staff.</p>"
        f"{err}"
        "<form method='post' action='/enroll/start'>"
        "<input name='entry_code' placeholder='ENTRY CODE' required autofocus> "
        "<button type='submit'>Continue</button>"
        "</form>"
    )
    return _page("Enroll", body)


@router.post("/start")
def enroll_start(entry_code: str = Form(...), db: Session = Depends(get_db)):
    """Validate the entry code, stash PKCE+state on the provider_account, redirect to Google."""
    code = entry_code.strip().upper()
    subject = db.scalar(select(Subject).where(Subject.entry_code == code))
    if subject is None:
        return RedirectResponse(url="/enroll?error=Invalid+entry+code", status_code=303)

    acct = db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.subject_id == subject.id,
            ProviderAccount.provider == fitbit_gh.NAME,
        )
    )
    if acct and acct.registered:
        return RedirectResponse(
            url="/enroll?error=This+code+has+already+been+registered", status_code=303
        )

    code_verifier, code_challenge = fitbit_gh.generate_pkce()
    state = fitbit_gh.generate_state()

    if acct is None:
        acct = ProviderAccount(subject_id=subject.id, provider=fitbit_gh.NAME)
        db.add(acct)
    acct.state = state
    acct.code_verifier = code_verifier
    db.commit()

    return RedirectResponse(
        url=fitbit_gh.build_authorization_url(state, code_challenge), status_code=303
    )


@router.get("/callback", response_class=HTMLResponse)
def enroll_callback(
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Google redirects here. Look up the account by `state`, exchange the code, store tokens."""
    if error:
        return _page("Enrollment failed", f"<h1>Authorization denied</h1><p>{error}</p>", 400)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    acct = db.scalar(select(ProviderAccount).where(ProviderAccount.state == state))
    if acct is None:
        raise HTTPException(status_code=400, detail="Unknown or expired state")

    if not acct.code_verifier:
        raise HTTPException(status_code=400, detail="No PKCE verifier on record for this state")

    result = fitbit_gh.exchange(code, acct.code_verifier)

    acct.access_token = encrypt(result.access_token)
    if result.refresh_token:  # Google omits it on re-auth without prompt=consent; keep prior otherwise
        acct.refresh_token = encrypt(result.refresh_token)
    acct.token_expires_at = result.expires_at
    acct.scope = result.scope
    acct.provider_user_id = result.provider_user_id
    acct.raw_token_json = result.raw
    acct.registered = True
    # One-time-use: clear the OAuth handshake fields now that they're spent.
    acct.state = None
    acct.code_verifier = None

    subject = db.get(Subject, acct.subject_id)
    if subject:
        subject.status = "registered"

    db.commit()

    _maybe_subscribe(db, acct)

    return _page(
        "Enrolled",
        "<h1>You're enrolled 🎉</h1><p>Your wearable is now linked. You can close this window.</p>",
    )


def _maybe_subscribe(db: Session, acct: ProviderAccount) -> None:
    """Best-effort Tier-2: create a per-user subscription under the project subscriber.

    Requires the project subscriber to already be registered (Tier-1, via the admin path).
    If it isn't, we skip — enrollment still succeeds; the subscription can be created later.
    Never breaks enrollment (tokens are already stored).
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
    try:
        raw = fitbit_gh.create_subscription(subscriber.subscriber_id, acct.provider_user_id)
        db.add(
            Subscription(
                provider_account_id=acct.id,
                subscriber_id=subscriber.subscriber_id,
                provider_subscription_id=raw.get("name") or raw.get("id"),
                data_types=raw.get("dataTypes"),
                status="active",
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 — enrollment must succeed regardless
        log.exception("Tier-2 subscription failed for provider_account %s", acct.id)
        db.rollback()
