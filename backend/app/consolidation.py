"""Daily consolidation of Google Health data — one row per subject per local day.

Google Health **webhooks carry no values**; they only signal which (user, dataType, interval)
changed. So consolidation *pulls* the day's data from the dataPoints API and aggregates it.

Two read methods, verified live (2026-06-11):
  - **dailyRollUp** (`POST .../dataTypes/{read_id}/dataPoints:dailyRollUp`, body
    `{"range": {"start": CivilDateTime, "end": CivilDateTime}}`) returns Google-computed daily
    totals in the subject's local day. Used for the summable/summary metrics.
        steps        -> {"countSum": "2764"}
        total-calories -> {"kcalSum": 1601.96}     (NB: the read id for "calories" is total-calories)
        distance     -> {"millimetersSum": "1885800"}
        floors/altitude/weight/height -> rollup too (value keys vary — stored verbatim in metrics)
  - **list** (`GET .../dataTypes/{read_id}/dataPoints?filter=...`) returns raw intraday points.
    Used for the raw-point fidelity layer and for **sleep**, which is NOT rollup-able
    ("supported actions: list, get") and is aggregated from `sleep.stages[]`.

`floors` and `calories` are NOT listable (list 400s); they exist only via rollup, so they have
no raw points — only the daily summary.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.db import SessionLocal
from app.models import (
    ConsolidationState,
    DailyHealth,
    HealthDataPoint,
    ProviderAccount,
    Study,
    Subject,
)
from app.providers import fitbit_gh

log = logging.getLogger(__name__)
_TIMEOUT = 30.0
_BASE = fitbit_gh.HEALTH_API_BASE


# --- per-dataType configuration -------------------------------------------------

@dataclass(frozen=True)
class Spec:
    read_id: str               # dataType id for the read/rollup API (differs from sub name!)
    rollup: bool               # supports dailyRollUp (daily summary)
    list_: bool                # supports dataPoints.list (raw points)
    typed_col: str | None = None   # daily_health column for the headline number
    headline_key: str | None = None  # key inside the rollup value object for the headline
    to_typed: object = None        # caster: raw headline -> typed column value
    page_size: int = 1000          # list page size (sleep/exercise cap at 25)
    filterable: bool = True        # civil_start_time filter works (False: sleep/sample types)


def _to_int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _mm_to_m(v):
    n = _num(v)
    return n / 1000.0 if n is not None else None


# Keyed by subscription dataType name (what we subscribe to / see in webhooks).
DATATYPE_SPEC: dict[str, Spec] = {
    "steps":    Spec("steps", rollup=True, list_=True, typed_col="steps", headline_key="countSum", to_typed=_to_int),
    "distance": Spec("distance", rollup=True, list_=True, typed_col="distance_m", headline_key="millimetersSum", to_typed=_mm_to_m),
    "calories": Spec("total-calories", rollup=True, list_=False, typed_col="calories", headline_key="kcalSum", to_typed=lambda v: _num(v)),
    "floors":   Spec("floors", rollup=True, list_=False, typed_col="floors", headline_key="countSum", to_typed=_to_int),
    "altitude": Spec("altitude", rollup=True, list_=True),
    "weight":   Spec("weight", rollup=True, list_=False),
    # height/sleep aren't filterable (sample type / sleep filter members are non-comparable);
    # listed newest-first with an early-stop client filter instead. height isn't rollup-able.
    "height":   Spec("height", rollup=False, list_=True, page_size=100, filterable=False),
    "sleep":    Spec("sleep", rollup=False, list_=True, page_size=25, filterable=False),  # from stages
    "exercise": Spec("exercise", rollup=False, list_=True, page_size=25),
}


# --- small helpers --------------------------------------------------------------

def _num(v):
    """Coerce a number or numeric string to float; None otherwise."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _first_number(obj: dict | None):
    for v in (obj or {}).values():
        n = _num(v)
        if n is not None:
            return n
    return None


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _civil(d: date) -> dict:
    return {"date": {"year": d.year, "month": d.month, "day": d.day}}


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _offset_seconds(value) -> int | None:
    """Parse an offset like '28800s' -> 28800."""
    if isinstance(value, str) and value.endswith("s"):
        try:
            return int(value[:-1])
        except ValueError:
            return None
    return None


