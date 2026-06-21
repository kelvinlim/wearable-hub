"""Provider-account lifecycle helpers shared across routers.

Revocation has three triggers, all converging here:
  - **Outbound:** staff revoke a subject (admin endpoint) → `revoke_account` (calls Google).
  - **Reactive:** a token refresh returns `invalid_grant` → the grant is already gone, so
    `mark_revoked` (no Google call needed).
  - **Inbound:** a deregistration webhook (best-effort; shape unverified) → `mark_revoked`.
"""

import logging

from sqlalchemy.orm import Session

from app.crypto import decrypt
from app.models import ProviderAccount, Subject
from app.providers import fitbit_gh, garmin

log = logging.getLogger(__name__)


def mark_revoked(db: Session, acct: ProviderAccount, *, subject_status: str = "revoked") -> None:
    """Flip an account to unregistered and forget its (now-dead) tokens. Does NOT call Google.

    Use when the grant is already gone — reactive `invalid_grant`, or an inbound deregistration
    notification. `health_user_id`/`provider_user_id` are kept for history. Caller commits.
    """
    acct.registered = False
    acct.access_token = None
    acct.refresh_token = None
    acct.token_expires_at = None
    subj = db.get(Subject, acct.subject_id)
    if subj and subject_status:
        subj.status = subject_status


def revoke_account(db: Session, acct: ProviderAccount) -> bool:
    """Revoke the account's grant at the provider (best-effort), then mark it revoked locally.

    Dispatches by provider: Google (`fitbit_gh.revoke`) vs Garmin (`garmin.deregister`). Returns
    True if a revoke/deregister call was actually sent. Provider revocation is idempotent; if it
    can't be reached we still mark the account revoked locally and log. Caller commits.
    """
    token_sent = False
    try:
        if acct.provider == garmin.NAME:
            # Garmin OAuth1a needs both the UAT (access_token) and the token secret (refresh_token).
            if acct.access_token and acct.refresh_token:
                garmin.deregister(decrypt(acct.access_token), decrypt(acct.refresh_token))
                token_sent = True
        else:
            token = None
            if acct.refresh_token:
                token = decrypt(acct.refresh_token)
            elif acct.access_token:
                token = decrypt(acct.access_token)
            if token:
                fitbit_gh.revoke(token)
                token_sent = True
    except Exception:  # noqa: BLE001 — never let a provider hiccup block the local revoke
        log.exception(
            "Provider revoke failed for provider_account %s; marking revoked locally", acct.id
        )
    mark_revoked(db, acct)
    return token_sent
