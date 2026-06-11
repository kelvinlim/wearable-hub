"""Fitbit-via-Google-Health OAuth2 + PKCE provider, plus subscription API calls.

Replaces the legacy Fitbit Web API (OAuth2/PKCE against fitbit.com) with Google
OAuth 2.0. Differs from the prior art ([fitbitreg/fitbit_flask.py](fitbitreg/fitbit_flask.py))
in three ways the plan calls out:
  - `access_type=offline` + `prompt=consent` to force a refresh token.
  - state + PKCE verifier are persisted on the `provider_accounts` row (by the router),
    not in a process global or signed cookie — request-safe across restarts/concurrency.
  - data arrives via a two-tier subscriber/subscription model, not pull polling.
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.providers.base import TokenResult

NAME = "fitbit_gh"

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
HEALTH_API_BASE = "https://health.googleapis.com/v4"

_HTTP_TIMEOUT = 30.0


# --- PKCE / state ---------------------------------------------------------------

def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for the S256 method."""
    verifier = secrets.token_urlsafe(64)[:128]  # RFC 7636: 43–128 chars
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def _expires_at(token: dict) -> datetime | None:
    """Compute a naive-UTC expiry from `expires_in`."""
    expires_in = token.get("expires_in")
    if not expires_in:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).replace(tzinfo=None)


def _decode_id_token_sub(id_token: str | None) -> str | None:
    """Best-effort: pull the stable Google account id (`sub`) from the id_token.

    Not cryptographically verified — we only trust this because it came straight
    from Google's token endpoint over TLS. Used as `provider_user_id`.
    """
    if not id_token:
        return None
    try:
        payload_b64 = id_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("sub")
    except Exception:
        return None


def _to_result(token: dict) -> TokenResult:
    return TokenResult(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        expires_at=_expires_at(token),
        scope=token.get("scope"),
        provider_user_id=_decode_id_token_sub(token.get("id_token")),
        raw=token,
    )


# --- OAuth ----------------------------------------------------------------------

