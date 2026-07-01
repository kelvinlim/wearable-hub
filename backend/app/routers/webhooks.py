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

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import consolidation, garmin_ingest
from app.accounts import mark_revoked
from app.config import get_settings
from app.crypto import decrypt
from app.db import get_db
from app.models import GoogleCredentialSet, HealthData, ProviderAccount
from app.providers import fitbit_gh

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _authorized(request: Request, db: Session) -> tuple[bool, int | None]:
    """Match the inbound Authorization header against every known webhook secret — the global one
    and each credential set's. Returns (authorized, matched_credential_set_id | None); the matching
    secret identifies which GCP project the notification came from (None = global). A miss → not
    authorized (the caller 401s, which also satisfies Google's registration-time unauthorized
    probe). Constant-time compares to avoid leaking secrets via timing.

    If no global secret is set (dev) and no set matches, accept as global — but then the
    unauthorized probe can't be satisfied, so a real subscriber needs a secret set.
    """
    presented = request.headers.get("authorization", "")
    gsecret = get_settings().webhook_secret
    if gsecret and hmac.compare_digest(presented, f"Bearer {gsecret}"):
        return True, None
    for cs in db.scalars(
        select(GoogleCredentialSet).where(GoogleCredentialSet.webhook_secret.isnot(None))
    ):
        sec = decrypt(cs.webhook_secret)
        if sec and hmac.compare_digest(presented, f"Bearer {sec}"):
            return True, cs.id
    if not gsecret:  # dev: no global secret configured -> accept as the global project
        return True, None
    return False, None


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
    """Earliest start time across the notification's `intervals`, if present.

    Real shape (verified 2026-06-11): intervals[].physicalTimeInterval.startTime. Older/flat
    `startTime` is accepted as a fallback.
    """
    intervals = data.get("intervals")
    if not isinstance(intervals, list):
        return None
    for iv in intervals:
        if not isinstance(iv, dict):
            continue
        phys = iv.get("physicalTimeInterval")
        src = phys if isinstance(phys, dict) else iv
        dt = _parse_dt(src.get("startTime") or src.get("start_time"))
        if dt:
            return dt
    return None


def _resolve_account(db: Session, hid: str, set_id: int | None = None) -> "ProviderAccount | None":
    """Find the provider_account for a healthUserId, linking it on first sighting.

    Direct match on `health_user_id`; else the conservative fallback — scoped to the project the
    notification came from (`set_id`): if exactly one registered account pinned to that credential
    set still lacks a healthUserId, this notification is theirs, so bind it.
    """
    acct = db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.provider == fitbit_gh.NAME,
            ProviderAccount.health_user_id == hid,
        )
    )
    if acct:
        return acct
    candidates = list(
        db.scalars(
            select(ProviderAccount).where(
                ProviderAccount.provider == fitbit_gh.NAME,
                ProviderAccount.registered.is_(True),
                ProviderAccount.health_user_id.is_(None),
                ProviderAccount.credential_set_id == set_id,  # set_id None → global-pinned accounts
            )
        )
    )
    if len(candidates) == 1:
        candidates[0].health_user_id = hid
        return candidates[0]
    return None