def _civil_date_of(interval: dict) -> date | None:
    """The LOCAL civil start date of a notification interval."""
    ci = interval.get("civilIso8601TimeInterval") or {}
    s = ci.get("startTime")
    if isinstance(s, str) and len(s) >= 10:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    d = ((interval.get("civilDateTimeInterval") or {}).get("startDateTime") or {}).get("date")
    if isinstance(d, dict) and d.get("year"):
        return date(d["year"], d["month"], d["day"])
    return None


def affected_local_dates(item: dict) -> set[date]:
    """Local civil days touched by one webhook notification item."""
    data = item.get("data") if isinstance(item, dict) else None
    if not isinstance(data, dict):
        return set()
    out: set[date] = set()
    for iv in data.get("intervals") or []:
        if isinstance(iv, dict):
            d = _civil_date_of(iv)
            if d:
                out.add(d)
    return out


# --- Google reads ---------------------------------------------------------------

def pull_daily_rollup(token: str, read_id: str, d: date) -> dict | None:
    """The dailyRollUp value object for `read_id` on local day `d`, or None if no data."""
    body = {"range": {"start": _civil(d), "end": _civil(d + timedelta(days=1))}}
    url = f"{_BASE}/users/me/dataTypes/{read_id}/dataPoints:dailyRollUp"
    r = httpx.post(url, headers=_auth(token), json=body, timeout=_TIMEOUT)
    r.raise_for_status()
    pts = r.json().get("rollupDataPoints") or []
    if not pts:
        return None
    for k, v in pts[0].items():  # the value object is the one non-civil key
        if k not in ("civilStartTime", "civilEndTime") and isinstance(v, dict):
            return v
    return None


def _point_local_date(dp: dict, read_id: str) -> date | None:
    """Local civil start date of a dataPoint (UTC start + offset)."""
    vo = dp.get(read_id) or {}
    iv = vo.get("interval") or vo.get("sampleTime") or {}
    start = _parse_iso(iv.get("startTime") or iv.get("physicalTime"))
    if not start:
        return None
    off = _offset_seconds(iv.get("startUtcOffset")) or 0
    return (start + timedelta(seconds=off)).date()


def pull_daily_value(token: str, read_id: str, d: date, date_field: str) -> dict | None:
    """For 'daily' types (resting-HR, HRV) that aren't rollup-able: list the one point on day
    `d` (filtered by its `date` field) and return its value object, or None."""
    nxt = d + timedelta(days=1)
    flt = f'{date_field} >= "{d.isoformat()}" AND {date_field} < "{nxt.isoformat()}"'
    url = f"{_BASE}/users/me/dataTypes/{read_id}/dataPoints"
    r = httpx.get(url, params={"filter": flt, "pageSize": "5"}, headers=_auth(token), timeout=_TIMEOUT)
    r.raise_for_status()
    dps = r.json().get("dataPoints") or []
    if not dps:
        return None
    for k, v in dps[0].items():  # value object is the one non-meta key
        if k not in ("dataSource", "name") and isinstance(v, dict):
            return v
    return None


_EPOCH = datetime(1970, 1, 1)


