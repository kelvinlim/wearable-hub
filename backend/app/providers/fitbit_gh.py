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
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.providers.base import TokenResult

if TYPE_CHECKING:
    from app.providers.gh_creds import GHCreds

NAME = "fitbit_gh"

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
HEALTH_API_BASE = "https://health.googleapis.com/v4"

_HTTP_TIMEOUT = 30.0


class GrantRevokedError(RuntimeError):
    """The user's OAuth grant is no longer valid (revoked, or refresh returned invalid_grant)."""


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

def build_authorization_url(creds: "GHCreds", state: str, code_challenge: str) -> str:
    """Build the subject OAuth authorize URL for the given (resolved) credential set."""
    params = {
        "response_type": "code",
        "client_id": creds.client_id,
        "redirect_uri": creds.redirect_uri,
        "scope": creds.scopes,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",  # request a refresh token
        "prompt": "consent",       # force the consent screen so the refresh token is re-issued
        "include_granted_scopes": "true",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def exchange(creds: "GHCreds", code: str, code_verifier: str) -> TokenResult:
    """Exchange an authorization code for tokens (Google token endpoint)."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "redirect_uri": creds.redirect_uri,
    }
    resp = httpx.post(TOKEN_ENDPOINT, data=data, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return _to_result(resp.json())


def refresh(creds: "GHCreds", refresh_token: str) -> TokenResult:
    """Refresh an access token against the credential set that issued it. Google usually omits a
    new refresh_token; the caller should keep the existing one when the result's is None.
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }
    resp = httpx.post(TOKEN_ENDPOINT, data=data, timeout=_HTTP_TIMEOUT)
    # A revoked grant fails refresh with 400 invalid_grant — surface it as a typed signal so
    # callers can mark the account unregistered rather than retrying a dead token.
    if resp.status_code == 400 and "invalid_grant" in resp.text:
        raise GrantRevokedError("refresh_token rejected (invalid_grant): grant revoked")
    resp.raise_for_status()
    return _to_result(resp.json())


def revoke(token: str) -> None:
    """Revoke an OAuth token (and thus its grant) at Google. Idempotent.

    A token Google no longer recognizes returns 400 — treat that as already-revoked rather
    than an error, so re-revoking is safe.
    """
    resp = httpx.post(REVOKE_ENDPOINT, data={"token": token}, timeout=_HTTP_TIMEOUT)
    if resp.status_code not in (200, 400):
        resp.raise_for_status()


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


def project_access_token(creds: "GHCreds") -> str:
    """Mint an access token for project-level calls from the credential set's service account.

    Uses `creds.sa_json` (the set's SA) if present; else the global GH_SA_CREDENTIALS_FILE; else
    Application Default Credentials. Raises ProjectCredentialsError when nothing is configured.
    """
    s = get_settings()
    scopes = s.gh_sa_scopes.split()
    try:
        import google.auth
        import google.auth.transport.requests
        from google.auth.exceptions import DefaultCredentialsError
        from google.oauth2 import service_account

        if creds.sa_json:
            sa_creds = service_account.Credentials.from_service_account_info(
                creds.sa_json, scopes=scopes
            )
        elif s.gh_sa_credentials_file:
            sa_creds = service_account.Credentials.from_service_account_file(
                s.gh_sa_credentials_file, scopes=scopes
            )
        else:
            try:
                sa_creds, _ = google.auth.default(scopes=scopes)
            except DefaultCredentialsError as exc:
                raise ProjectCredentialsError(
                    "No project credentials: add a service-account JSON to the credential set, "
                    "set GH_SA_CREDENTIALS_FILE, or provide Application Default Credentials."
                ) from exc
        sa_creds.refresh(google.auth.transport.requests.Request())
        return sa_creds.token
    except ProjectCredentialsError:
        raise
    except FileNotFoundError as exc:
        raise ProjectCredentialsError(
            f"GH_SA_CREDENTIALS_FILE not found: {s.gh_sa_credentials_file}"
        ) from exc


