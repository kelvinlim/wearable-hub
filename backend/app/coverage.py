"""Participant coverage calendar.

One local day per cell, three independent metrics (heart rate, steps, sleep).
The calendar never combines them into a single score. Heart-rate days are the
headline total ("on screen" / "to date"); steps and sleep stay visible as their
own bands.

Thresholds (product choices, documented in the changelog):

* Heart rate — sufficient when intraday samples cover at least 10 hours
  (600 min) of the local day. Ten hours is the wear-time cut used for a valid
  wrist day in NHANES-style and Fitbit adherence work (Choi / Troiano lineage).
  1–599 minutes is partial. When the study does not store intraday heart rate,
  a daily average still counts as sufficient — it is the only heart-rate signal
  we have — and a resting-heart-rate value alone is partial.
* Steps — sufficient when intraday recording covers at least 10 hours, using
  the same wear-day cut. A stored day total counts as sufficient when no
  intraday steps (and no Oura non-wear minutes) exist, **including a total of
  zero**. Zero steps is a recorded sedentary day, not a missing day. Oura's
  ``activity.non_wear_minutes`` supplies recording minutes when epoch/bucket
  points were not stored.
* Sleep — sufficient at 4 hours (240 min) or more of asleep time. Shorter
  recorded sleep (a nap, a fragmented night) is partial; no asleep time is
  missing. Four hours is a common minimum for a usable night without turning
  the band into a clinical score.

Sleep is attributed to the wake-up local date. Providers disagree about which
calendar day a night belongs to (Google Health points are pulled by session
start; Garmin ``calendarDate`` and Oura ``day`` are already the wake day). When
an account has stored ``sleep`` points, those points win and the daily column
is ignored for that account so a bedtime-dated total is not counted twice.
Accounts with no sleep points (Garmin, Oura) keep ``daily_health.sleep_minutes``
on its stored local date.

Days outside the collection window, before the participant was added (when no
window start is set), or after the participant's local today are not expected
(hatched), not missing. "Last 7 days" still renders full Monday–Sunday weeks;
dates outside that window are marked dimmed.

``span="full"`` is the sliceable calendar: every local day from the earliest of
first data, the all-data start, and six days before local today, through the
latest of local today and last data, Monday–Sunday padded. ``dimmed`` on that
payload is the all-data window. ``all_start``, ``all_end``, and ``enrolled_on``
let a client re-slice last-7 and custom ranges (including week padding) without
another query. ``to_date`` does not depend on the slice. ``on_screen`` on the
full payload is the all-data tally; clients recompute it for the visible window.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import Integer, and_, case, cast, func, literal_column, select
from sqlalchemy.orm import Session

from app.models import DailyHealth, HealthDataPoint, ProviderAccount, Subject

HR_SUFFICIENT_MINUTES = 600
STEPS_SUFFICIENT_MINUTES = 600
SLEEP_SUFFICIENT_MINUTES = 240
DAY_MINUTES = 24 * 60
MAX_CUSTOM_DAYS = 800
SPANS = frozenset({"7d", "all", "custom", "full"})

THRESHOLDS = {
    "hr_sufficient_minutes": HR_SUFFICIENT_MINUTES,
    "steps_sufficient_minutes": STEPS_SUFFICIENT_MINUTES,
    "sleep_sufficient_minutes": SLEEP_SUFFICIENT_MINUTES,
    "day_minutes": DAY_MINUTES,
}


class CoverageQueryError(ValueError):
    """The caller asked for a range the calendar cannot build."""


def _utcnow() -> datetime:
    return datetime.utcnow()


def local_today(now_utc: datetime, tz_offset_seconds: int | None) -> date:
    """Participant-local calendar day for a naive UTC timestamp."""
    return (now_utc + timedelta(seconds=tz_offset_seconds or 0)).date()


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_dates(start: date, end: date) -> list[list[date]]:
    """Monday–Sunday weeks covering ``start``..``end`` inclusive. Empty if end < start."""
    if end < start:
        return []
    cur = monday_of(start)
    last = monday_of(end)
    weeks: list[list[date]] = []
    while cur <= last:
        weeks.append([cur + timedelta(days=i) for i in range(7)])
        cur += timedelta(days=7)
    return weeks


def classify_hr(
    *,
    coverage_minutes: int | None,
    has_intraday: bool,
    hr_avg: float | None,
    resting_hr: int | None,
) -> tuple[str, str]:
    """Return ``(status, basis)`` for one local day.

    Intraday minutes win over the daily summary whenever any positive coverage
    was stored, so a short wear day stays partial even if a daily average exists.
    """
    if has_intraday and coverage_minutes is not None and coverage_minutes > 0:
        if coverage_minutes >= HR_SUFFICIENT_MINUTES:
            return "sufficient", "intraday"
        return "partial", "intraday"
    if hr_avg is not None:
        return "sufficient", "daily_summary"
    if resting_hr is not None:
        return "partial", "resting_only"
    return "missing", "none"


def classify_steps(
    *,
    total: int | None,
    coverage_minutes: int | None,
    has_recording: bool,
) -> tuple[str, str]:
    """Return ``(status, basis)``.

    ``total == 0`` with no recording series is a real sedentary day (sufficient).
    A recording series that covers zero minutes — for example Oura non-wear for
    the whole day — is missing, even when the day total is also zero: the device
    was not worn, it did not record a quiet day.
    """
    if has_recording:
        minutes = coverage_minutes or 0
        if minutes >= STEPS_SUFFICIENT_MINUTES:
            return "sufficient", "intraday"
        if minutes > 0:
            return "partial", "intraday"
        return "missing", "intraday"
    if total is not None:
        return "sufficient", "daily_total"
    return "missing", "none"


def classify_sleep(minutes: int | None) -> tuple[str, str]:
    """Return ``(status, basis)``. Zero asleep minutes is missing, unlike steps."""
    if minutes is None or minutes <= 0:
        return "missing", "none"
    if minutes >= SLEEP_SUFFICIENT_MINUTES:
        return "sufficient", "wake_date"
    return "partial", "wake_date"


def wake_local_date(
    end: datetime | None,
    start: datetime | None,
    tz_offset_seconds: int | None,
    fallback: date | None,
) -> date | None:
    """Local civil date the sleeper woke up (interval end, else start, else fallback)."""
    anchor = end or start
    if anchor is None:
        return fallback
    return (anchor + timedelta(seconds=tz_offset_seconds or 0)).date()


def _parse_iso(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def asleep_minutes_from_point(
    payload,
    start: datetime | None,
    end: datetime | None,
) -> int:
    """Asleep minutes for one sleep point.

    Stage durations excluding ``AWAKE`` when stages are present. Otherwise the
    session span (time in bed), which may include awake minutes — used only when
    the payload has no stage list.
    """
    stages = _sleep_stages(payload)
    if stages:
        asleep = 0.0
        parsed = False
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            a = _parse_iso(stage.get("startTime") or stage.get("start_time"))
            b = _parse_iso(stage.get("endTime") or stage.get("end_time"))
            if a is None or b is None or b < a:
                continue
            parsed = True
            if str(stage.get("type") or "").upper() != "AWAKE":
                asleep += (b - a).total_seconds() / 60.0
        if parsed:
            return int(round(asleep))
    return _span_minutes(start, end)


def _sleep_stages(payload) -> list | None:
    if not isinstance(payload, dict):
        return None
    sleep = payload.get("sleep") if isinstance(payload.get("sleep"), dict) else payload
    if not isinstance(sleep, dict):
        return None
    stages = sleep.get("stages")
    return stages if isinstance(stages, list) and stages else None


def _span_minutes(start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None or end < start:
        return 0
    return int(round((end - start).total_seconds() / 60.0))


def _clamp_minutes(minutes: int | None) -> int:
    if minutes is None or minutes < 0:
        return 0
    return min(DAY_MINUTES, int(minutes))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    text = dt.isoformat(timespec="seconds")
    if dt.tzinfo is None and not text.endswith("Z"):
        return text + "Z"
    return text


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _expected(d: date, subj: dict, today: date) -> tuple[bool, str | None]:
    """Whether ``d`` should count against the participant, and why not.

    A collection window is explicit. With no start bound, days before the
    participant was added are not expected; every other day on or before local
    today is. That keeps a last-7 view of a new enrollee gray (missing) rather
    than hatched, while Monday padding before enrollment stays hatched.
    """
    if d > today:
        return False, "future"
    start, end = subj.get("collection_start"), subj.get("collection_end")
    if (start and d < start) or (end and d > end):
        return False, "collection_window"
    enrolled = subj.get("enrolled_on")
    if start is None and enrolled is not None and d < enrolled:
        return False, "before_enrollment"
    return True, None


def _metric(status: str, basis: str, **fields) -> dict:
    out = {"status": status, "basis": basis}
    out.update(fields)
    return out


def _fraction(minutes: int | None) -> float | None:
    if minutes is None:
        return None
    return round(min(DAY_MINUTES, max(0, minutes)) / DAY_MINUTES, 3)


def assemble_coverage(
    *,
    subjects: list[dict],
    dailies: list[dict],
    point_aggs: list[dict],
    sleep_points: list[dict],
    span: str,
    custom_start: date | None,
    custom_end: date | None,
    now: datetime,
) -> dict:
    """Pure calendar build. Rows are plain dicts so tests skip the database.

    Subject dict keys: id, participant_id, subject_label, status, archived,
    collection_start, collection_end, account_ids (list[int]).

    Daily dict keys: account_id, local_date, steps, hr_avg, resting_hr,
    sleep_minutes, pulled_at, tz_offset_seconds, non_wear_minutes.

    Point-agg dict keys: account_id, local_date, datatype (``heart_rate`` or
    ``steps``), minutes, value_sum.

    Sleep-point dict keys: account_id, local_date, start, end, tz_offset_seconds,
    payload.
    """
    if span not in SPANS:
        raise CoverageQueryError("range must be 7d, all, custom, or full")
    if span == "custom":
        if custom_start is None or custom_end is None:
            raise CoverageQueryError("custom range requires start and end")
        if custom_end < custom_start:
            raise CoverageQueryError("end must be >= start")
        if (custom_end - custom_start).days > MAX_CUSTOM_DAYS:
            raise CoverageQueryError(f"range too large (max {MAX_CUSTOM_DAYS} days)")

    by_account_daily: dict[int, list[dict]] = defaultdict(list)
    for row in dailies:
        by_account_daily[row["account_id"]].append(row)

    hr_minutes: dict[tuple[int, date], int] = {}
    step_minutes: dict[tuple[int, date], int] = {}
    step_value: dict[tuple[int, date], float] = {}
    for agg in point_aggs:
        key = (agg["account_id"], agg["local_date"])
        minutes = _clamp_minutes(agg.get("minutes"))
        if agg["datatype"] == "heart_rate":
            hr_minutes[key] = _clamp_minutes(hr_minutes.get(key, 0) + minutes)
        elif agg["datatype"] == "steps":
            step_minutes[key] = _clamp_minutes(step_minutes.get(key, 0) + minutes)
            if agg.get("value_sum") is not None:
                step_value[key] = step_value.get(key, 0.0) + float(agg["value_sum"])

    sleep_by_account: dict[int, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    accounts_with_sleep_points: set[int] = set()
    for pt in sleep_points:
        accounts_with_sleep_points.add(pt["account_id"])
        wake = wake_local_date(
            pt.get("end"), pt.get("start"), pt.get("tz_offset_seconds"), pt.get("local_date")
        )
        if wake is None:
            continue
        sleep_by_account[pt["account_id"]][wake] += asleep_minutes_from_point(
            pt.get("payload"), pt.get("start"), pt.get("end")
        )

    # Selected window is shared for custom; last-7 and all are per participant.
    grid_start: date | None = custom_start if span == "custom" else None
    grid_end: date | None = custom_end if span == "custom" else None
    built: list[dict] = []

    ordered = sorted(
        subjects,
        key=lambda s: (
            1 if s.get("archived") else 0,
            (s.get("participant_id") or "").lower(),
            (s.get("subject_label") or "").lower(),
            s["id"],
        ),
    )

    for subj in ordered:
        ctx = _subject_context(
            subj,
            by_account_daily,
            hr_minutes,
            step_minutes,
            step_value,
            sleep_by_account,
            accounts_with_sleep_points,
            span,
            custom_start,
            custom_end,
            now,
        )
        if grid_start is None or ctx["sel_start"] < grid_start:
            grid_start = ctx["sel_start"]
        if grid_end is None or ctx["sel_end"] > grid_end:
            grid_end = ctx["sel_end"]
        built.append(ctx)

    if span == "full" and built:
        # Wider than the all-data window so a client can slice last-7 (which reaches
        # six days before local today, even for someone enrolled this week) and any
        # custom range that overlaps stored days. Pre-enrollment weeks stay in the
        # payload with their scores; the all-data slice drops them except as padding.
        starts: list[date] = []
        ends: list[date] = []
        for ctx in built:
            starts.append(min(ctx["sel_start"], ctx["today"] - timedelta(days=6)))
            ends.append(ctx["sel_end"])
            if ctx["data_start"]:
                starts.append(ctx["data_start"])
            if ctx["data_end"]:
                ends.append(ctx["data_end"])
        grid_start, grid_end = min(starts), max(ends)

    if grid_start is None or grid_end is None:
        # No participants. Still describe the requested window so the toolbar is honest.
        anchor = now.date()
        if span in ("7d", "full"):
            grid_start, grid_end = anchor - timedelta(days=6), anchor
        elif span == "all":
            grid_start = grid_end = anchor
        else:
            grid_start, grid_end = custom_start, custom_end

    weeks = week_dates(grid_start, grid_end)
    grid = [d for week in weeks for d in week]
    return {
        "range": span,
        "start": _iso(grid_start),
        "end": _iso(grid_end),
        "thresholds": dict(THRESHOLDS),
        "weeks": [{"start": _iso(week[0]), "dates": [_iso(d) for d in week]} for week in weeks],
        "subjects": [_subject_payload(item, grid) for item in built],
    }


def _enrolled_on(subj: dict, offset: int | None) -> date | None:
    """Local date the participant was added, when the caller did not pass one."""
    explicit = subj.get("enrolled_on")
    if isinstance(explicit, date):
        return explicit
    created = subj.get("created_at")
    if isinstance(created, datetime):
        return (created + timedelta(seconds=offset or 0)).date()
    if isinstance(created, date):
        return created
    return None


def _subject_context(
    subj,
    by_account_daily,
    hr_minutes,
    step_minutes,
    step_value,
    sleep_by_account,
    accounts_with_sleep_points,
    span,
    custom_start,
    custom_end,
    now,
) -> dict:
    account_ids = list(subj.get("account_ids") or [])
    rows = [r for acct in account_ids for r in by_account_daily.get(acct, [])]
    offset = _latest_offset(rows)
    today = local_today(now, offset)
    enrolled = _enrolled_on(subj, offset)
    # Copy so later subjects don't see a mutated enrolled_on on a shared dict.
    subj = {**subj, "enrolled_on": enrolled}
    data_start, data_end = _data_bounds(rows, account_ids, hr_minutes, step_minutes, sleep_by_account)
    first_data = data_start
    denom_start = subj.get("collection_start") or enrolled or first_data or today
    denom_end = today
    if subj.get("collection_end") and subj["collection_end"] < denom_end:
        denom_end = subj["collection_end"]
    if denom_end < denom_start:
        denom_end = denom_start

    # ``full`` uses the all-data selection for dimming, on_screen, and to_date.
    # The wider grid is applied in assemble_coverage.
    if span == "7d":
        sel_start, sel_end = today - timedelta(days=6), today
    elif span in ("all", "full"):
        sel_start, sel_end = denom_start, today
    else:
        sel_start, sel_end = custom_start, custom_end

    daily_by_account_date = {(row["account_id"], row["local_date"]): row for row in rows}
    ctx = {
        "subject": subj,
        "account_ids": account_ids,
        "daily_by_account_date": daily_by_account_date,
        "hr_minutes": hr_minutes,
        "step_minutes": step_minutes,
        "step_value": step_value,
        "sleep_by_account": sleep_by_account,
        "accounts_with_sleep_points": accounts_with_sleep_points,
        "today": today,
        "offset": offset,
        "sel_start": sel_start,
        "sel_end": sel_end,
        "data_start": data_start,
        "data_end": data_end,
        "calendar_span": span,
        "last_pull": max((r["pulled_at"] for r in rows if r.get("pulled_at")), default=None),
    }
    ctx["on_screen"] = _tally_span(ctx, sel_start, sel_end)
    ctx["to_date"] = _tally_span(ctx, denom_start, denom_end)
    return ctx


def _cell(ctx: dict, d: date) -> dict:
    hr, steps, sleep = _merge_day(
        d,
        ctx["account_ids"],
        ctx["daily_by_account_date"],
        ctx["hr_minutes"],
        ctx["step_minutes"],
        ctx["step_value"],
        ctx["sleep_by_account"],
        ctx["accounts_with_sleep_points"],
    )
    expected, reason = _expected(d, ctx["subject"], ctx["today"])
    return {
        "date": d.isoformat(),
        "dimmed": d < ctx["sel_start"] or d > ctx["sel_end"],
        "expected": expected,
        "reason": reason,
        "hr": hr,
        "steps": steps,
        "sleep": sleep,
    }


def _tally_span(ctx: dict, start: date, end: date) -> dict:
    tally = _tally()
    if end < start:
        return tally
    for d in _daterange(start, end):
        cell = _cell(ctx, d)
        if cell["expected"]:
            _count(tally, cell)
    return tally


def _subject_payload(item: dict, grid: list[date]) -> dict:
    subj = item["subject"]
    out = {
        "id": subj["id"],
        "participant_id": subj.get("participant_id"),
        "subject_label": subj.get("subject_label"),
        "status": subj.get("status"),
        "archived": bool(subj.get("archived")),
        "collection_start": _iso(subj.get("collection_start")),
        "collection_end": _iso(subj.get("collection_end")),
        "tz_offset_seconds": item["offset"],
        "local_today": _iso(item["today"]),
        "last_pull_at": _iso_utc(item["last_pull"]),
        "on_screen": item["on_screen"],
        "to_date": item["to_date"],
        "days": [_cell(item, d) for d in grid],
    }
    if item.get("calendar_span") == "full":
        # Selection bounds for the all-data slice. ``dimmed`` on each day already
        # uses this window; clients override it when they slice last-7 or custom.
        out["enrolled_on"] = _iso(subj.get("enrolled_on"))
        out["all_start"] = _iso(item["sel_start"])
        out["all_end"] = _iso(item["sel_end"])
    return out


def _latest_offset(rows: list[dict]) -> int | None:
    dated = [r for r in rows if r.get("tz_offset_seconds") is not None]
    if not dated:
        return None
    dated.sort(key=lambda r: r["local_date"])
    return dated[-1]["tz_offset_seconds"]


def _data_bounds(rows, account_ids, hr_minutes, step_minutes, sleep_by_account) -> tuple[date | None, date | None]:
    """Earliest and latest local date with a daily row, heart-rate/steps aggregate, or sleep."""
    dates: list[date] = [r["local_date"] for r in rows]
    acct = set(account_ids)
    for (account_id, local_date) in list(hr_minutes) + list(step_minutes):
        if account_id in acct:
            dates.append(local_date)
    for account_id in account_ids:
        dates.extend(sleep_by_account.get(account_id, {}).keys())
    if not dates:
        return None, None
    return min(dates), max(dates)


def _tally() -> dict:
    return {"hr_sufficient": 0, "steps_sufficient": 0, "sleep_sufficient": 0, "expected": 0}


def _count(tally: dict, cell: dict) -> None:
    tally["expected"] += 1
    if cell["hr"]["status"] == "sufficient":
        tally["hr_sufficient"] += 1
    if cell["steps"]["status"] == "sufficient":
        tally["steps_sufficient"] += 1
    if cell["sleep"]["status"] == "sufficient":
        tally["sleep_sufficient"] += 1


def _merge_day(
    d,
    account_ids,
    daily_by_account_date,
    hr_minutes,
    step_minutes,
    step_value,
    sleep_by_account,
    accounts_with_sleep_points,
):
    """Best signal across the subject's devices. Max coverage, not a sum.

    Summing two watches would double-count the same person. The stronger
    heart-rate coverage, the higher step total, and the longer sleep win.
    """
    best_hr = None
    best_steps = None
    best_sleep = None
    for account_id in account_ids:
        row = daily_by_account_date.get((account_id, d))
        hr_key = (account_id, d)
        has_hr = hr_key in hr_minutes
        hr_mins = hr_minutes.get(hr_key)
        hr_status, hr_basis = classify_hr(
            coverage_minutes=hr_mins,
            has_intraday=has_hr,
            hr_avg=None if row is None else row.get("hr_avg"),
            resting_hr=None if row is None else row.get("resting_hr"),
        )
        hr_obj = _metric(
            hr_status,
            hr_basis,
            minutes=hr_mins if has_hr else None,
            fraction=_fraction(hr_mins) if has_hr else None,
            hr_avg=None if row is None else row.get("hr_avg"),
        )

        has_steps = hr_key in step_minutes
        step_mins = step_minutes.get(hr_key)
        step_basis_minutes = step_mins
        total = None if row is None else row.get("steps")
        if not has_steps and row is not None and row.get("non_wear_minutes") is not None:
            wear = DAY_MINUTES - int(row["non_wear_minutes"])
            step_basis_minutes = _clamp_minutes(wear)
            has_steps = True
        if total is None and hr_key in step_value:
            total = int(round(step_value[hr_key]))
        step_status, step_basis = classify_steps(
            total=total,
            coverage_minutes=step_basis_minutes,
            has_recording=has_steps,
        )
        steps_obj = _metric(
            step_status,
            step_basis,
            total=total,
            minutes=step_basis_minutes if has_steps else None,
            fraction=_fraction(step_basis_minutes) if has_steps else None,
        )

        if account_id in accounts_with_sleep_points:
            sleep_mins = sleep_by_account.get(account_id, {}).get(d)
        else:
            sleep_mins = None if row is None else row.get("sleep_minutes")
        sleep_status, sleep_basis = classify_sleep(sleep_mins)
        sleep_obj = _metric(sleep_status, sleep_basis, minutes=sleep_mins)

        best_hr = _prefer(best_hr, hr_obj, "minutes")
        best_steps = _prefer_steps(best_steps, steps_obj)
        best_sleep = _prefer(best_sleep, sleep_obj, "minutes")

    if best_hr is None:
        best_hr = _metric("missing", "none", minutes=None, fraction=None, hr_avg=None)
    if best_steps is None:
        best_steps = _metric("missing", "none", total=None, minutes=None, fraction=None)
    if best_sleep is None:
        best_sleep = _metric("missing", "none", minutes=None)
    return best_hr, best_steps, best_sleep


_STATUS_RANK = {"sufficient": 3, "partial": 2, "missing": 1}


def _prefer(current: dict | None, candidate: dict, minutes_key: str) -> dict:
    if current is None:
        return candidate
    rank_c = _STATUS_RANK.get(candidate["status"], 0)
    rank_k = _STATUS_RANK.get(current["status"], 0)
    if rank_c != rank_k:
        return candidate if rank_c > rank_k else current
    cand_m = candidate.get(minutes_key)
    curr_m = current.get(minutes_key)
    if cand_m is None:
        return current
    if curr_m is None or cand_m > curr_m:
        return candidate
    return current


def _prefer_steps(current: dict | None, candidate: dict) -> dict:
    """Status first, then recording minutes, then the higher step total.

    A recorded zero beats a missing total. A higher non-null total wins ties
    so two devices don't get summed.
    """
    if current is None:
        return candidate
    rank_c = _STATUS_RANK.get(candidate["status"], 0)
    rank_k = _STATUS_RANK.get(current["status"], 0)
    if rank_c != rank_k:
        return candidate if rank_c > rank_k else current
    cand_m = candidate.get("minutes")
    curr_m = current.get("minutes")
    if cand_m is not None and (curr_m is None or cand_m > curr_m):
        return candidate
    if curr_m is not None and (cand_m is None or curr_m > cand_m):
        return current
    cand_t = candidate.get("total")
    curr_t = current.get("total")
    if cand_t is None:
        return current
    if curr_t is None or cand_t > curr_t:
        return candidate
    return current


def _duration_minutes_expr(dialect: str):
    """Whole minutes between start_time and end_time, portable across SQLite and MariaDB."""
    if dialect == "sqlite":
        return cast(
            func.round(
                (
                    func.julianday(HealthDataPoint.end_time)
                    - func.julianday(HealthDataPoint.start_time)
                )
                * DAY_MINUTES
            ),
            Integer,
        )
    return func.timestampdiff(
        literal_column("MINUTE"),
        HealthDataPoint.start_time,
        HealthDataPoint.end_time,
    )


def _load_subjects(db: Session, study_id: int, include_archived: bool) -> list[dict]:
    q = select(Subject).where(Subject.study_id == study_id)
    if not include_archived:
        q = q.where(Subject.archived_at.is_(None))
    subjects = list(db.scalars(q))
    if not subjects:
        return []
    ids = [s.id for s in subjects]
    accounts = list(
        db.scalars(
            select(ProviderAccount)
            .where(ProviderAccount.subject_id.in_(ids))
            .order_by(ProviderAccount.id)
        )
    )
    by_subject: dict[int, list[int]] = defaultdict(list)
    for acct in accounts:
        by_subject[acct.subject_id].append(acct.id)
    return [
        {
            "id": s.id,
            "participant_id": s.participant_id,
            "subject_label": s.subject_label,
            "status": s.status,
            "archived": s.archived_at is not None,
            "collection_start": s.collection_start,
            "collection_end": s.collection_end,
            "created_at": s.created_at,
            "account_ids": by_subject.get(s.id, []),
        }
        for s in subjects
    ]


def _load_dailies(db: Session, account_ids: list[int]) -> list[dict]:
    if not account_ids:
        return []
    non_wear = cast(
        func.json_extract(DailyHealth.metrics, "$.activity.non_wear_minutes"),
        Integer,
    )
    stmt = select(
        DailyHealth.provider_account_id,
        DailyHealth.local_date,
        DailyHealth.steps,
        DailyHealth.hr_avg,
        DailyHealth.resting_hr,
        DailyHealth.sleep_minutes,
        DailyHealth.pulled_at,
        DailyHealth.tz_offset_seconds,
        non_wear,
    ).where(DailyHealth.provider_account_id.in_(account_ids))
    out = []
    for acct, local_date, steps, hr_avg, resting, sleep, pulled, offset, wear in db.execute(stmt):
        out.append(
            {
                "account_id": acct,
                "local_date": local_date,
                "steps": steps,
                "hr_avg": hr_avg,
                "resting_hr": resting,
                "sleep_minutes": sleep,
                "pulled_at": pulled,
                "tz_offset_seconds": offset,
                "non_wear_minutes": wear,
            }
        )
    return out


def _load_point_aggs(
    db: Session, account_ids: list[int], start: date | None, end: date | None
) -> list[dict]:
    if not account_ids or start is None or end is None:
        return []
    dialect = db.get_bind().dialect.name
    duration = _duration_minutes_expr(dialect)
    samples = cast(func.json_extract(HealthDataPoint.payload, "$.samples"), Integer)
    measured = case(
        (and_(HealthDataPoint.datatype == "steps", samples.is_not(None)), samples),
        else_=duration,
    )
    stmt = (
        select(
            HealthDataPoint.provider_account_id,
            HealthDataPoint.local_date,
            HealthDataPoint.datatype,
            func.coalesce(func.sum(measured), 0),
            func.sum(HealthDataPoint.value),
        )
        .where(
            HealthDataPoint.provider_account_id.in_(account_ids),
            HealthDataPoint.datatype.in_(("heart_rate", "steps")),
            HealthDataPoint.local_date >= start,
            HealthDataPoint.local_date <= end,
        )
        .group_by(
            HealthDataPoint.provider_account_id,
            HealthDataPoint.local_date,
            HealthDataPoint.datatype,
        )
    )
    out = []
    for acct, local_date, datatype, minutes, value_sum in db.execute(stmt):
        out.append(
            {
                "account_id": acct,
                "local_date": local_date,
                "datatype": datatype,
                "minutes": int(minutes or 0),
                "value_sum": value_sum,
            }
        )
    return out


def _load_sleep_points(
    db: Session, account_ids: list[int], start: date | None, end: date | None
) -> list[dict]:
    if not account_ids or start is None or end is None:
        return []
    # One day of pad so a session stored on the bedtime date still wakes inside the span.
    stmt = select(
        HealthDataPoint.provider_account_id,
        HealthDataPoint.local_date,
        HealthDataPoint.start_time,
        HealthDataPoint.end_time,
        HealthDataPoint.tz_offset_seconds,
        HealthDataPoint.payload,
    ).where(
        HealthDataPoint.provider_account_id.in_(account_ids),
        HealthDataPoint.datatype == "sleep",
        HealthDataPoint.local_date >= start - timedelta(days=1),
        HealthDataPoint.local_date <= end + timedelta(days=1),
    )
    return [
        {
            "account_id": acct,
            "local_date": local_date,
            "start": start_time,
            "end": end_time,
            "tz_offset_seconds": offset,
            "payload": payload,
        }
        for acct, local_date, start_time, end_time, offset, payload in db.execute(stmt)
    ]


def _agg_bounds(subjects: list[dict], dailies: list[dict], now: datetime) -> tuple[date, date]:
    """Dates whose points we must load. Sleep adds its own one-day pad."""
    dates: list[date] = []
    rows_by_account: dict[int, list[dict]] = defaultdict(list)
    for row in dailies:
        rows_by_account[row["account_id"]].append(row)
        dates.append(row["local_date"])
    for subj in subjects:
        rows = [r for acct in subj["account_ids"] for r in rows_by_account.get(acct, [])]
        today = local_today(now, _latest_offset(rows))
        dates.append(today)
        if subj["collection_start"]:
            dates.append(subj["collection_start"])
        if subj["collection_end"]:
            dates.append(subj["collection_end"])
    if not dates:
        today = now.date()
        return today - timedelta(days=7), today
    return min(dates) - timedelta(days=1), max(dates) + timedelta(days=1)


def build_study_coverage(
    db: Session,
    study_id: int,
    *,
    span: str = "7d",
    custom_start: date | None = None,
    custom_end: date | None = None,
    include_archived: bool = False,
    now: datetime | None = None,
) -> dict:
    """Load one study and return the coverage calendar payload."""
    now = now or _utcnow()
    subjects = _load_subjects(db, study_id, include_archived)
    account_ids = [acct for s in subjects for acct in s["account_ids"]]
    dailies = _load_dailies(db, account_ids)
    start, end = _agg_bounds(subjects, dailies, now)
    if span == "custom" and custom_start and custom_end:
        start = min(start, custom_start - timedelta(days=1))
        end = max(end, custom_end + timedelta(days=1))
    return assemble_coverage(
        subjects=subjects,
        dailies=dailies,
        point_aggs=_load_point_aggs(db, account_ids, start, end),
        sleep_points=_load_sleep_points(db, account_ids, start, end),
        span=span,
        custom_start=custom_start,
        custom_end=custom_end,
        now=now,
    )
