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
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.dailywrite import upsert_daily as _upsert_daily
from app.db import SessionLocal
from app.models import (
    ConsolidationState,
    HealthDataPoint,
    PairedDevice,
    ProviderAccount,
    Study,
    Subject,
)
from app.providers import fitbit_gh, gh_creds

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


# Per-study opt-in intraday *sample* types (sleep-period, low-frequency — stored raw, no
# downsampling). Keyed by the datatype string we store on HealthDataPoint rows; values are
# (read_id, value-object key, scalar key inside it). Verified live 2026-06-18.
INTRADAY_SAMPLE_TYPES: dict[str, tuple[str, str, str]] = {
    "heart_rate_variability": (
        "heart-rate-variability", "heartRateVariability",
        "rootMeanSquareOfSuccessiveDifferencesMilliseconds",  # RMSSD ms
    ),
    "oxygen_saturation": ("oxygen-saturation", "oxygenSaturation", "percentage"),
}


def pull_intraday_samples(token: str, read_id: str, d: date, tz_off: int | None) -> list[dict]:
    """Raw instantaneous samples (HRV, SpO2) for local day `d`.

    These sample-time types aren't civil_start_time-filterable, so we filter on the
    `sample_time.physical_time` UTC window for the local day (same trick as intraday HR). They're
    sleep-period and low-frequency (tens of points/day), so the raw dataPoints are returned as-is."""
    offset = tz_off or 0
    start_utc = datetime(d.year, d.month, d.day) - timedelta(seconds=offset)
    end_utc = start_utc + timedelta(days=1)
    field = read_id.replace("-", "_")
    flt = (
        f'{field}.sample_time.physical_time >= "{start_utc.isoformat()}Z" '
        f'AND {field}.sample_time.physical_time < "{end_utc.isoformat()}Z"'
    )
    url = f"{_BASE}/users/me/dataTypes/{read_id}/dataPoints"
    out: list[dict] = []
    page_token = None
    for _ in range(50):  # safety bound
        params = {"filter": flt, "pageSize": "1000"}
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


def _probe_tz_offset(token: str, d: date) -> int | None:
    """One-request probe for the local UTC offset on day `d`, via a single `steps` point.

    Used to anchor intraday HR/HRV/SpO2 windows when no list points were stored that day (e.g.
    intraday activity is off, so steps/distance aren't pulled)."""
    nxt = d + timedelta(days=1)
    flt = (
        f'steps.interval.civil_start_time >= "{d.isoformat()}" '
        f'AND steps.interval.civil_start_time < "{nxt.isoformat()}"'
    )
    url = f"{_BASE}/users/me/dataTypes/steps/dataPoints"
    r = httpx.get(url, params={"filter": flt, "pageSize": "1"}, headers=_auth(token), timeout=_TIMEOUT)
    r.raise_for_status()
    for dp in r.json().get("dataPoints") or []:
        vo = dp.get("steps") or {}
        off = _offset_seconds((vo.get("interval") or {}).get("startUtcOffset"))
        if off is not None:
            return off
    return None


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
    """Refresh + persist the account's access token. Raises GrantRevokedError if revoked.

    Refreshes against the credential set that ISSUED this token (pinned on the account), so it works
    regardless of the study's current set. Runs on every trigger (nightly / webhook / on-demand)."""
    if not account.refresh_token:
        raise fitbit_gh.GrantRevokedError("no refresh token on record")
    creds = gh_creds.resolve_for_account(db, account)
    log.debug("refresh acct %s using creds source=%s", account.id, creds.source)
    res = fitbit_gh.refresh(creds, decrypt(account.refresh_token))
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
        # Session is autoflush=False, so the SELECT above can't see rows added earlier in this
        # same run. Flush now so a later duplicate point_key in the same pull (Google can return
        # overlapping dataPoints across pages, or two name-less points sharing a start minute)
        # finds this row and updates it instead of adding a second, which would violate
        # uq_hdp_acct_dt_key at commit.
        db.flush()
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
        db.flush()  # see _upsert_point: flush so same-run duplicate buckets update, not re-add
    row.local_date = d
    row.start_time = bkt["start"]
    row.end_time = bkt["end"]
    row.tz_offset_seconds = offset
    row.value = bkt["avg"]
    row.payload = {"bpm_avg": bkt["avg"], "samples": bkt["n"], "bucket_minutes": bucket_min}