def register_subscriber(creds: "GHCreds") -> dict:
    """Tier-1: register the credential set's project webhook subscriber. Idempotent.

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
    if not creds.project_number:
        raise ProjectCredentialsError("project number is not set (subscriber API needs it).")

    config: dict = {"subscriptionCreatePolicy": creds.subscription_policy}
    data_types = creds.subscription_data_types.split()
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
        "endpointUri": get_settings().webhook_public_url,  # shared across projects (match-any-secret)
        "subscriberConfigs": [config],
        "endpointAuthorization": {"secret": f"Bearer {creds.webhook_secret}"},
    }
    url = f"{HEALTH_API_BASE}/projects/{creds.project_number}/subscribers"
    resp = httpx.post(
        url,
        params={"subscriberId": creds.subscriber_id},
        json=body,
        headers={"Authorization": f"Bearer {project_access_token(creds)}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_subscriber(creds: "GHCreds") -> dict | None:
    """Return the canonical project subscriber resource for our configured id, or None.

    Used after register_subscriber() to get the authoritative resource: create can return
    either the subscriber inline OR a long-running Operation (when Google runs async endpoint
    verification), so we never parse the create response — we re-read the known subscriber.

    The API exposes LIST but no GET-by-id route (a GET on .../subscribers/{id} returns a
    Google HTML 404), so we LIST and match on the resource name's trailing id.
    """
    url = f"{HEALTH_API_BASE}/projects/{creds.project_number}/subscribers"
    resp = httpx.get(
        url,
        headers={"Authorization": f"Bearer {project_access_token(creds)}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    suffix = f"/subscribers/{creds.subscriber_id}"
    for sub in resp.json().get("subscribers", []):
        if str(sub.get("name", "")).endswith(suffix):
            return sub
    return None


def list_subscriptions(creds: "GHCreds", subscriber_id: str) -> list[dict]:
    """List per-user subscriptions under the subscriber (project credentials). Verified shape.

    Each Subscription has `name`, `user` (= "users/{healthUserId}") and `dataTypes`. Useful
    after an AUTOMATIC enrollment to discover a subject's healthUserId from the `user` field.
    """
    url = f"{HEALTH_API_BASE}/projects/{creds.project_number}/subscribers/{subscriber_id}/subscriptions"
    resp = httpx.get(
        url, headers={"Authorization": f"Bearer {project_access_token(creds)}"}, timeout=_HTTP_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json().get("subscriptions", [])


def parse_health_user_id(subscription: dict) -> str | None:
    """Extract the bare healthUserId from a subscription's `user` field ("users/{id}")."""
    user = subscription.get("user") or ""
    return user.split("/", 1)[1] if user.startswith("users/") else (user or None)


def create_subscription(
    creds: "GHCreds", subscriber_id: str, health_user_id: str, data_types: list[str] | None = None
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
    url = f"{HEALTH_API_BASE}/projects/{creds.project_number}/subscribers/{subscriber_id}/subscriptions"
    body: dict = {"user": f"users/{health_user_id}"}
    if data_types:
        body["dataTypes"] = data_types
    resp = httpx.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {project_access_token(creds)}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def list_paired_devices(access_token: str) -> list[dict]:
    """The subject's paired trackers/scales (HealthProfile service). Uses the SUBJECT's token.

    GET /v4/users/me/pairedDevices?pageSize=100 — profile data, not a dataType; needs the
    `…/auth/googlehealth.settings.readonly` scope on the subject grant. Each PairedDevice has
    `name`, `deviceType` (TRACKER|SCALE), `batteryLevel`, `batteryStatus` (High|Medium|Low|Empty),
    `lastSyncTime`, `deviceVersion`, `macAddress`, `features[]`. Paginated; returns all pages.
    """
    url = f"{HEALTH_API_BASE}/users/me/pairedDevices"
    out: list[dict] = []
    page_token: str | None = None
    for _ in range(20):  # safety bound (default page 5, max 100; few devices in practice)
        params = {"pageSize": "100"}
        if page_token:
            params["pageToken"] = page_token
        resp = httpx.get(
            url, params=params, headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        j = resp.json()
        out.extend(j.get("pairedDevices") or [])
        page_token = j.get("nextPageToken")
        if not page_token:
            break
    return out
