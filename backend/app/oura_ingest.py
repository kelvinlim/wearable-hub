"""Oura pull-side consolidation: one subject-day -> `daily_health` (+ intraday points).

Oura is a hybrid of the two existing providers: like Google, webhook events carry no
values (so each touched day is *pulled*); unlike Google, everything comes from plain
usercollection reads keyed by Oura's local calendar `day` field — no rollup API, no
timezone probing (the offset rides on the documents' timestamps).

Token handling differs from consolidation._fresh_token on purpose: Oura refresh tokens
are SINGLE-USE (each refresh rotates the pair and kills the old one), so the rotated
tokens are committed immediately after refresh — before any data call — because losing
a rotation to a later rollback would orphan the grant permanently. Refreshes are also
skipped while the access token is still fresh instead of running on every trigger.
"""

import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.consolidation import (
    _get_or_create_state,
    _outside_collection_window,
    _replace_points_for_day,
)
from app.crypto import decrypt, encrypt
from app.dailywrite import upsert_daily, upsert_point
from app.models import ConsolidationState, DailyHealth, ProviderAccount, Study, Subject
from app.providers import oura

log = logging.getLogger("oura_ingest")

_REFRESH_MARGIN = timedelta(minutes=5)


# --- time helpers ----------------------------------------------------------------

def _parse_ts(value) -> datetime | None:
    """Oura ISO timestamp (with offset) -> naive UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _offset_seconds(value) -> int | None:
    """UTC offset (seconds) carried by an Oura ISO timestamp, e.g. "...T07:12:00-05:00"."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.utcoffset() is None:
        return None
    return int(dt.utcoffset().total_seconds())


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _for_day(docs: list[dict], d: date) -> list[dict]:
    """Oura daily/sleep documents carry a local calendar `day` — filter to the target day
    (reads use a padded start/end window to be safe against the API's window semantics)."""
    return [doc for doc in docs if doc.get("day") == d.isoformat()]


# --- token handling --------------------------------------------------------------

def _fresh_token(db: Session, account: ProviderAccount) -> str:
    """Return a usable access token, refreshing (and committing the rotated pair) only
    when the stored one is expired / near expiry. See module docstring for why this must
    commit immediately rather than ride the end-of-day commit."""
    if account.token_expires_at and account.token_expires_at > datetime.utcnow() + _REFRESH_MARGIN:
        return decrypt(account.access_token)
    if not account.refresh_token:
        raise oura.GrantRevokedError("no refresh token on record")
    res = oura.refresh(decrypt(account.refresh_token))
    account.access_token = encrypt(res.access_token)
    if res.refresh_token:
        account.refresh_token = encrypt(res.refresh_token)
    account.token_expires_at = res.expires_at
    db.commit()
    return res.access_token


# --- document -> metric mapping (pure, unit-testable) -----------------------------

def map_daily_activity(doc: dict) -> tuple[dict, dict]:
    """daily_activity -> (typed, metrics["activity"]). MVPA = high + medium activity time."""
    typed: dict = {}
    steps = _num(doc.get("steps"))
    if steps is not None:
        typed["steps"] = int(steps)
    dist = _num(doc.get("equivalent_walking_distance"))
    if dist is not None:
        typed["distance_m"] = dist
    cal = _num(doc.get("total_calories"))
    if cal is not None:
        typed["calories"] = cal
    high = _num(doc.get("high_activity_time")) or 0
    medium = _num(doc.get("medium_activity_time")) or 0
    if doc.get("high_activity_time") is not None or doc.get("medium_activity_time") is not None:
        typed["mvpa_minutes"] = round((high + medium) / 60)

    def _min(key):
        v = _num(doc.get(key))
        return round(v / 60) if v is not None else None

    metrics = {
        "score": doc.get("score"),
        "active_calories": _num(doc.get("active_calories")),
        "low_minutes": _min("low_activity_time"),
        "medium_minutes": _min("medium_activity_time"),
        "high_minutes": _min("high_activity_time"),
        "sedentary_minutes": _min("sedentary_time"),
        "non_wear_minutes": _min("non_wear_time"),
        "average_met_minutes": _num(doc.get("average_met_minutes")),
    }
    return typed, {k: v for k, v in metrics.items() if v is not None}