def _upsert_sample_point(
    db: Session, account_id: int, datatype: str, value_key: str, scalar_key: str, d: date, dp: dict
) -> None:
    """Upsert one instantaneous sample (HRV/SpO2) as a HealthDataPoint, keyed by its sample time."""
    vo = dp.get(value_key) or {}
    st = vo.get("sampleTime") or {}
    t = _parse_iso(st.get("physicalTime"))
    off = _offset_seconds(st.get("utcOffset"))
    val = _num(vo.get(scalar_key))
    point_key = f"{datatype}|{t.isoformat() if t else id(dp)}"
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
        db.flush()  # see _upsert_point: flush so same-run duplicate samples update, not re-add
    row.local_date = d
    row.start_time = t
    row.end_time = t
    row.tz_offset_seconds = off
    row.value = val
    row.payload = dp


def bucket_sum_points(points: list[dict], read_id: str, bucket_min: int) -> list[dict]:
    """Integrate summable 1-min list points (steps/distance) into `bucket_min`-minute SUM buckets.

    Returns [{start, end, sum, n, off}] sorted by start. `bucket_min <= 0` keeps each point as its
    own 1-min bucket (passthrough). Mirrors the bucketing math in `pull_intraday_hr`."""
    parsed: list[tuple[datetime, float, int | None]] = []
    for dp in points:
        vo = dp.get(read_id) or {}
        if not isinstance(vo, dict):
            continue
        start, _end, off = _point_interval(dp, vo)
        val = _first_number({k: v for k, v in vo.items() if k not in ("interval", "sampleTime")})
        if start is None or val is None:
            continue
        parsed.append((start, val, off))

    if bucket_min <= 0:
        return [
            {"start": s, "end": s + timedelta(minutes=1), "sum": v, "n": 1, "off": o}
            for s, v, o in parsed
        ]

    bsec = bucket_min * 60
    buckets: dict[int, list] = {}  # epoch -> [sum, n, off]
    for s, v, o in parsed:
        epoch = int((s - _EPOCH).total_seconds())
        k = epoch - (epoch % bsec)
        b = buckets.get(k)
        if b is None:
            buckets[k] = [v, 1, o]
        else:
            b[0] += v
            b[1] += 1
            if b[2] is None:
                b[2] = o
    out = []
    for k in sorted(buckets):
        total, n, off = buckets[k]
        start = datetime.fromtimestamp(k, timezone.utc).replace(tzinfo=None)
        out.append(
            {"start": start, "end": start + timedelta(seconds=bsec),
             "sum": round(total, 2), "n": n, "off": off}
        )
    return out


def bucket_samples_avg_min(
    pts: list[dict], value_key: str, scalar_key: str, bucket_min: int
) -> list[dict]:
    """Downsample instantaneous samples (SpO2) into `bucket_min`-minute buckets, keeping both the
    average and the bucket minimum (desaturation nadir). Returns [{start, end, avg, min, n, off}]."""
    bsec = bucket_min * 60
    buckets: dict[int, list] = {}  # epoch -> [sum, min, n, off]
    for dp in pts:
        vo = dp.get(value_key) or {}
        st = vo.get("sampleTime") or {}
        t = _parse_iso(st.get("physicalTime"))
        val = _num(vo.get(scalar_key))
        if t is None or val is None:
            continue
        off = _offset_seconds(st.get("utcOffset"))
        epoch = int((t - _EPOCH).total_seconds())
        k = epoch - (epoch % bsec)
        b = buckets.get(k)
        if b is None:
            buckets[k] = [val, val, 1, off]
        else:
            b[0] += val
            b[1] = min(b[1], val)
            b[2] += 1
            if b[3] is None:
                b[3] = off
    out = []
    for k in sorted(buckets):
        total, mn, n, off = buckets[k]
        start = datetime.fromtimestamp(k, timezone.utc).replace(tzinfo=None)
        out.append(
            {"start": start, "end": start + timedelta(seconds=bsec),
             "avg": round(total / n, 1), "min": round(mn, 1), "n": n, "off": off}
        )
    return out


