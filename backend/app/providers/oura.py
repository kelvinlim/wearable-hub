"""Oura Ring OAuth2 provider + usercollection pulls + app-level webhook subscriptions.

Third provider. Differences from the other two that shape this module:
  - Standard confidential authorization-code flow (client_secret, NO PKCE). Refresh
    tokens are SINGLE-USE: every refresh() rotates the pair and the old refresh token is
    invalidated server-side, so callers MUST persist (and commit) the returned pair
    before making any further API call — see oura_ingest._fresh_token.
  - Data is pull-only REST (GET /v2/usercollection/{type}), paginated via next_token.
    `heartrate` filters by start_datetime/end_datetime; everything else by
    start_date/end_date, and daily/sleep documents carry a local calendar `day` field.
  - Webhooks are APP-level (one subscription per (data_type, event_type) pair for the
    whole application, authenticated with x-client-id/x-client-secret — no user token).
    Events carry no values; the webhook handler marks days dirty and consolidation pulls.
"""

import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.providers.base import TokenResult

NAME = "oura"

_HTTP_TIMEOUT = 30.0


class GrantRevokedError(RuntimeError):
    """The user's OAuth grant is no longer valid (revoked, or refresh rejected)."""


# --- OAuth ----------------------------------------------------------------------

def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    s = get_settings()
    params = {
        "response_type": "code",
        "client_id": s.oura_client_id,
        "redirect_uri": s.oura_oauth_redirect_uri,
        "scope": s.oura_scopes,
        "state": state,
    }
    return f"{s.oura_authorize_url}?{urlencode(params)}"


def _expires_at(token: dict) -> datetime | None:
    expires_in = token.get("expires_in")
    if not expires_in:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).replace(tzinfo=None)


def _to_result(token: dict, provider_user_id: str | None = None) -> TokenResult:
    return TokenResult(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        expires_at=_expires_at(token),
        scope=token.get("scope"),
        provider_user_id=provider_user_id,
        raw=token,
    )


def exchange(code: str) -> TokenResult:
    """Exchange an authorization code for tokens, then best-effort resolve the Oura user id
    (personal_info `id`) so webhook events can be matched to the account."""
    s = get_settings()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": s.oura_client_id,
        "client_secret": s.oura_client_secret,
        "redirect_uri": s.oura_oauth_redirect_uri,
    }
    resp = httpx.post(s.oura_token_url, data=data, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    token = resp.json()
    user_id = None
    try:
        user_id = fetch_user_id(token["access_token"])
    except Exception:
        pass  # linked later via the single-unlinked-account webhook fallback
    return _to_result(token, provider_user_id=user_id)


def refresh(refresh_token: str) -> TokenResult:
    """Refresh the access token. The result ALWAYS carries the rotated refresh token —
    the one passed in is dead after this call succeeds. A rejected refresh means the
    grant is gone (revoked, or the single-use token was already spent and lost)."""
    s = get_settings()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": s.oura_client_id,
        "client_secret": s.oura_client_secret,
    }
    resp = httpx.post(s.oura_token_url, data=data, timeout=_HTTP_TIMEOUT)
    if resp.status_code == 401 or (resp.status_code == 400 and "invalid_grant" in resp.text):
        raise GrantRevokedError("refresh_token rejected: grant revoked or rotation lost")
    resp.raise_for_status()
    return _to_result(resp.json())


def revoke(access_token: str) -> None:
    """Revoke the grant at Oura. Idempotent — an already-dead token's 400/401 is fine."""
    resp = httpx.post(
        "https://api.ouraring.com/oauth/revoke",
        data={"access_token": access_token},
        timeout=_HTTP_TIMEOUT,
    )
    if resp.status_code not in (200, 204, 400, 401):
        resp.raise_for_status()


# --- User API (subject Bearer token) ---------------------------------------------

def _collection_base() -> str:
    s = get_settings()
    if s.oura_use_sandbox:
        return f"{s.oura_api_base}/sandbox/usercollection"
    return f"{s.oura_api_base}/usercollection"


def _raise_for_user_call(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise GrantRevokedError("Oura API returned 401: token/grant revoked")
    resp.raise_for_status()


def fetch_user_id(access_token: str) -> str | None:
    """The stable Oura user id from personal_info (needs the `personal` scope)."""
    s = get_settings()
    resp = httpx.get(
        f"{s.oura_api_base}/usercollection/personal_info",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_HTTP_TIMEOUT,
    )
    _raise_for_user_call(resp)
    uid = resp.json().get("id")
    return str(uid) if uid else None


def _fetch_paginated(url: str, params: dict, access_token: str) -> list[dict]:
    out: list[dict] = []
    next_token: str | None = None
    for _ in range(50):  # safety bound
        q = dict(params)
        if next_token:
            q["next_token"] = next_token
        resp = httpx.get(
            url, params=q, headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT,
        )
        _raise_for_user_call(resp)
        j = resp.json()
        out.extend(j.get("data") or [])
        next_token = j.get("next_token")
        if not next_token:
            break
    return out


def fetch_collection(access_token: str, data_type: str, start: date, end: date) -> list[dict]:
    """All documents of a date-keyed usercollection type in [start, end] inclusive."""
    return _fetch_paginated(
        f"{_collection_base()}/{data_type}",
        {"start_date": start.isoformat(), "end_date": end.isoformat()},
        access_token,
    )


def fetch_heartrate(access_token: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Intraday heart-rate samples (~5-min bpm) in a datetime window (ISO, with offset)."""
    return _fetch_paginated(
        f"{_collection_base()}/heartrate",
        {"start_datetime": start_dt.isoformat(), "end_datetime": end_dt.isoformat()},
        access_token,
    )


# --- App-level webhook subscriptions (x-client-id / x-client-secret) --------------

def _webhook_headers() -> dict:
    s = get_settings()
    return {"x-client-id": s.oura_client_id, "x-client-secret": s.oura_client_secret}


def _webhook_url(path: str = "") -> str:
    return f"{get_settings().oura_api_base}/webhook/subscription{path}"


def list_webhook_subscriptions() -> list[dict]:
    resp = httpx.get(_webhook_url(), headers=_webhook_headers(), timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def create_webhook_subscription(data_type: str, event_type: str) -> dict:
    """Create one (data_type, event_type) subscription. Oura fires the GET challenge at
    our callback URL synchronously — the webhook endpoint must already be public."""
    s = get_settings()
    body = {
        "callback_url": s.oura_webhook_public_url,
        "verification_token": s.oura_webhook_verification_token,
        "event_type": event_type,
        "data_type": data_type,
    }
    resp = httpx.post(_webhook_url(), json=body, headers=_webhook_headers(), timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def renew_webhook_subscription(sub_id: str) -> dict:
    resp = httpx.put(
        _webhook_url(f"/renew/{sub_id}"), headers=_webhook_headers(), timeout=_HTTP_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


def delete_webhook_subscription(sub_id: str) -> None:
    resp = httpx.delete(_webhook_url(f"/{sub_id}"), headers=_webhook_headers(), timeout=_HTTP_TIMEOUT)
    if resp.status_code not in (204, 403):  # 403 = already gone
        resp.raise_for_status()


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Validate the x-oura-signature header: HMAC-SHA256 of the raw body with the client
    secret. Accepts hex with or without an algorithm prefix (e.g. "sha256=<hex>")."""
    secret = get_settings().oura_client_secret
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, candidate)