def aggregate_sleep(docs: list[dict]) -> tuple[dict, dict, int | None]:
    """Long-form `sleep` periods for one day -> (typed, metrics["sleep"], tz_off).

    Stage keys are uppercased (DEEP/LIGHT/REM/AWAKE) to match the Google/consolidation
    shape so the existing console day view and CSV export read them unchanged.
    """
    typed: dict = {}
    stages: dict[str, float] = {}
    total_sleep = 0.0
    hrv_weighted = 0.0
    hrv_weight = 0.0
    hr_weighted = 0.0
    hr_weight = 0.0
    lowest_hr: float | None = None
    tz_off: int | None = None
    efficiency = None
    for doc in docs:
        dur = _num(doc.get("total_sleep_duration")) or 0.0
        total_sleep += dur
        for key, stage in (
            ("deep_sleep_duration", "DEEP"),
            ("light_sleep_duration", "LIGHT"),
            ("rem_sleep_duration", "REM"),
            ("awake_time", "AWAKE"),
        ):
            v = _num(doc.get(key))
            if v is not None:
                stages[stage] = stages.get(stage, 0.0) + v
        hrv = _num(doc.get("average_hrv"))
        if hrv is not None and dur > 0:
            hrv_weighted += hrv * dur
            hrv_weight += dur
        hr = _num(doc.get("average_heart_rate"))
        if hr is not None and dur > 0:
            hr_weighted += hr * dur
            hr_weight += dur
        low = _num(doc.get("lowest_heart_rate"))
        if low is not None:
            lowest_hr = low if lowest_hr is None else min(lowest_hr, low)
        if tz_off is None:
            tz_off = _offset_seconds(doc.get("bedtime_start"))
        if efficiency is None:
            efficiency = _num(doc.get("efficiency"))
    if not docs:
        return typed, {}, None

    asleep_min = round(total_sleep / 60)
    typed["sleep_minutes"] = asleep_min
    if hrv_weight > 0:
        typed["hrv_ms"] = round(hrv_weighted / hrv_weight, 1)
    if lowest_hr is not None:
        typed["resting_hr"] = int(lowest_hr)  # Oura's nightly resting-HR convention

    stage_min = {k: round(v / 60) for k, v in stages.items()}
    metrics = {
        "total_min": asleep_min + stage_min.get("AWAKE", 0),
        "asleep_min": asleep_min,
        "stages": stage_min,
        "segments": len(docs),
    }
    if efficiency is not None:
        metrics["efficiency"] = efficiency
    if hr_weight > 0:
        metrics["hr_avg_sleep"] = round(hr_weighted / hr_weight, 1)
    return typed, metrics, tz_off


def map_daily_readiness(doc: dict) -> dict:
    out = {
        "score": doc.get("score"),
        "temperature_deviation": _num(doc.get("temperature_deviation")),
        "temperature_trend_deviation": _num(doc.get("temperature_trend_deviation")),
    }
    return {k: v for k, v in out.items() if v is not None}


def map_daily_stress(doc: dict) -> dict:
    def _min(key):
        v = _num(doc.get(key))
        return round(v / 60) if v is not None else None

    out = {
        "high_minutes": _min("stress_high"),
        "recovery_minutes": _min("recovery_high"),
        "day_summary": doc.get("day_summary"),
    }
    return {k: v for k, v in out.items() if v is not None}


# --- intraday points -------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1)


def bucket_hr_samples(samples: list[tuple[datetime, float]], bucket_min: int) -> list[dict]:
    """Downsample (utc_time, bpm) samples to bucket_min-minute averages (<=0 keeps raw).
    Returns [{start, end, avg, n}] — same shape as consolidation.pull_intraday_hr."""
    if bucket_min <= 0:
        return [{"start": t, "end": t, "avg": round(b, 1), "n": 1} for t, b in samples]
    bsec = bucket_min * 60
    buckets: dict[int, tuple[float, int]] = {}
    for t, b in samples:
        e = int((t - _EPOCH).total_seconds())
        k = e - (e % bsec)
        s, c = buckets.get(k, (0.0, 0))
        buckets[k] = (s + b, c + 1)
    return [
        {
            "start": _EPOCH + timedelta(seconds=k),
            "end": _EPOCH + timedelta(seconds=k + bsec),
            "avg": round(s / c, 1),
            "n": c,
        }
        for k, (s, c) in sorted(buckets.items())
    ]