def _upsert_value_bucket(
    db: Session, account_id: int, datatype: str, d: date, bkt: dict, value, payload: dict
) -> None:
    """Upsert one aggregated bucket (steps/distance sum, SpO2 avg) as a HealthDataPoint."""
    point_key = f"{datatype}|{bkt['start'].isoformat()}"
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
        db.flush()  # see _upsert_point: flush so same-run duplicate buckets update, not re-add
    row.local_date = d
    row.start_time = bkt["start"]
    row.end_time = bkt["end"]
    row.tz_offset_seconds = bkt.get("off") or 0
    row.value = value
    row.payload = payload


def _replace_points_for_day(db: Session, account_id: int, datatype: str, d: date) -> None:
    """Delete existing intraday points for (account, datatype, local day) before re-inserting.

    Makes consolidation self-cleaning across granularity changes (e.g. switching raw 1-min steps to
    5-min buckets, or disabling intraday) and keeps re-runs idempotent."""
    db.execute(
        delete(HealthDataPoint).where(
            HealthDataPoint.provider_account_id == account_id,
            HealthDataPoint.datatype == datatype,
            HealthDataPoint.local_date == d,
        )
    )
    db.flush()


def _upsert_paired_device(db: Session, account_id: int, dev: dict) -> None:
    """Upsert one PairedDevice snapshot row (keyed by the Google resource `name`)."""
    name = dev.get("name") or dev.get("macAddress")
    if not name:
        return
    row = db.scalar(
        select(PairedDevice).where(
            PairedDevice.provider_account_id == account_id,
            PairedDevice.device_name == name,
        )
    )
    if row is None:
        row = PairedDevice(provider_account_id=account_id, device_name=name)
        db.add(row)
        db.flush()  # see _upsert_point: same-run dedupe under autoflush=False
    row.device_type = dev.get("deviceType")
    row.device_version = dev.get("deviceVersion")
    row.battery_level = _to_int(dev.get("batteryLevel"))
    row.battery_status = dev.get("batteryStatus")
    row.last_sync_time = _parse_iso(dev.get("lastSyncTime"))
    row.mac_address = dev.get("macAddress")
    row.features = dev.get("features")
    row.raw_json = dev


def refresh_paired_devices(db: Session, account: ProviderAccount, token: str) -> int:
    """Pull + upsert the account's paired-device snapshots. Returns the count seen.

    Battery/sync are "now" values, so callers only refresh when consolidating a recent day.
    Fault-isolated by the caller; the settings.readonly scope must be on the grant."""
    devices = fitbit_gh.list_paired_devices(token)
    for dev in devices:
        if isinstance(dev, dict):
            _upsert_paired_device(db, account.id, dev)
    return len(devices)


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


def _outside_collection_window(subject, d: date) -> bool:
    """True if `d` falls outside the subject's optional [collection_start, collection_end]
    (inclusive, subject-local days). Either bound may be None = unbounded on that side."""
    if subject is None:
        return False
    if subject.collection_start and d < subject.collection_start:
        return True
    if subject.collection_end and d > subject.collection_end:
        return True
    return False


