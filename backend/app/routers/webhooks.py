"""Webhook receiver for Google Health notifications.

Contract per https://developers.google.com/health/webhooks:

- **Auth:** the `endpointAuthorization.secret` we registered ("Bearer <WEBHOOK_SECRET>") is
  echoed verbatim in the inbound `Authorization` header. We reject anything that doesn't
  match with **401** — required, because Google's registration-time verification sends an
  *unauthorized* probe that MUST get 401/403 (and it stops forged notifications).
- **Verification handshake:** registering/updating a subscriber makes Google POST
  `{"type": "verification"}` twice (authorized → expect 200, unauthorized → expect 401).
  We answer 200 to the authorized probe without landing it.
- **Notifications:** real body is `{"data": {healthUserId, dataType, operation, intervals,
  clientProvidedSubscriptionName, version}}`. We land it in `health_data` and — following
  garminrec's rule — **return 200 even on internal error** so Google doesn't disable the
  subscription. (Auth failure is the one case we 401; a correctly-configured Google always
  sends the right secret, so that only fires for forgeries / the verification probe.)
"""

import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import HealthData, ProviderAccount
from app.providers import fitbit_gh

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _authorized(request: Request) -> bool:
    """True if the inbound Authorization header matches our registered secret.

    If WEBHOOK_SECRET is unset (dev), accept everything — but then the registration
    handshake's unauthorized probe can't be satisfied, so a real subscriber needs the
    secret set. Constant-time compare to avoid leaking the secret via timing.
    """
    secret = get_settings().webhook_secret
    if not secret:
        return True
    expected = f"Bearer {secret}"
    presented = request.headers.get("authorization", "")
    return hmac.compare_digest(presented, expected)


def _parse_dt(value) -> datetime | None:
    """Parse an ISO-8601 timestamp to naive UTC. Defensive: returns None on anything odd."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _interval_start(data: dict) -> datetime | None:
    """Earliest start time across the notification's `intervals`, if present."""
    intervals = data.get("intervals")
    if not isinstance(intervals, list):
        return None
    for iv in intervals:
        if isinstance(iv, dict):
            dt = _parse_dt(iv.get("startTime") or iv.get("start_time"))
            if dt:
                return dt
    return None


@router.post("/google-health")
async def google_health(request: Request, db: Session = Depends(get_db)) -> Response:
    """Receive a Google Health notification or verification probe.

    Returns 401 on bad/missing auth; 200 otherwise (even on internal processing error).
    """
    raw = await request.body()

    # Auth gate first — also satisfies the registration-time unauthorized probe.
    if not _authorized(request):
        return Response(status_code=401)

    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {"_unparsed": raw.decode("utf-8", "replace")}

    # Verification handshake: don't land it, just 200 the authorized probe.
    if isinstance(body, dict) and body.get("type") == "verification":
        log.info("Webhook verification probe received; acking 200")
        return Response(status_code=200)

    # Notification processing — never let an error reach Google (keeps the sub alive).
    try:
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            # Unknown shape — land verbatim rather than drop.
            db.add(HealthData(provider=fitbit_gh.NAME, payload=body))
            db.commit()
            return Response(status_code=200)

        health_user_id = data.get("healthUserId")
        acct = None
        if health_user_id:
            hid = str(health_user_id)
            # healthUserId (Google's public per-user id) is captured on provider_accounts via
            # /admin/subscriptions/sync; match on it, not the OAuth `sub`.
            acct = db.scalar(
                select(ProviderAccount).where(
                    ProviderAccount.provider == fitbit_gh.NAME,
                    ProviderAccount.health_user_id == hid,
                )
            )
            if acct is None:
                # First-webhook fallback link: if exactly one registered account still lacks a
                # healthUserId, this notification must be theirs. Same conservative rule as sync.
                candidates = list(
                    db.scalars(
                        select(ProviderAccount).where(
                            ProviderAccount.provider == fitbit_gh.NAME,
                            ProviderAccount.registered.is_(True),
                            ProviderAccount.health_user_id.is_(None),
                        )
                    )
                )
                if len(candidates) == 1:
                    acct = candidates[0]
                    acct.health_user_id = hid

        db.add(
            HealthData(
                provider_account_id=acct.id if acct else None,
                provider=fitbit_gh.NAME,
                datatype=data.get("dataType"),
                start_time=_interval_start(data),
                payload=body,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 — never let an error reach the provider
        log.exception("Error processing Google Health webhook; returning 200 regardless")
        db.rollback()

    return Response(status_code=200)