def _store_hr_buckets(
    db: Session, account_id: int, d: date, buckets: list[dict], tz_off: int | None, bucket_min: int
) -> None:
    _replace_points_for_day(db, account_id, "heart_rate", d)
    for bkt in buckets:
        upsert_point(
            db, account_id, "heart_rate", d,
            point_key=f"heart_rate|{bkt['start'].isoformat()}",
            start=bkt["start"], end=bkt["end"], tz_off=tz_off or 0, value=bkt["avg"],
            payload={"bpm_avg": bkt["avg"], "samples": bkt["n"], "bucket_minutes": bucket_min},
        )


def store_sleep_hrv_series(db: Session, account_id: int, d: date, docs: list[dict]) -> int:
    """Sleep-period 5-min HRV (RMSSD ms) series from long-form sleep docs -> raw
    `heart_rate_variability` points (matches the Google intraday-HRV opt-in)."""
    _replace_points_for_day(db, account_id, "heart_rate_variability", d)
    n = 0
    for doc in docs:
        series = doc.get("hrv") or {}
        items = series.get("items") or []
        interval = _num(series.get("interval")) or 300.0
        t0 = _parse_ts(series.get("timestamp")) or _parse_ts(doc.get("bedtime_start"))
        off = _offset_seconds(doc.get("bedtime_start"))
        if t0 is None:
            continue
        for i, v in enumerate(items):
            val = _num(v)
            if val is None:
                continue
            t = t0 + timedelta(seconds=i * interval)
            upsert_point(
                db, account_id, "heart_rate_variability", d,
                point_key=f"heart_rate_variability|{t.isoformat()}",
                start=t, end=t, tz_off=off, value=val,
                payload={"rmssd_ms": val, "interval_seconds": interval},
            )
            n += 1
    return n


# --- webhook support -------------------------------------------------------------

def local_today_yesterday(db: Session, account: ProviderAccount) -> set[date]:
    """The account-local today + yesterday, for dirty-marking on webhook events (which
    carry no date). Uses the most recent known tz offset, falling back to UTC; the
    nightly days_back=2 job self-heals anything this misses."""
    off = db.scalar(
        select(DailyHealth.tz_offset_seconds)
        .where(DailyHealth.provider_account_id == account.id)
        .order_by(DailyHealth.local_date.desc())
        .limit(1)
    )
    local_now = datetime.utcnow() + timedelta(seconds=off or 0)
    today = local_now.date()
    return {today, today - timedelta(days=1)}


# --- consolidation ---------------------------------------------------------------

