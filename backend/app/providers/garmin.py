"""Garmin Health OAuth 1.0a provider, plus identity + deregistration helpers.

Garmin differs from `fitbit_gh` in three ways (see docs/garmin-integration-plan.md):
  - **OAuth 1.0a** (3-legged, HMAC-SHA1 signed) — no refresh tokens, tokens don't expire.
  - **Push webhooks carry the values** — there is no pull/consolidation step; data lands via the
    `/webhooks/garmin/{datatype}` endpoints and is aggregated by `app/garmin_ingest.py`.
  - **No subscription API** — Garmin pushes once a user authorizes.

The OAuth1a handshake is the standard 3-legged flow, mirrored from the prior art
([garminrec/app_usercode.py](garminrec/app_usercode.py) lines 99-275); `requests-oauthlib`
(`OAuth1Session`) does the HMAC-SHA1 signing. We persist the transient request token / secret on
the `provider_accounts` row (`state` / `code_verifier`) keyed by the request token — request-safe
across restarts, like the Google flow.
"""

import logging

from requests_oauthlib import OAuth1Session

from app.config import get_settings
from app.providers.base import TokenResult

log = logging.getLogger(__name__)

NAME = "garmin"

_TIMEOUT = 30.0


# --- OAuth 1.0a -----------------------------------------------------------------

def start_auth() -> tuple[str, str, str]:
    """Begin enrollment: fetch a request token, return (authorize_url, request_token, secret).

    The caller persists `request_token` on `provider_accounts.state` and `secret` on
    `code_verifier`, then redirects the subject to `authorize_url`. Garmin redirects back to the
    callback with `oauth_token` (== request_token) + `oauth_verifier`.
    """
    s = get_settings()
    oauth = OAuth1Session(
        s.garmin_consumer_key,
        client_secret=s.garmin_consumer_secret,
        callback_uri=s.garmin_oauth_redirect_uri,
    )
    fetched = oauth.fetch_request_token(s.garmin_request_token_url)
    request_token = fetched.get("oauth_token")
    request_secret = fetched.get("oauth_token_secret")
    authorize_url = oauth.authorization_url(s.garmin_authorize_url)
    return authorize_url, request_token, request_secret


def exchange(oauth_token: str, oauth_verifier: str, request_secret: str) -> TokenResult:
    """Exchange the authorized request token for a Garmin user access token (UAT).

    The Garmin **token secret** is needed to sign later API/webhook-validation calls, so it's
    carried in `TokenResult.refresh_token` (the router encrypts it like any other token). We also
    resolve the Garmin `userId` here — it's the identity key inbound pushes are matched on.
    """
    s = get_settings()
    oauth = OAuth1Session(
        s.garmin_consumer_key,
        client_secret=s.garmin_consumer_secret,
        resource_owner_key=oauth_token,
        resource_owner_secret=request_secret,
        verifier=oauth_verifier,
    )
    tokens = oauth.fetch_access_token(s.garmin_access_token_url)
    uat = tokens.get("oauth_token")
    token_secret = tokens.get("oauth_token_secret")

    user_id: str | None = None
    try:
        user_id = fetch_user_id(uat, token_secret)
    except Exception:  # noqa: BLE001 — enrollment still succeeds; userId can be backfilled later
        log.exception("Garmin user-id lookup failed during exchange; provider_user_id left unset")

    return TokenResult(
        access_token=uat,
        refresh_token=token_secret,
        expires_at=None,  # Garmin tokens don't expire
        scope=None,
        provider_user_id=user_id,
        raw=dict(tokens),
    )


def refresh(refresh_token: str) -> TokenResult:
    """Garmin OAuth1a tokens never expire — there is nothing to refresh."""
    raise NotImplementedError("Garmin OAuth1a tokens do not expire")


# --- Identity + lifecycle (OAuth1-signed user calls) ----------------------------

def _user_session(uat: str, secret: str) -> OAuth1Session:
    s = get_settings()
    return OAuth1Session(
        s.garmin_consumer_key,
        client_secret=s.garmin_consumer_secret,
        resource_owner_key=uat,
        resource_owner_secret=secret,
    )


def fetch_user_id(uat: str, secret: str) -> str | None:
    """Resolve the Garmin `userId` for a user access token (the webhook identity key).

    GET {garmin_api_base}/user/id (OAuth1-signed) -> {"userId": "..."}.
    """
    s = get_settings()
    resp = _user_session(uat, secret).get(f"{s.garmin_api_base}/user/id", timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("userId")


def deregister(uat: str, secret: str) -> None:
    """Best-effort: revoke the user's Garmin registration. Idempotent.

    DELETE {garmin_api_base}/user/registration (OAuth1-signed). A 404 means the registration is
    already gone, so treat it as success.
    """
    s = get_settings()
    resp = _user_session(uat, secret).delete(
        f"{s.garmin_api_base}/user/registration", timeout=_TIMEOUT
    )
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()