def consolidate_day(db: Session, account: ProviderAccount, d: date) -> ConsolidationState:
    """Pull + aggregate one subject-day into `daily_health` (+ raw points). Idempotent.

    Days outside the subject's data-collection window are skipped (no API pull) so the window
    is enforced uniformly across every trigger that routes through here (real-time webhook,
    nightly safety-net, on-demand backfill)."""
    state = _get_or_create_state(db, account.id, d)
    if _outside_collection_window(account.subject, d):
        state.status, state.detail, state.completed_at = (
            "skipped", "outside collection window", datetime.utcnow()
        )
        db.commit()
        return state
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

    settings = get_settings()
    subj = db.get(Subject, account.subject_id)
    study = db.get(Study, subj.study_id) if subj else None

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
        if not spec.list_:
            continue
        # Steps/distance: intraday is OPT-IN per study (the daily totals come from the rollup
        # above regardless). When off, skip the pull and clear any previously stored points; when
        # on, integrate the 1-min points into N-minute SUM buckets before storing.
        if name in ("steps", "distance"):
            if not (study and study.ingest_intraday_activity):
                _replace_points_for_day(db, account.id, name, d)
                continue
            try:
                points = pull_points(
                    token, spec.read_id, d, page_size=spec.page_size, filterable=spec.filterable
                )
                bucket_min = settings.steps_bucket_minutes
                buckets = bucket_sum_points(points, spec.read_id, bucket_min)
                _replace_points_for_day(db, account.id, name, d)
                for bkt in buckets:
                    _upsert_value_bucket(
                        db, account.id, name, d, bkt, bkt["sum"],
                        {"sum": bkt["sum"], "samples": bkt["n"], "bucket_minutes": bucket_min},
                    )
                    if tz_off is None and bkt.get("off") is not None:
                        tz_off = bkt["off"]
                point_count += len(buckets)
            except httpx.HTTPStatusError as exc:
                errors[f"{name}:list"] = exc.response.status_code
                log.warning("list %s failed: %s %s", name, exc.response.status_code, exc.response.text[:120])
            continue
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

    # SpO2 (blood oxygen) — pull-only (NOT webhook-subscribable). The daily summary is a
    # day-keyed list type (typically computed during sleep): avg + lower/upper bound %.
    try:
        spo2 = pull_daily_value(token, "daily-oxygen-saturation", d, "daily_oxygen_saturation.date")
        if spo2:
            metrics["spo2"] = spo2
            avg = _num(spo2.get("averagePercentage"))
            if avg is not None:
                typed["spo2_avg"] = round(avg, 1)
    except httpx.HTTPStatusError as exc:
        errors["spo2:list"] = exc.response.status_code

    # Active Zone Minutes — pull-only daily rollup (NOT listable/subscribable). Per-zone minutes;
    # Fitbit weights fat-burn x1 and cardio/peak x2 for the headline total. Fault-isolated.
    try:
        azm = pull_daily_rollup(token, "active-zone-minutes", d)
        if azm:
            cardio = _to_int(azm.get("sumInCardioHeartZone")) or 0
            peak = _to_int(azm.get("sumInPeakHeartZone")) or 0
            fat_burn = _to_int(azm.get("sumInFatBurnHeartZone")) or 0
            total = fat_burn + 2 * (cardio + peak)
            metrics["active_zone_minutes"] = {
                "cardio": cardio, "peak": peak, "fat_burn": fat_burn, "total": total,
            }
            typed["azm_total"] = total
    except httpx.HTTPStatusError as exc:
        errors["active_zone_minutes:rollup"] = exc.response.status_code

    # Active minutes by activity level — pull-only daily rollup. Headline is MVPA
    # (moderate + vigorous, the public-health standard); per-level minutes kept in metrics.
    try:
        am = pull_daily_rollup(token, "active-minutes", d)
        if am:
            levels: dict[str, int] = {}
            for it in am.get("activeMinutesRollupByActivityLevel") or []:
                lvl = (it.get("activityLevel") or "").lower()
                mins = _to_int(it.get("activeMinutesSum"))
                if lvl and mins is not None:
                    levels[lvl] = mins
            if levels:
                mvpa = levels.get("moderate", 0) + levels.get("vigorous", 0)
                metrics["active_minutes"] = {**levels, "mvpa": mvpa}
                typed["mvpa_minutes"] = mvpa
    except httpx.HTTPStatusError as exc:
        errors["active_minutes:rollup"] = exc.response.status_code

    # Intraday HR/HRV/SpO2 windows are anchored on local-day midnight, so they need the day's UTC
    # offset. It's normally captured from the list points above, but when intraday activity is off
    # (steps/distance not pulled) fall back to a one-point probe so the window stays correct.
    if tz_off is None and study and (
        study.ingest_intraday_hr or study.ingest_intraday_hrv or study.ingest_intraday_spo2
    ):
        try:
            tz_off = _probe_tz_offset(token, d)
        except httpx.HTTPStatusError:
            pass

    # Intraday heart rate — OPT-IN per study, downsampled to N-minute buckets (raw HR is
    # 1000+ samples/day). Stored as `heart_rate` points so they show in the day expansion + export.
    if study and study.ingest_intraday_hr:
        try:
            bucket_min = settings.hr_downsample_minutes
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

    # Intraday HRV / SpO2 — OPT-IN per study. HRV is ~5-min already → stored raw; SpO2 is ~1-min
    # → downsampled to N-min avg buckets (with bucket min). Each lands as
    # `heart_rate_variability` / `oxygen_saturation` points (day expansion + export).
    if study:
        spo2_bucket_min = settings.spo2_downsample_minutes
        for dt, enabled in (
            ("heart_rate_variability", study.ingest_intraday_hrv),
            ("oxygen_saturation", study.ingest_intraday_spo2),
        ):
            if not enabled:
                continue
            read_id, value_key, scalar_key = INTRADAY_SAMPLE_TYPES[dt]
            try:
                pts = pull_intraday_samples(token, read_id, d, tz_off)
                # SpO2 is ~1-min during sleep (~390/day): downsample to N-min avg buckets, keeping
                # the bucket minimum (desaturation nadir). HRV is already ~5-min — stored raw.
                if dt == "oxygen_saturation" and spo2_bucket_min > 0:
                    buckets = bucket_samples_avg_min(pts, value_key, scalar_key, spo2_bucket_min)
                    _replace_points_for_day(db, account.id, dt, d)
                    for bkt in buckets:
                        _upsert_value_bucket(
                            db, account.id, dt, d, bkt, bkt["avg"],
                            {"spo2_avg": bkt["avg"], "spo2_min": bkt["min"],
                             "samples": bkt["n"], "bucket_minutes": spo2_bucket_min},
                        )
                    point_count += len(buckets)
                    metrics.setdefault("intraday", {})[dt] = len(buckets)
                else:
                    for dp in pts:
                        _upsert_sample_point(db, account.id, dt, value_key, scalar_key, d, dp)
                    point_count += len(pts)
                    metrics.setdefault("intraday", {})[dt] = len(pts)
            except httpx.HTTPStatusError as exc:
                errors[f"{dt}:intraday"] = exc.response.status_code

    # Paired-device snapshot (battery, last sync, model) — profile data, not per-day. Battery is
    # a "now" value, so only refresh when consolidating a recent day to avoid hitting the
    # HealthProfile endpoint once per day on long backfills. Fault-isolated.
    if d >= date.today() - timedelta(days=2):
        try:
            n = refresh_paired_devices(db, account, token)
            metrics["paired_devices"] = {"count": n}
        except httpx.HTTPStatusError as exc:
            errors["paired_devices"] = exc.response.status_code

    if errors:
        metrics["_errors"] = errors
    _upsert_daily(db, account, d, typed, metrics, point_count, tz_off)
    state.status, state.detail, state.completed_at = "done", None, datetime.utcnow()
    db.commit()
    return state


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