def consolidate_day(db: Session, account: ProviderAccount, d: date) -> ConsolidationState:
    """Pull + aggregate one Oura subject-day into `daily_health` (+ intraday points).
    Idempotent; same state machine and collection-window semantics as the Google path."""
    state = _get_or_create_state(db, account.id, d)
    if _outside_collection_window(account.subject, d):
        state.status, state.detail, state.completed_at = (
            "skipped", "outside collection window", datetime.utcnow()
        )
        db.commit()
        return state
    try:
        token = _fresh_token(db, account)
    except oura.GrantRevokedError as exc:
        from app.accounts import mark_revoked
        mark_revoked(db, account)
        state.status, state.detail, state.completed_at = (
            "error", f"grant revoked: {exc}", datetime.utcnow()
        )
        db.commit()
        return state

    settings = get_settings()
    subj = db.get(Subject, account.subject_id)
    study = db.get(Study, subj.study_id) if subj else None

    typed: dict = {}
    metrics: dict = {}
    errors: dict = {}
    tz_off: int | None = None
    point_count = 0
    revoked_midpull = False

    def _fetch(name: str, data_type: str) -> list[dict]:
        """Fault-isolated day fetch: one type's HTTP error is recorded, not fatal —
        except a 401, which means the grant died mid-pull."""
        nonlocal revoked_midpull
        if revoked_midpull:
            return []
        try:
            docs = oura.fetch_collection(
                token, data_type, d - timedelta(days=1), d + timedelta(days=1)
            )
            return _for_day(docs, d)
        except oura.GrantRevokedError:
            revoked_midpull = True
            return []
        except httpx.HTTPStatusError as exc:
            errors[name] = exc.response.status_code
            log.warning("oura %s failed: %s %s", name, exc.response.status_code,
                        exc.response.text[:120])
            return []

    # Activity (steps / distance / calories / MVPA).
    for doc in _fetch("activity", "daily_activity")[:1]:
        t, m = map_daily_activity(doc)
        typed.update(t)
        if m:
            metrics["activity"] = m
        if tz_off is None:
            tz_off = _offset_seconds(doc.get("timestamp"))

    # Sleep: long-form periods carry everything (stages, HRV, HRs, tz offset)...
    sleep_docs = _fetch("sleep", "sleep")
    t, sleep_metrics, sleep_off = aggregate_sleep(sleep_docs)
    typed.update(t)
    if sleep_off is not None:
        tz_off = sleep_off
    # ...and daily_sleep adds the score.
    for doc in _fetch("sleep_score", "daily_sleep")[:1]:
        if doc.get("score") is not None:
            sleep_metrics["score"] = doc["score"]
    if sleep_metrics:
        metrics["sleep"] = sleep_metrics

    for doc in _fetch("readiness", "daily_readiness")[:1]:
        m = map_daily_readiness(doc)
        if m:
            metrics["readiness"] = m

    for doc in _fetch("spo2", "daily_spo2")[:1]:
        avg = _num((doc.get("spo2_percentage") or {}).get("average"))
        if avg is not None:
            typed["spo2_avg"] = round(avg, 1)
        metrics["spo2"] = doc

    for doc in _fetch("stress", "daily_stress")[:1]:
        m = map_daily_stress(doc)
        if m:
            metrics["stress"] = m

    workouts = _fetch("workouts", "workout")
    if workouts:
        metrics["workouts"] = {
            "count": len(workouts),
            "items": [
                {k: w.get(k) for k in
                 ("activity", "intensity", "calories", "distance", "start_datetime", "end_datetime")}
                for w in workouts
            ],
        }
    sessions = _fetch("sessions", "session")
    if sessions:
        metrics["sessions"] = {
            "count": len(sessions),
            "items": [{k: it.get(k) for k in ("type", "start_datetime", "end_datetime")}
                      for it in sessions],
        }
    tags = _fetch("tags", "enhanced_tag")
    if tags:
        metrics["tags"] = [
            {k: it.get(k) for k in ("tag_type_code", "custom_name", "comment", "start_time")}
            for it in tags
        ]

    # Intraday heart rate — always pulled to compute the day's hr_avg (Oura has no all-day
    # HR summary); the samples are only STORED as points when the study opts in.
    if not revoked_midpull:
        try:
            offset = tz_off or 0
            start_utc = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(seconds=offset)
            raw = oura.fetch_heartrate(token, start_utc, start_utc + timedelta(days=1))
            samples: list[tuple[datetime, float]] = []
            for it in raw:
                ts = _parse_ts(it.get("timestamp"))
                bpm = _num(it.get("bpm"))
                if ts is not None and bpm is not None:
                    samples.append((ts, bpm))
            if samples:
                typed["hr_avg"] = round(sum(b for _, b in samples) / len(samples), 1)
                metrics["heart_rate"] = {"samples": len(samples)}
            if study and study.ingest_intraday_hr:
                bucket_min = settings.hr_downsample_minutes
                buckets = bucket_hr_samples(samples, bucket_min)
                _store_hr_buckets(db, account.id, d, buckets, tz_off, bucket_min)
                point_count += len(buckets)
                if samples:
                    metrics["heart_rate"].update(
                        {"intraday_buckets": len(buckets), "bucket_minutes": bucket_min}
                    )
        except oura.GrantRevokedError:
            revoked_midpull = True
        except httpx.HTTPStatusError as exc:
            errors["heart_rate:intraday"] = exc.response.status_code

    # Sleep-period HRV series — opt-in, already fetched with the sleep docs.
    if study and study.ingest_intraday_hrv and sleep_docs:
        point_count += store_sleep_hrv_series(db, account.id, d, sleep_docs)

    if revoked_midpull:
        from app.accounts import mark_revoked
        mark_revoked(db, account)
        state.status, state.detail, state.completed_at = (
            "error", "grant revoked (mid-pull 401)", datetime.utcnow()
        )
        db.commit()
        return state

    if errors:
        metrics["_errors"] = errors
    upsert_daily(db, account, d, typed, metrics, point_count, tz_off)
    state.status, state.detail, state.completed_at = "done", None, datetime.utcnow()
    db.commit()
    return state