def pull_intraday_hr(token: str, d: date, tz_off: int | None, bucket_min: int) -> list[dict]:
    """Pull the day's heart-rate samples (UTC window for the local day) and downsample to
    `bucket_min`-minute average-BPM buckets (bucket_min<=0 keeps raw samples). Returns
    [{start, end, avg, n}]."""
    offset = tz_off or 0
    start_utc = datetime(d.year, d.month, d.day) - timedelta(seconds=offset)
    end_utc = start_utc + timedelta(days=1)
    flt = (
        f'heart_rate.sample_time.physical_time >= "{start_utc.isoformat()}Z" '
        f'AND heart_rate.sample_time.physical_time < "{end_utc.isoformat()}Z"'
    )
    url = f"{_BASE}/users/me/dataTypes/heart-rate/dataPoints"
    samples: list[tuple[int, float]] = []
    page_token = None
    for _ in range(100):
        params = {"filter": flt, "pageSize": "1000"}
        if page_token:
            params["pageToken"] = page_token
        r = httpx.get(url, params=params, headers=_auth(token), timeout=_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        for dp in j.get("dataPoints") or []:
            hr = dp.get("heartRate") or {}
            t = _parse_iso((hr.get("sampleTime") or {}).get("physicalTime"))
            bpm = _num(hr.get("beatsPerMinute"))
            if t is not None and bpm is not None:
                samples.append((int((t - _EPOCH).total_seconds()), bpm))
        page_token = j.get("nextPageToken")
        if not page_token:
            break

    def _utc(epoch: int) -> datetime:
        return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)

    if bucket_min <= 0:
        return [{"start": _utc(e), "end": _utc(e), "avg": round(b, 1), "n": 1} for e, b in samples]
    bsec = bucket_min * 60
    buckets: dict[int, tuple[float, int]] = {}
    for e, b in samples:
        k = e - (e % bsec)
        s, c = buckets.get(k, (0.0, 0))
        buckets[k] = (s + b, c + 1)
    return [
        {"start": _utc(k), "end": _utc(k + bsec), "avg": round(s / c, 1), "n": c}
        for k, (s, c) in sorted(buckets.items())
    ]


