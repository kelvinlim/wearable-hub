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
  - `stress` / `stressDetails`: avg/max + per-band durations from timeOffsetStressLevelValues; the
    same push also carries body battery (`timeOffsetBodyBatteryValues`) -> metrics["body_battery"].
  - `epochs`: ~15-min activity slices -> intraday `steps` points (the only Garmin within-day steps).
  - `pulseox` / `pulseOx`: avg SpO2 % from timeOffsetSpo2Values (-> spo2_avg).
  - `respiration`: avg/min/max breaths/min from timeOffsetEpochToBreaths.
  - `bodyComps`: weight/BMI/body fat/water/muscle/bone.
  - `userMetrics`: VO2max + fitness age.
  - `skinTemp` / `skinTemperature`: overnight skin-temp deviation from baseline (°C, sleep-only).
  - everything else: landed raw (no daily mapping).
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
    # Most summaries carry startTime*; body composition carries measurementTime* instead.
    start = item.get("startTimeInSeconds")
    off = item.get("startTimeOffsetInSeconds")
    if start is None:
        start = item.get("measurementTimeInSeconds")
        off = item.get("measurementTimeOffsetInSeconds")
    if start is None:
        return None
    try:
        return datetime.fromtimestamp(int(start) + int(off or 0), tz=timezone.utc).date()
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


def _merge_submetric(row: DailyHealth, key: str, updates: dict) -> None:
    """Merge `updates` into the metrics[key] sub-dict, preserving fields other pushes set.

    Body battery is split across two pushes — `dailies` carries charged/drained, `stressDetails`
    carries the intraday levels — so each must update its own portion without clobbering the other.
    """
    metrics = dict(row.metrics or {})
    sub = dict(metrics.get(key) or {})
    sub.update(updates)
    metrics[key] = sub
    row.metrics = metrics


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _summarize_offsets(values) -> dict | None:
    """Avg/min/max/count over a Garmin `timeOffset*` -> value map.

    These maps key seconds-from-start to a reading (stress level, SpO2 %, breaths/min). Garmin
    uses negative sentinels (-1 = unable to measure, -2 = insufficient data); drop them and any
    non-numeric value. Returns None if nothing usable remains.
    """
    if not isinstance(values, dict):
        return None
    nums = [n for n in (_num(v) for v in values.values()) if n is not None and n >= 0]
    if not nums:
        return None
    return {
        "avg": round(sum(nums) / len(nums), 1),
        "min": min(nums),
        "max": max(nums),
        "count": len(nums),
    }


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
    # Body battery daily charge/drain lives on the dailies summary (intraday levels come via stress).
    charged = _num(item.get("bodyBatteryChargedValue"))
    drained = _num(item.get("bodyBatteryDrainedValue"))
    if charged is not None or drained is not None:
        _merge_submetric(row, "body_battery", {"charged": charged, "drained": drained})
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