def build_authorization_url(state: str, code_challenge: str) -> str:
    s = get_settings()
    params = {
        "response_type": "code",
        "client_id": s.google_client_id,
        "redirect_uri": s.oauth_redirect_uri,
        "scope": s.google_health_scopes,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",  # request a refresh token
        "prompt": "consent",       # force the consent screen so the refresh token is re-issued
        "include_granted_scopes": "true",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def exchange(code: str, code_verifier: str) -> TokenResult:
    """Exchange an authorization code for tokens (Google token endpoint)."""
    s = get_settings()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": s.google_client_id,
        "client_secret": s.google_client_secret,
        "redirect_uri": s.oauth_redirect_uri,
    }
    resp = httpx.post(TOKEN_ENDPOINT, data=data, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return _to_result(resp.json())


def refresh(refresh_token: str) -> TokenResult:
    """Refresh an access token. Google usually omits a new refresh_token; the
    caller should keep the existing one when the result's refresh_token is None.
    """
    s = get_settings()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": s.google_client_id,
        "client_secret": s.google_client_secret,
    }
    resp = httpx.post(TOKEN_ENDPOINT, data=data, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return _to_result(resp.json())


# --- Subscriptions (two-tier) ---------------------------------------------------
# Tier-1 (register the project subscriber) is a PROJECT operation — it must use project
# credentials (a service account), NOT a subject's user token, which gets 403. Tier-2
# (per-user subscription) references the already-registered subscriber. The exact request/
# response shapes and which credential Tier-2 needs are still being confirmed against
# Google's docs (see PLAN.md finding 2026-06-11); callers treat these as best-effort.


class ProjectCredentialsError(RuntimeError):
    """Raised when no project/service-account credentials are configured for Tier-1."""


class InvalidDataTypeError(ValueError):
    """Raised when a configured subscription dataType isn't subscribable."""


# Webhook-subscribable dataTypes, verified empirically against the live API on 2026-06-11
# (Google returns a bare 400 INVALID_ARGUMENT with no field detail for anything else).
# NOTE: heart rate / HRV / SpO2 / VO2 max / active(-zone) minutes / body fat / respiratory
# rate are NOT subscribable — they exist only as pull reads via the dataPoints endpoint,
# despite appearing in the general data-types docs.
SUBSCRIBABLE_DATA_TYPES = frozenset(
    {"steps", "sleep", "distance", "calories", "weight", "height", "floors", "exercise", "altitude"}
)


def project_access_token() -> str:
    """Mint an access token from the service account (or ADC) for project-level calls.

    Uses GH_SA_CREDENTIALS_FILE if set, else Application Default Credentials. Raises
    ProjectCredentialsError with a clear message when nothing is configured.
    """
    s = get_settings()
    scopes = s.gh_sa_scopes.split()
    try:
        import google.auth
        import google.auth.transport.requests
        from google.auth.exceptions import DefaultCredentialsError
        from google.oauth2 import service_account

        if s.gh_sa_credentials_file:
            creds = service_account.Credentials.from_service_account_file(
                s.gh_sa_credentials_file, scopes=scopes
            )
        else:
            try:
                creds, _ = google.auth.default(scopes=scopes)
            except DefaultCredentialsError as exc:
                raise ProjectCredentialsError(
                    "No project credentials: set GH_SA_CREDENTIALS_FILE to a mounted "
                    "service-account key, or provide Application Default Credentials."
                ) from exc
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except ProjectCredentialsError:
        raise
    except FileNotFoundError as exc:
        raise ProjectCredentialsError(
            f"GH_SA_CREDENTIALS_FILE not found: {s.gh_sa_credentials_file}"
        ) from exc


def register_subscriber() -> dict:
    """Tier-1: register the project's webhook subscriber. Project credentials. Idempotent.

    Per https://developers.google.com/health/webhooks:
      POST /v4/projects/{project-NUMBER}/subscribers?subscriberId={id}
      body: { endpointUri, subscriberConfigs:[{dataTypes, subscriptionCreatePolicy}],
              endpointAuthorization:{ secret } }
    The `secret` is echoed verbatim in the `Authorization` header of every inbound
    notification (and of the registration-time verification handshake), so we register
    "Bearer <WEBHOOK_SECRET>" and compare against it in the webhook handler.

    Registration triggers Google's two-step endpoint verification against `endpointUri`:
    an authorized probe (must 200) and an unauthorized probe (must 401/403). Our webhook
    must already be publicly reachable and WEBHOOK_SECRET set, or registration fails.
    """
    s = get_settings()
    if not s.gh_project_number:
        raise ProjectCredentialsError("GH_PROJECT_NUMBER is not set (subscriber API needs it).")

    config: dict = {"subscriptionCreatePolicy": s.gh_subscription_create_policy}
    data_types = s.gh_subscription_data_types.split()
    invalid = [d for d in data_types if d not in SUBSCRIBABLE_DATA_TYPES]
    if invalid:
        raise InvalidDataTypeError(
            f"Not webhook-subscribable: {', '.join(invalid)}. "
            f"Subscribable types are: {', '.join(sorted(SUBSCRIBABLE_DATA_TYPES))}. "
            "(Heart rate, HRV, SpO2, etc. are pull-only via the dataPoints read.)"
        )
    if data_types:
        config["dataTypes"] = data_types

    body = {
        "endpointUri": s.webhook_public_url,
        "subscriberConfigs": [config],
        "endpointAuthorization": {"secret": f"Bearer {s.webhook_secret}"},
    }
    url = f"{HEALTH_API_BASE}/projects/{s.gh_project_number}/subscribers"
    resp = httpx.post(
        url,
        params={"subscriberId": s.gh_subscriber_id},
        json=body,
        headers={"Authorization": f"Bearer {project_access_token()}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_subscriber() -> dict | None:
    """Return the canonical project subscriber resource for our configured id, or None.

    Used after register_subscriber() to get the authoritative resource: create can return
    either the subscriber inline OR a long-running Operation (when Google runs async endpoint
    verification), so we never parse the create response — we re-read the known subscriber.

    The API exposes LIST but no GET-by-id route (a GET on .../subscribers/{id} returns a
    Google HTML 404), so we LIST and match on the resource name's trailing id.
    """
    s = get_settings()
    url = f"{HEALTH_API_BASE}/projects/{s.gh_project_number}/subscribers"
    resp = httpx.get(
        url,
        headers={"Authorization": f"Bearer {project_access_token()}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    suffix = f"/subscribers/{s.gh_subscriber_id}"
    for sub in resp.json().get("subscribers", []):
        if str(sub.get("name", "")).endswith(suffix):
            return sub
    return None


def list_subscriptions(subscriber_id: str) -> list[dict]:
    """List per-user subscriptions under the subscriber (project credentials). Verified shape.

    Each Subscription has `name`, `user` (= "users/{healthUserId}") and `dataTypes`. Useful
    after an AUTOMATIC enrollment to discover a subject's healthUserId from the `user` field.
    """
    s = get_settings()
    url = f"{HEALTH_API_BASE}/projects/{s.gh_project_number}/subscribers/{subscriber_id}/subscriptions"
    resp = httpx.get(
        url, headers={"Authorization": f"Bearer {project_access_token()}"}, timeout=_HTTP_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json().get("subscriptions", [])


def create_subscription(
    subscriber_id: str, health_user_id: str, data_types: list[str] | None = None
) -> dict:
    """Tier-2 (MANUAL policy only): create a per-user subscription. Returns the raw resource.

    Verified against the live API (2026-06-11):
      POST /v4/projects/{project-NUMBER}/subscribers/{subscriber}/subscriptions
      body (the Subscription resource itself): {"user": "users/{healthUserId}", "dataTypes":[...]}

    NOTES from verification:
      - `user` requires the public **healthUserId**, NOT the OAuth `sub` we store as
        `provider_user_id` (Google rejects the sub: "Invalid user ID segment"). The
        healthUserId is only available from webhook payloads or an auto-created
        subscription's `user` field — capture it before calling this.
      - Only works when the subscriber's `subscriptionCreatePolicy` is **MANUAL** for those
        data types. Under **AUTOMATIC** (current config) Google creates subscriptions itself
        on user consent and this call is unnecessary (and rejected).
    """
    s = get_settings()
    url = f"{HEALTH_API_BASE}/projects/{s.gh_project_number}/subscribers/{subscriber_id}/subscriptions"
    body: dict = {"user": f"users/{health_user_id}"}
    if data_types:
        body["dataTypes"] = data_types
    resp = httpx.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {project_access_token()}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()