@router.post("/google-health")
async def google_health(
    request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> Response:
    """Receive a Google Health notification or verification probe.

    Returns 401 on bad/missing auth; 200 otherwise (even on internal processing error).
    """
    raw = await request.body()

    # Auth gate first — also satisfies the registration-time unauthorized probe. The matching
    # secret tells us which project (credential set) this came from, scoping account resolution.
    authorized, set_id = _authorized(request, db)
    if not authorized:
        return Response(status_code=401)

    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {"_unparsed": raw.decode("utf-8", "replace")}

    # Verification handshake: don't land it, just 200 the authorized probe.
    if isinstance(body, dict) and body.get("type") == "verification":
        log.info("Webhook verification probe received; acking 200")
        return Response(status_code=200)

    # Inbound deregistration (BEST-EFFORT — shape unverified). Google's docs don't define an
    # account-level revocation webhook ("notifications simply stop" on consent withdrawal), so
    # we don't know the exact payload. Real data notifications are JSON *arrays*; only a dict
    # body carrying a deletion/deregistration signal triggers this, so it can't misfire on
    # normal data. We log loudly to capture the real shape if one ever arrives.
    if isinstance(body, dict):
        ntype = str(body.get("notificationType") or "").upper()
        if any(tok in ntype for tok in ("DELET", "DEREG", "REVOK")):
            log.warning("Inbound deregistration-like notification (verify shape): %s", body)
            hid = body.get("healthUserId") or body.get("userId")
            if hid:
                acct = db.scalar(
                    select(ProviderAccount).where(
                        ProviderAccount.provider == fitbit_gh.NAME,
                        ProviderAccount.health_user_id == str(hid),
                    )
                )
                if acct:
                    mark_revoked(db, acct)
                    db.commit()
            return Response(status_code=200)

    # Notification processing — never let an error reach Google (keeps the sub alive).
    # Verified shape: the body is a JSON ARRAY of {"data": {...}} items (we also accept a lone
    # dict). Land one health_data row per item; link by healthUserId (cached per request).
    try:
        if isinstance(body, list):
            items = body
        elif isinstance(body, dict) and isinstance(body.get("data"), dict):
            items = [body]
        else:
            items = []

        if not items:
            # Unknown shape — land verbatim rather than drop.
            db.add(HealthData(provider=fitbit_gh.NAME, payload=body))
            db.commit()
            return Response(status_code=200)

        acct_cache: dict[str, int | None] = {}
        dirty: dict[int, set] = {}  # account_id -> set of local dates touched
        for item in items:
            data = item.get("data") if isinstance(item, dict) else None
            if not isinstance(data, dict):
                db.add(HealthData(provider=fitbit_gh.NAME, payload=item))
                continue
            acct_id: int | None = None
            hid = data.get("healthUserId")
            if hid:
                hid = str(hid)
                if hid not in acct_cache:
                    acct = _resolve_account(db, hid, set_id)
                    acct_cache[hid] = acct.id if acct else None
                acct_id = acct_cache[hid]
            db.add(
                HealthData(
                    provider_account_id=acct_id,
                    provider=fitbit_gh.NAME,
                    datatype=data.get("dataType"),
                    start_time=_interval_start(data),
                    payload=item,
                )
            )
            if acct_id is not None:
                dirty.setdefault(acct_id, set()).update(consolidation.affected_local_dates(item))
        db.commit()

        # Real-time consolidation: mark the touched subject-days dirty (durable queue) and
        # drain them in the background, AFTER the fast 200 — keeps the webhook contract.
        for account_id, dates in dirty.items():
            if dates:
                consolidation.mark_dirty(db, account_id, dates)
        if any(dates for dates in dirty.values()):
            background_tasks.add_task(consolidation.run_due_background)
    except Exception:  # noqa: BLE001 — never let an error reach the provider
        log.exception("Error processing Google Health webhook; returning 200 regardless")
        db.rollback()

    return Response(status_code=200)


@router.post("/garmin/{datatype}")
async def garmin_push(datatype: str, request: Request, db: Session = Depends(get_db)) -> Response:
    """Receive a Garmin push for one summary type. Always 200 (even on error) so Garmin keeps
    the subscription alive.

    Garmin POSTs the actual values, so there's no pull step: we land + aggregate inline (local
    compute only, no outbound calls). A `deregistrations` push marks the account unregistered.
    Garmin pushes aren't secret-authenticated (the registered URL is the trust boundary), so no
    auth gate here — unlike the Google handler.
    """
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {"_unparsed": raw.decode("utf-8", "replace")}

    try:
        if datatype == "deregistrations" or (isinstance(body, dict) and "deregistrations" in body):
            _garmin_deregister(db, body)
            return Response(status_code=200)
        garmin_ingest.ingest_push(db, datatype, body)
    except Exception:  # noqa: BLE001 — never let an error reach Garmin
        log.exception("Error processing Garmin %s push; returning 200 regardless", datatype)
        db.rollback()

    return Response(status_code=200)


def _garmin_deregister(db: Session, body: dict) -> None:
    """Mark each deregistered Garmin account unregistered (resolve by userId). Best-effort."""
    items = body.get("deregistrations") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        # Land the raw event, then flip the account.
        db.add(HealthData(provider="garmin", datatype="deregistrations", payload=item))
        acct = garmin_ingest.resolve_account(db, item)
        if acct:
            mark_revoked(db, acct)
    db.commit()
