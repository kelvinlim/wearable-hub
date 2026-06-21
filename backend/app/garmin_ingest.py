"""Ingest Garmin push payloads into the provider-agnostic data tables.

Garmin POSTs the actual values (unlike Google's value-less notifications), so there is no pull
step. For each pushed item we:
  1. land it raw in `health_data` (`provider='garmin'`),
  2. resolve the owning `provider_account` by Garmin `userId`,
  3. merge its contribution into that (account, local_date)'s `daily_health` row and, for HR,
     into `health_data_points`.

The merge is **per-datatype and idempotent**: a `dailies` push owns steps/distance/calories/
floors/HR, `sleeps` owns sleep, `hrv` owns hrv_ms — re-pushing a datatype overwrites only its own
fields, so re-sends self-heal and different datatypes never clobber each other. Mapping per
docs/garmin-integration-plan.md; everything not mapped is still landed raw for later.

Garmin shapes (Health API summary endpoints; prior art garminrec/db_code2.py:475-509):
  - `dailies`: steps, distanceInMeters, active/bmr Kilocalories, floorsClimbed, *HeartRate*,
    and intraday HR via `timeOffsetHeartRateSamples` ({seconds-from-start: bpm}).
  - `sleeps`: deep/light/rem/awake DurationInSeconds (+ durationInSeconds total).
  - `hrv` / `hrvSummary`: lastNightAvg (ms).
  - `epochs` and the rest: landed raw (no daily mapping in v1).
"""

import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import dailywrite
from app.config import get_settings
from app.models import (
    DailyHealth,
    HealthData,
    HealthDataPoint,
    ProviderAccount,
    Study,
    Subject,
)
from app.providers import garmin

log = logging.getLogger(__name__)


# --- helpers --------------------------------------------------------------------

def _grouped_items(body, datatype_hint: str) -> dict[str, list]:
    """Normalize a push body to {garmin_datatype: [items]}.

    Garmin posts `{"dailies": [ ... ]}`; the top-level key is the datatype. Fall back to the URL
    path hint for odd shapes (bare list / dict item).
    """
    if isinstance(body, dict) and body and all(isinstance(v, list) for v in body.values()):
        return {k: v for k, v in body.items()}
    if isinstance(body, list):
        return {datatype_hint: body}
    if isinstance(body, dict):
        return {datatype_hint: [body]}
    return {}