def pull_points(
    token: str, read_id: str, d: date, page_size: int = 1000, filterable: bool = True
) -> list[dict]:
    """Raw intraday dataPoints for `read_id` on local day `d`.

    `filterable` types use the civil_start_time `filter`. Others (sleep, sample types) don't
    accept that filter, so we page the (newest-first) unfiltered list and stop once we pass `d`.
    """
    url = f"{_BASE}/users/me/dataTypes/{read_id}/dataPoints"
    out: list[dict] = []
    page_token = None

    if filterable:
        nxt = d + timedelta(days=1)
        flt = (
            f'{read_id}.interval.civil_start_time >= "{d.isoformat()}" '
            f'AND {read_id}.interval.civil_start_time < "{nxt.isoformat()}"'
        )
        for _ in range(100):  # safety bound on pagination
            params = {"filter": flt, "pageSize": str(page_size)}
            if page_token:
                params["pageToken"] = page_token
            r = httpx.get(url, params=params, headers=_auth(token), timeout=_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            out.extend(j.get("dataPoints") or [])
            page_token = j.get("nextPageToken")
            if not page_token:
                break
        return out

    # Unfiltered, newest-first: collect day `d`, stop once points are older than it.
    for _ in range(50):
        params = {"pageSize": str(page_size)}
        if page_token:
            params["pageToken"] = page_token
        r = httpx.get(url, params=params, headers=_auth(token), timeout=_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        stop = False
        for dp in j.get("dataPoints") or []:
            ld = _point_local_date(dp, read_id)
            if ld is None:
                continue
            if ld < d:
                stop = True
                break
            if ld == d:
                out.append(dp)
        page_token = j.get("nextPageToken")
        if stop or not page_token:
            break
    return out


# --- aggregation ----------------------------------------------------------------

def _point_interval(dp: dict, value_obj: dict) -> tuple[datetime | None, datetime | None, int | None]:
    iv = value_obj.get("interval") or value_obj.get("sampleTime") or {}
    start = _parse_iso(iv.get("startTime") or iv.get("physicalTime"))
    end = _parse_iso(iv.get("endTime"))
    off = _offset_seconds(iv.get("startUtcOffset"))
    return start, end, off


def aggregate_sleep(points: list[dict]) -> dict:
    """Per-stage minutes from sleep `stages[]`; asleep = total minus AWAKE."""
    stages: dict[str, float] = {}
    segments = 0
    for p in points:
        sl = p.get("sleep") or {}
        for st in sl.get("stages") or []:
            start, end = _parse_iso(st.get("startTime")), _parse_iso(st.get("endTime"))
            if not (start and end):
                continue
            mins = (end - start).total_seconds() / 60.0
            stages[st.get("type", "UNKNOWN")] = stages.get(st.get("type", "UNKNOWN"), 0.0) + mins
        segments += 1
    total = sum(stages.values())
    asleep = total - stages.get("AWAKE", 0.0)
    return {
        "total_min": round(total),
        "asleep_min": round(asleep),
        "stages": {k: round(v) for k, v in stages.items()},
        "segments": segments,
    }


# --- consolidation --------------------------------------------------------------

def _fresh_token(db: Session, account: ProviderAccount) -> str:
    """Refresh + persist the account's access token. Raises GrantRevokedError if revoked."""
    if not account.refresh_token:
        raise fitbit_gh.GrantRevokedError("no refresh token on record")
    res = fitbit_gh.refresh(decrypt(account.refresh_token))
    account.access_token = encrypt(res.access_token)
    if res.refresh_token:
        account.refresh_token = encrypt(res.refresh_token)
    account.token_expires_at = res.expires_at
    db.flush()
    return res.access_token


def _upsert_point(db: Session, account_id: int, datatype: str, d: date, dp: dict) -> None:
    value_obj = dp.get(DATATYPE_SPEC[datatype].read_id) or dp.get(datatype) or {}
    if not isinstance(value_obj, dict):
        value_obj = {}
    start, end, off = _point_interval(dp, value_obj)
    point_key = dp.get("name") or f"{datatype}|{start.isoformat() if start else id(dp)}"
    scalar = _first_number({k: v for k, v in value_obj.items() if k not in ("interval", "sampleTime")})

    row = db.scalar(
        select(HealthDataPoint).where(
            HealthDataPoint.provider_account_id == account_id,
            HealthDataPoint.datatype == datatype,
            HealthDataPoint.point_key == point_key,
        )
    )
    if row is None:
        row = HealthDataPoint(provider_account_id=account_id, datatype=datatype, point_key=point_key)
        db.add(row)
    row.local_date = d
    row.start_time = start
    row.end_time = end
    row.tz_offset_seconds = off
    row.value = scalar
    row.payload = dp


def _upsert_hr_bucket(db: Session, account_id: int, d: date, bkt: dict, offset: int, bucket_min: int) -> None:
    point_key = f"heart_rate|{bkt['start'].isoformat()}"
    row = db.scalar(
        select(HealthDataPoint).where(
            HealthDataPoint.provider_account_id == account_id,
            HealthDataPoint.datatype == "heart_rate",
            HealthDataPoint.point_key == point_key,
        )
    )
    if row is None:
        row = HealthDataPoint(provider_account_id=account_id, datatype="heart_rate", point_key=point_key)
        db.add(row)
    row.local_date = d
    row.start_time = bkt["start"]
    row.end_time = bkt["end"]
    row.tz_offset_seconds = offset
    row.value = bkt["avg"]
    row.payload = {"bpm_avg": bkt["avg"], "samples": bkt["n"], "bucket_minutes": bucket_min}


def _get_or_create_state(db: Session, account_id: int, d: date) -> ConsolidationState:
    row = db.scalar(
        select(ConsolidationState).where(
            ConsolidationState.provider_account_id == account_id,
            ConsolidationState.local_date == d,
        )
    )
    if row is None:
        row = ConsolidationState(provider_account_id=account_id, local_date=d, status="pending")
        db.add(row)
        db.flush()
    return row


def consolidate_day(db: Session, account: ProviderAccount, d: date) -> ConsolidationState:
    """Pull + aggregate one subject-day into `daily_health` (+ raw points). Idempotent."""
    state = _get_or_create_state(db, account.id, d)
    try:
        token = _fresh_token(db, account)
    except fitbit_gh.GrantRevokedError as exc:
        from app.accounts import mark_revoked
        mark_revoked(db, account)
        state.status, state.detail, state.completed_at = "error", f"grant revoked: {exc}", datetime.utcnow()
        db.commit()
        return state

    metrics: dict = {}
    typed: dict = {}
    errors: dict = {}
    tz_off: int | None = None
    point_count = 0

    # Each metric is pulled independently and fault-isolated: the dataPoints API supports
    # different methods per dataType (e.g. height isn't rollup-able, floors/calories aren't
    # listable), so one type's 4xx must not fail the whole day. Failures are recorded but skipped.
    for name, spec in DATATYPE_SPEC.items():
        # Daily summary via rollup.
        if spec.rollup:
            try:
                value_obj = pull_daily_rollup(token, spec.read_id, d)
                if value_obj is not None:
                    metrics[name] = value_obj
                    if spec.typed_col:
                        raw = value_obj.get(spec.headline_key) if spec.headline_key else None
                        if raw is None:
                            raw = _first_number(value_obj)
                        typed[spec.typed_col] = (
                            spec.to_typed(raw) if (spec.to_typed and raw is not None) else _num(raw)
                        )
            except httpx.HTTPStatusError as exc:
                errors[f"{name}:rollup"] = exc.response.status_code
                log.warning("rollup %s failed: %s %s", name, exc.response.status_code, exc.response.text[:120])
        # Raw points (+ sleep aggregation) via list.
        if spec.list_:
            try:
                points = pull_points(
                    token, spec.read_id, d, page_size=spec.page_size, filterable=spec.filterable
                )
                point_count += len(points)
                for dp in points:
                    _upsert_point(db, account.id, name, d, dp)
                    if tz_off is None:
                        vo = dp.get(spec.read_id) or {}
                        tz_off = _offset_seconds((vo.get("interval") or {}).get("startUtcOffset"))
                if name == "sleep" and points:
                    s = aggregate_sleep(points)
                    metrics["sleep"] = s
                    typed["sleep_minutes"] = s["asleep_min"]
                elif name == "exercise":
                    metrics["exercise"] = {"count": len(points)}
            except httpx.HTTPStatusError as exc:
                errors[f"{name}:list"] = exc.response.status_code
                log.warning("list %s failed: %s %s", name, exc.response.status_code, exc.response.text[:120])

    # Heart rate + HRV — pull-only (NOT webhook-subscribable). heart-rate has a daily rollup
    # (avg/min/max BPM); resting-HR and HRV are day-keyed list types. Fault-isolated.
    try:
        hr = pull_daily_rollup(token, "heart-rate", d)
        if hr:
            metrics["heart_rate"] = hr
            avg = _num(hr.get("beatsPerMinuteAvg"))
            if avg is not None:
                typed["hr_avg"] = round(avg, 1)
    except httpx.HTTPStatusError as exc:
        errors["heart_rate:rollup"] = exc.response.status_code
    try:
        rhr = pull_daily_value(token, "daily-resting-heart-rate", d, "daily_resting_heart_rate.date")
        if rhr:
            metrics["resting_hr"] = rhr
            bpm = _num(rhr.get("beatsPerMinute"))
            if bpm is not None:
                typed["resting_hr"] = int(bpm)
    except httpx.HTTPStatusError as exc:
        errors["resting_hr:list"] = exc.response.status_code
    try:
        hrv = pull_daily_value(token, "daily-heart-rate-variability", d, "daily_heart_rate_variability.date")
        if hrv:
            metrics["hrv"] = hrv
            ms = _num(hrv.get("averageHeartRateVariabilityMilliseconds"))
            if ms is not None:
                typed["hrv_ms"] = round(ms, 1)
    except httpx.HTTPStatusError as exc:
        errors["hrv:list"] = exc.response.status_code

    # Intraday heart rate — OPT-IN per study, downsampled to N-minute buckets (raw HR is
    # 1000+ samples/day). Stored as `heart_rate` points so they show in the day expansion + export.
    subj = db.get(Subject, account.subject_id)
    study = db.get(Study, subj.study_id) if subj else None
    if study and study.ingest_intraday_hr:
        try:
            bucket_min = get_settings().hr_downsample_minutes
            buckets = pull_intraday_hr(token, d, tz_off, bucket_min)
            for bkt in buckets:
                _upsert_hr_bucket(db, account.id, d, bkt, tz_off or 0, bucket_min)
            point_count += len(buckets)
            hr_meta = metrics.get("heart_rate")
            if isinstance(hr_meta, dict):
                hr_meta["intraday_buckets"] = len(buckets)
                hr_meta["bucket_minutes"] = bucket_min
        except httpx.HTTPStatusError as exc:
            errors["heart_rate:intraday"] = exc.response.status_code

    if errors:
        metrics["_errors"] = errors
    _upsert_daily(db, account, d, typed, metrics, point_count, tz_off)
    state.status, state.detail, state.completed_at = "done", None, datetime.utcnow()
    db.commit()
    return state


def _upsert_daily(db, account, d, typed, metrics, point_count, tz_off) -> None:
    row = db.scalar(
        select(DailyHealth).where(
            DailyHealth.provider_account_id == account.id,
            DailyHealth.local_date == d,
        )
    )
    if row is None:
        row = DailyHealth(provider_account_id=account.id, local_date=d)
        db.add(row)
    row.subject_id = account.subject_id
    row.tz_offset_seconds = tz_off
    row.steps = typed.get("steps")
    row.distance_m = typed.get("distance_m")
    row.calories = typed.get("calories")
    row.floors = typed.get("floors")
    row.sleep_minutes = typed.get("sleep_minutes")
    row.hr_avg = typed.get("hr_avg")
    row.resting_hr = typed.get("resting_hr")
    row.hrv_ms = typed.get("hrv_ms")
    row.metrics = metrics
    row.point_count = point_count
    row.pulled_at = datetime.utcnow()


def mark_dirty(db: Session, account_id: int, dates) -> int:
    """Mark (account, day) rows `pending` for (re)consolidation. Returns count marked."""
    n = 0
    for d in dates:
        row = db.scalar(
            select(ConsolidationState).where(
                ConsolidationState.provider_account_id == account_id,
                ConsolidationState.local_date == d,
            )
        )
        if row is None:
            db.add(ConsolidationState(provider_account_id=account_id, local_date=d, status="pending"))
        elif row.status != "pending":
            row.status, row.requested_at, row.completed_at = "pending", datetime.utcnow(), None
        n += 1
    db.commit()
    return n


def consolidate_due(db: Session, limit: int = 50) -> dict:
    """Drain pending consolidation_state rows. Returns {done, errors}."""
    rows = list(
        db.scalars(
            select(ConsolidationState)
            .where(ConsolidationState.status == "pending")
            .order_by(ConsolidationState.requested_at)
            .limit(limit)
        )
    )
    done = errors = 0
    for row in rows:
        account = db.get(ProviderAccount, row.provider_account_id)
        if account is None:
            row.status, row.detail = "error", "no provider account"
            db.commit()
            errors += 1
            continue
        try:
            result = consolidate_day(db, account, row.local_date)
            done += result.status == "done"
            errors += result.status == "error"
        except Exception as exc:  # noqa: BLE001 — one bad day shouldn't stop the drain
            db.rollback()
            log.exception("consolidate_day failed for acct %s %s", account.id, row.local_date)
            fresh = db.get(ConsolidationState, row.id)
            if fresh:
                fresh.status, fresh.detail = "error", str(exc)[:500]
                db.commit()
            errors += 1
    return {"done": done, "errors": errors}


def run_due_background() -> None:
    """Drain pending days in a fresh session — safe to schedule from a request BackgroundTask."""
    db = SessionLocal()
    try:
        consolidate_due(db)
    finally:
        db.close()