def _apply_stress(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Stress Details push -> metrics["stress"]. Headline avg/max prefer Garmin's own fields,
    else are computed from `timeOffsetStressLevelValues`."""
    row = _get_or_create_daily(db, account, d)
    summary = _summarize_offsets(item.get("timeOffsetStressLevelValues"))
    avg = _num(item.get("averageStressLevel"))
    if avg is None or avg < 0:
        avg = summary["avg"] if summary else None
    mx = _num(item.get("maxStressLevel"))
    if mx is None or mx < 0:
        mx = summary["max"] if summary else None
    _merge_metrics(row, "stress", {
        "avg": avg,
        "max": mx,
        "duration_seconds": _num(item.get("stressDurationInSeconds")),
        "rest_seconds": _num(item.get("restStressDurationInSeconds")),
        "low_seconds": _num(item.get("lowStressDurationInSeconds")),
        "medium_seconds": _num(item.get("mediumStressDurationInSeconds")),
        "high_seconds": _num(item.get("highStressDurationInSeconds")),
        "raw": item,
    })
    # Body battery rides the stress push: intraday levels in `timeOffsetBodyBatteryValues`.
    bb = _body_battery_summary(item.get("timeOffsetBodyBatteryValues"))
    if bb:
        _merge_submetric(row, "body_battery", bb)
    row.pulled_at = datetime.utcnow()

    study = _study_for(db, account)
    if study and study.ingest_intraday_stress:
        _store_intraday_stress(db, account, d, item)
        _store_intraday_body_battery(db, account, d, item)
        row.point_count = _count_points(db, account.id, d)


def _apply_pulseox(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Pulse Ox push -> spo2_avg column (typed) + metrics["spo2"] detail."""
    row = _get_or_create_daily(db, account, d)
    summary = _summarize_offsets(item.get("timeOffsetSpo2Values"))
    if summary:
        row.spo2_avg = float(summary["avg"])
    _merge_metrics(row, "spo2", {**(summary or {}), "on_demand": item.get("onDemand"), "raw": item})
    row.pulled_at = datetime.utcnow()


def _apply_respiration(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """All-day respiration push -> metrics["respiration"] (avg/min/max breaths per minute)."""
    row = _get_or_create_daily(db, account, d)
    summary = _summarize_offsets(item.get("timeOffsetEpochToBreaths"))
    _merge_metrics(row, "respiration", {**(summary or {}), "raw": item})
    row.pulled_at = datetime.utcnow()


def _apply_body_comp(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Body Composition push -> metrics["body_composition"]. Weight normalized grams -> kg."""
    row = _get_or_create_daily(db, account, d)
    weight_g = _num(item.get("weightInGrams"))
    _merge_metrics(row, "body_composition", {
        "weight_kg": round(weight_g / 1000, 2) if weight_g is not None else None,
        "bmi": _num(item.get("bodyMassIndex")),
        "body_fat_percent": _num(item.get("bodyFatInPercent")),
        "body_water_percent": _num(item.get("bodyWaterInPercent")),
        "muscle_mass_g": _num(item.get("muscleMassInGrams")),
        "bone_mass_g": _num(item.get("boneMassInGrams")),
        "raw": item,
    })
    row.pulled_at = datetime.utcnow()


def _apply_user_metrics(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """User Metrics push -> metrics["user_metrics"] (VO2max, fitness age)."""
    row = _get_or_create_daily(db, account, d)
    _merge_metrics(row, "user_metrics", {
        "vo2_max": _num(item.get("vo2Max")),
        "vo2_max_cycling": _num(item.get("vo2MaxCycling")),
        "fitness_age": _num(item.get("fitnessAge")),
        "raw": item,
    })
    row.pulled_at = datetime.utcnow()


def _apply_skin_temp(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Skin Temperature push -> metrics["skin_temp"].

    Garmin reports overnight wrist skin temperature as a **deviation from the user's learned
    baseline** (°C), not an absolute temperature, over the sleep window. Field naming varies by
    payload version (`avgDeviationCelsius` / `deviationCelsius` / `averageDeviationCelsius`); take
    the first present. Sleep-only, one summary per night.
    """
    row = _get_or_create_daily(db, account, d)
    deviation = next(
        (
            _num(item.get(k))
            for k in ("avgDeviationCelsius", "averageDeviationCelsius", "deviationCelsius")
            if _num(item.get(k)) is not None
        ),
        None,
    )
    _merge_metrics(row, "skin_temp", {
        "deviation_c": deviation,
        "min_deviation_c": _num(item.get("minDeviationCelsius")),
        "max_deviation_c": _num(item.get("maxDeviationCelsius")),
        "duration_seconds": _num(item.get("durationInSeconds")),
        "raw": item,
    })
    row.pulled_at = datetime.utcnow()


def _apply_epochs(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Garmin epoch (~15-min activity slice) -> intraday `steps` point (opt-in `ingest_intraday_activity`).

    Epochs are the only Garmin source of within-day steps — `dailies` carries the day total only. Each
    epoch is stored as one point spanning its own window (value = steps; distance/intensity/type kept
    in the payload). Idempotent on the epoch start, so re-pushes self-heal. Daily totals still come
    from `dailies`. ingest_push processes one epoch item per call.
    """
    study = _study_for(db, account)
    if not (study and study.ingest_intraday_activity):
        return
    steps = _num(item.get("steps"))
    start = item.get("startTimeInSeconds")
    if steps is None or start is None:
        return
    dur = _num(item.get("durationInSeconds")) or 0
    off = item.get("startTimeOffsetInSeconds") or 0
    bstart = datetime.fromtimestamp(int(start), tz=timezone.utc).replace(tzinfo=None)
    bend = datetime.fromtimestamp(int(start) + int(dur), tz=timezone.utc).replace(tzinfo=None)
    dailywrite.upsert_point(
        db,
        account.id,
        "steps",
        d,
        point_key=f"steps|{bstart.isoformat()}",
        start=bstart,
        end=bend,
        tz_off=int(off),
        value=steps,
        payload={
            "steps": steps,
            "distance_m": _num(item.get("distanceInMeters")),
            "active_kcal": _num(item.get("activeKilocalories")),
            "intensity": item.get("intensity"),
            "activity_type": item.get("activityType"),
        },
    )
    row = _get_or_create_daily(db, account, d)
    row.point_count = _count_points(db, account.id, d)


def _store_intraday_avg(
    db: Session, account: ProviderAccount, d: date, item: dict,
    *, source_field: str, datatype: str, bucket_min: int, avg_key: str,
) -> None:
    """Bucket a Garmin `timeOffset*` -> value map into N-min averages and upsert as `datatype` points.

    Keys are seconds from `startTimeInSeconds`; Garmin's negative sentinels (-1/-2) are dropped.
    Shared by intraday HR / stress / body battery — all the same shape, so the console's generic
    point-series view renders each as an over-time table.
    """
    samples = item.get(source_field)
    start = item.get("startTimeInSeconds")
    if not isinstance(samples, dict) or start is None:
        return
    bucket_min = max(1, bucket_min or 1)
    off = item.get("startTimeOffsetInSeconds") or 0
    buckets: dict[int, list[int]] = {}
    for k, raw in samples.items():
        try:
            sec = int(start) + int(k)
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val < 0:  # -1 unable to measure, -2 insufficient data
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
            datatype,
            d,
            point_key=f"{datatype}|{bstart.isoformat()}",
            start=bstart,
            end=bend,
            tz_off=int(off),
            value=round(avg, 1),
            payload={avg_key: round(avg, 1), "samples": len(vals), "bucket_minutes": bucket_min},
        )


def _store_intraday_hr(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Intraday HR from `dailies.timeOffsetHeartRateSamples` -> `heart_rate` points."""
    _store_intraday_avg(
        db, account, d, item,
        source_field="timeOffsetHeartRateSamples", datatype="heart_rate",
        bucket_min=get_settings().hr_downsample_minutes, avg_key="bpm_avg",
    )


def _store_intraday_stress(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Intraday stress from the stress push's `timeOffsetStressLevelValues` -> `stress` points."""
    _store_intraday_avg(
        db, account, d, item,
        source_field="timeOffsetStressLevelValues", datatype="stress",
        bucket_min=get_settings().stress_downsample_minutes, avg_key="stress_avg",
    )


def _store_intraday_body_battery(db: Session, account: ProviderAccount, d: date, item: dict) -> None:
    """Intraday body battery from the stress push's `timeOffsetBodyBatteryValues` -> `body_battery`
    points (0-100). Rides the same push + opt-in as stress."""
    _store_intraday_avg(
        db, account, d, item,
        source_field="timeOffsetBodyBatteryValues", datatype="body_battery",
        bucket_min=get_settings().stress_downsample_minutes, avg_key="body_battery_avg",
    )


def _body_battery_summary(values) -> dict | None:
    """min / max / latest body-battery level (0-100) from a `timeOffset* -> value` map.

    `latest` is the value at the largest time offset (the day's most recent reading).
    """
    if not isinstance(values, dict):
        return None
    pairs = []
    for k, v in values.items():
        n = _num(v)
        if n is None or n < 0:
            continue
        try:
            pairs.append((int(k), n))
        except (TypeError, ValueError):
            continue
    if not pairs:
        return None
    pairs.sort()
    levels = [v for _, v in pairs]
    return {"min": min(levels), "max": max(levels), "latest": pairs[-1][1]}


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


# Garmin datatype (body key / URL path) -> applier. The body's top-level key wins; the URL slug is
# only a fallback hint, so register every plausible spelling. HRV is `hrv` in the prior art; newer
# docs use `hrvSummary`. Stress pushes under `stressDetails`; Pulse Ox casing varies (`pulseox` /
# `pulseOx`).
_APPLIERS = {
    "dailies": _apply_dailies,
    "sleeps": _apply_sleep,
    "hrv": _apply_hrv,
    "hrvSummary": _apply_hrv,
    "stress": _apply_stress,
    "stressDetails": _apply_stress,
    "pulseox": _apply_pulseox,
    "pulseOx": _apply_pulseox,
    "respiration": _apply_respiration,
    "bodyComps": _apply_body_comp,
    "userMetrics": _apply_user_metrics,
    "skinTemp": _apply_skin_temp,
    "skinTemperature": _apply_skin_temp,
    "epochs": _apply_epochs,
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