def _utc_start(item: dict) -> datetime | None:
    start = item.get("startTimeInSeconds") or (item.get("summary") or {}).get("startTimeInSeconds")
    if start is None:
        return None
    try:
        return datetime.fromtimestamp(int(start), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _local_date(item: dict) -> date | None:
    """Local calendar day for an item: prefer Garmin's `calendarDate`, else start+offset."""
    cal = item.get("calendarDate")
    if isinstance(cal, str):
        try:
            return date.fromisoformat(cal)
        except ValueError:
            pass
    start = item.get("startTimeInSeconds")
    if start is None:
        return None
    off = item.get("startTimeOffsetInSeconds") or 0
    try:
        return datetime.fromtimestamp(int(start) + int(off), tz=timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


def resolve_account(db: Session, item: dict) -> ProviderAccount | None:
    """Find the Garmin provider_account for a push item, by `userId`.

    Direct match on `provider_user_id`; else the conservative fallback — if exactly one registered
    Garmin account still lacks a userId, this push is theirs, so bind it (mirrors the Fitbit
    healthUserId fallback in webhooks.py).
    """
    user_id = item.get("userId")
    if user_id is not None:
        acct = db.scalar(
            select(ProviderAccount).where(
                ProviderAccount.provider == garmin.NAME,
                ProviderAccount.provider_user_id == str(user_id),
            )
        )
        if acct:
            return acct
    candidates = list(
        db.scalars(
            select(ProviderAccount).where(
                ProviderAccount.provider == garmin.NAME,
                ProviderAccount.registered.is_(True),
                ProviderAccount.provider_user_id.is_(None),
            )
        )
    )
    if len(candidates) == 1:
        if user_id is not None:
            candidates[0].provider_user_id = str(user_id)
        return candidates[0]
    return None


def _study_for(db: Session, account: ProviderAccount) -> Study | None:
    subj = db.get(Subject, account.subject_id)
    return db.get(Study, subj.study_id) if subj else None


def _get_or_create_daily(db: Session, account: ProviderAccount, d: date) -> DailyHealth:
    row = db.scalar(
        select(DailyHealth).where(
            DailyHealth.provider_account_id == account.id,
            DailyHealth.local_date == d,
        )
    )
    if row is None:
        row = DailyHealth(provider_account_id=account.id, subject_id=account.subject_id, local_date=d)
        db.add(row)
        db.flush()  # autoflush=False: make this row visible to same-run sibling pushes
    return row


def _merge_metrics(row: DailyHealth, key: str, value) -> None:
    """Set metrics[key]=value, reassigning the dict so SQLAlchemy sees the JSON change."""
    metrics = dict(row.metrics or {})
    metrics[key] = value
    row.metrics = metrics


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


# --- per-datatype appliers ------------------------------------------------------

def _apply_dailies(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    row = _get_or_create_daily(db, account, d)
    off = item.get("startTimeOffsetInSeconds")
    if off is not None:
        row.tz_offset_seconds = int(off)
    row.steps = _num(item.get("steps"))
    dist = _num(item.get("distanceInMeters"))
    row.distance_m = float(dist) if dist is not None else None
    active = _num(item.get("activeKilocalories")) or 0
    bmr = _num(item.get("bmrKilocalories")) or 0
    row.calories = float(active + bmr) if (item.get("activeKilocalories") is not None
                                           or item.get("bmrKilocalories") is not None) else None
    row.floors = _num(item.get("floorsClimbed"))
    row.resting_hr = _num(item.get("restingHeartRateInBeatsPerMinute"))
    row.hr_avg = _num(item.get("averageHeartRateInBeatsPerMinute"))
    _merge_metrics(row, "dailies", item)
    row.pulled_at = datetime.utcnow()

    study = _study_for(db, account)
    if study and study.ingest_intraday_hr:
        _store_intraday_hr(db, account, d, item)
    row.point_count = _count_points(db, account.id, d)


def _apply_sleep(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    row = _get_or_create_daily(db, account, d)
    deep = _num(item.get("deepSleepDurationInSeconds"))
    light = _num(item.get("lightSleepDurationInSeconds"))
    rem = _num(item.get("remSleepInSeconds"))
    awake = _num(item.get("awakeDurationInSeconds"))
    asleep = sum(v for v in (deep, light, rem) if v is not None)
    if deep is None and light is None and rem is None:
        total = _num(item.get("durationInSeconds"))
        row.sleep_minutes = int(total // 60) if total is not None else None
    else:
        row.sleep_minutes = int(asleep // 60)
    _merge_metrics(
        row,
        "sleep",
        {
            "stages": {
                "deep_minutes": deep // 60 if deep is not None else None,
                "light_minutes": light // 60 if light is not None else None,
                "rem_minutes": rem // 60 if rem is not None else None,
                "awake_minutes": awake // 60 if awake is not None else None,
            },
            "raw": item,
        },
    )
    row.pulled_at = datetime.utcnow()


def _apply_hrv(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    row = _get_or_create_daily(db, account, d)
    avg = _num(item.get("lastNightAvg")) or _num(item.get("hrvAverage"))
    row.hrv_ms = float(avg) if avg is not None else None
    _merge_metrics(row, "hrv", item)
    row.pulled_at = datetime.utcnow()


def _store_intraday_hr(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Write Garmin intraday HR (dailies.timeOffsetHeartRateSamples) as N-min average buckets.

    Keys are seconds from `startTimeInSeconds`; values are bpm. Bucketed to
    `hr_downsample_minutes` averages and stored as `heart_rate` points — same shape as the Fitbit
    intraday-HR path, so the console's HR view works unchanged.
    """
    samples = item.get("timeOffsetHeartRateSamples")
    start = item.get("startTimeInSeconds")
    if not isinstance(samples, dict) or start is None:
        return
    bucket_min = max(1, get_settings().hr_downsample_minutes or 1)
    off = item.get("startTimeOffsetInSeconds") or 0
    buckets: dict[int, list[int]] = {}
    for k, bpm in samples.items():
        try:
            sec = int(start) + int(k)
            val = int(bpm)
        except (TypeError, ValueError):
            continue
        bkt = sec - (sec % (bucket_min * 60))
        buckets.setdefault(bkt, []).append(val)
    for bkt_epoch, vals in buckets.items():
        avg = sum(vals) / len(vals)
        bstart = datetime.fromtimestamp(bkt_epoch, tz=timezone.utc).replace(tzinfo=None)
        bend = datetime.fromtimestamp(bkt_epoch + bucket_min * 60, tz=timezone.utc).replace(tzinfo=None)
        dailywrite.upsert_point(
            db,
            account.id,
            "heart_rate",
            d,
            point_key=f"heart_rate|{bstart.isoformat()}",
            start=bstart,
            end=bend,
            tz_off=int(off),
            value=round(avg, 1),
            payload={"bpm_avg": round(avg, 1), "samples": len(vals), "bucket_minutes": bucket_min},
        )


def _count_points(db: Session, account_id: int, d: date) -> int:
    return (
        db.scalar(
            select(func.count(HealthDataPoint.id)).where(
                HealthDataPoint.provider_account_id == account_id,
                HealthDataPoint.local_date == d,
            )
        )
        or 0
    )


# Garmin datatype (body key / URL path) -> applier. HRV is `hrv` in the prior art; newer docs use
# `hrvSummary`, so accept both.
_APPLIERS = {
    "dailies": _apply_dailies,
    "sleeps": _apply_sleep,
    "hrv": _apply_hrv,
    "hrvSummary": _apply_hrv,
}


# --- entry point ----------------------------------------------------------------

def ingest_push(db: Session, datatype_hint: str, body) -> dict[int, ProviderAccount]:
    """Land + aggregate one push body. Commits. Returns {account_id: account} for those touched.

    Never raises on a single bad item — the webhook contract requires a fast 200.
    """
    touched: dict[int, ProviderAccount] = {}
    for datatype, items in _grouped_items(body, datatype_hint).items():
        applier = _APPLIERS.get(datatype)
        for item in items:
            if not isinstance(item, dict):
                continue
            account = resolve_account(db, item)
            db.add(
                HealthData(
                    provider_account_id=account.id if account else None,
                    provider=garmin.NAME,
                    datatype=datatype,
                    start_time=_utc_start(item),
                    payload={datatype: [item]},
                )
            )
            if account is None or applier is None:
                continue
            d = _local_date(item)
            if d is None:
                continue
            try:
                applier(db, account, d, item)
                touched[account.id] = account
            except Exception:  # noqa: BLE001 — one bad item shouldn't drop the rest
                log.exception("Garmin %s aggregation failed for account %s", datatype, account.id)
    db.commit()
    return touched
