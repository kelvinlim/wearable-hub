"""Provider-agnostic writers for the consolidated `daily_health` row and intraday points.

Extracted from `consolidation.py` so both the Google *pull* path (`consolidation.py`) and the
Garmin *push* path (`garmin_ingest.py`) write `daily_health` / `health_data_points` identically,
without `garmin_ingest` importing the Google pull code.

`SessionLocal` is `autoflush=False`, so a find-or-create SELECT can't see rows added earlier in
the same run; `upsert_point` flushes immediately after `db.add()` so a later duplicate
`(provider_account_id, datatype, point_key)` in the same run updates the existing row instead of
adding a second (which would violate `uq_hdp_acct_dt_key` at commit). See CLAUDE.md.
"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyHealth, HealthDataPoint, ProviderAccount


def upsert_daily(
    db: Session,
    account: ProviderAccount,
    d: date,
    typed: dict,
    metrics: dict | None,
    point_count: int,
    tz_off: int | None,
) -> None:
    """Upsert the one `daily_health` row for (account, local_date) from typed headline values."""
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
    row.spo2_avg = typed.get("spo2_avg")
    row.azm_total = typed.get("azm_total")
    row.mvpa_minutes = typed.get("mvpa_minutes")
    row.metrics = metrics
    row.point_count = point_count
    row.pulled_at = datetime.utcnow()


def upsert_point(
    db: Session,
    account_id: int,
    datatype: str,
    d: date | None,
    *,
    point_key: str,
    start: datetime | None = None,
    end: datetime | None = None,
    tz_off: int | None = None,
    value: float | None = None,
    payload: dict | None = None,
) -> None:
    """Generic intraday-point upsert keyed by (account, datatype, point_key). Flushes on insert."""
    row = db.scalar(
        select(HealthDataPoint).where(
            HealthDataPoint.provider_account_id == account_id,
            HealthDataPoint.datatype == datatype,
            HealthDataPoint.point_key == point_key,
        )
    )
    if row is None:
        row = HealthDataPoint(
            provider_account_id=account_id, datatype=datatype, point_key=point_key
        )
        db.add(row)
        db.flush()  # autoflush=False: flush so same-run duplicate keys update, not re-add
    row.local_date = d
    row.start_time = start
    row.end_time = end
    row.tz_offset_seconds = tz_off
    row.value = value
    row.payload = payload
