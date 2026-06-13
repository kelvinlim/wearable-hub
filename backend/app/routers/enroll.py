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
from app.models import ProjectSubscriber, ProviderAccount, Subject
from app.providers import fitbit_gh

log = logging.getLogger(__name__)
router = APIRouter(prefix="/enroll", tags=["enroll"])


# UMN-branded shell (maroon #7A0019 / gold #FFCC33). Server-rendered so subjects need no JS app.
# The "M" tile is a stylized placeholder — drop the official UMN wordmark in to replace it.
_STYLE = """
:root{--maroon:#7A0019;--gold:#FFCC33}
*{box-sizing:border-box}
body{font-family:'Open Sans',system-ui,-apple-system,sans-serif;margin:0;background:#f5f5f7;color:#1c1f26;line-height:1.6}
.bar{background:var(--maroon);color:#fff;display:flex;align-items:center;gap:.8rem;padding:.9rem 1.25rem;border-bottom:4px solid var(--gold)}
.bar .m{display:inline-flex;width:36px;height:36px;background:var(--gold);color:var(--maroon);border-radius:7px;align-items:center;justify-content:center;font-weight:800;font-size:1.2rem}
.bar .t b{font-size:1.05rem}
.bar .t span{display:block;font-size:.78rem;opacity:.85}
.wrap{max-width:40rem;margin:2.5rem auto;padding:0 1.25rem}
.card{background:#fff;border:1px solid #e3e3e8;border-radius:14px;padding:1.75rem 2rem;box-shadow:0 4px 18px rgba(0,0,0,.04)}
h1{font-size:1.5rem;color:var(--maroon);margin:0 0 .6rem}
.lead{font-size:1.05rem;color:#3a3d45}
.steps{font-weight:600;margin:1.1rem 0 .25rem}
ol{padding-left:1.2rem;margin:.25rem 0}ol li{margin:.3rem 0}
.note{font-size:.92rem;color:#5a5e69;background:#faf7ee;border:1px solid #f0e6c8;border-radius:10px;padding:.8rem 1rem;margin:1.25rem 0}
form{display:flex;gap:.6rem;flex-wrap:wrap;margin-top:1rem}
input{padding:.7rem .85rem;font-size:1.05rem;border:1px solid #c9ccd4;border-radius:8px;flex:1;min-width:13rem;text-transform:uppercase;letter-spacing:.08em}
input:focus{outline:none;border-color:var(--maroon);box-shadow:0 0 0 3px rgba(122,0,25,.15)}
button{padding:.7rem 1.4rem;font-size:1.05rem;font-weight:700;cursor:pointer;background:var(--maroon);color:#fff;border:0;border-radius:8px}
button:hover{background:#5a0013}
.err{color:#b00020;font-weight:600;margin:.75rem 0 0}
.foot{text-align:center;color:#8a8f9a;font-size:.8rem;margin-top:1.5rem}
a{color:var(--maroon)}
"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    html = (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{title} — University of Minnesota</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap' rel='stylesheet'>"
        f"<style>{_STYLE}</style></head><body>"
        "<div class='bar'><span class='m'>M</span>"
        "<div class='t'><b>University of Minnesota</b>"
        "<span>Wearable Hub — research data sharing</span></div></div>"
        f"<div class='wrap'><div class='card'>{body}</div>"
        "<div class='foot'>Version 1.0 · Questions? Contact your study staff.</div></div>"
        "</body></html>"
    )
    return HTMLResponse(html, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def enroll_form(error: str | None = None) -> HTMLResponse:
    err = f"<p class='err'>{error}</p>" if error else ""
    body = (
        "<h1>Thank you for participating in University of Minnesota research</h1>"
        "<p class='lead'>Enter the code your study staff gave you. If it's valid, you'll be taken "
        "to Google to authorize sharing your wearable (Fitbit) data with the research team.</p>"
        "<p class='steps'>What happens next</p>"
        "<ol>"
        "<li>Enter your study code below.</li>"
        "<li>Sign in with the Google account connected to your Fitbit.</li>"
        "<li>Review and approve sharing your activity, sleep, and heart-rate data.</li>"
        "</ol>"
        "<div class='note'>Taking part is voluntary, and your data is used only for this research "
        "study. You can stop sharing at any time by contacting your study staff or removing the "
        "app's access in your Google Account settings.</div>"
        f"{err}"
        "<form method='post' action='/enroll/start'>"
        "<input name='entry_code' placeholder='ENTER YOUR CODE' required autofocus "
        "aria-label='Study code'>"
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
        "<h1>You're enrolled 🎉</h1>"
        "<p class='lead'>Your wearable is now linked to the study. There's nothing else to do — "
        "your data will sync automatically over the coming days.</p>"
        "<div class='note'>You can stop sharing at any time by contacting your study staff or "
        "removing the app's access in your Google Account settings. You may now close this window.</div>",
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
