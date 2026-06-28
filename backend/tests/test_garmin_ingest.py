"""Unit tests for Garmin push ingestion → daily_health / health_data_points mapping.

Runs against an in-memory SQLite DB (no network). Verifies the per-datatype merge mapping and
that re-pushing is idempotent (no duplicate rows; values self-heal). Run from `backend/`:

    pytest tests/test_garmin_ingest.py
"""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import garmin_ingest
from app.db import Base
from app.models import DailyHealth, HealthData, HealthDataPoint, ProviderAccount, Study, Subject


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _seed(db, *, intraday_hr=False):
    study = Study(name="S", ingest_intraday_hr=intraday_hr)
    db.add(study)
    db.flush()
    subj = Subject(study_id=study.id, status="registered")
    db.add(subj)
    db.flush()
    acct = ProviderAccount(
        subject_id=subj.id, provider="garmin", registered=True, provider_user_id="U1"
    )
    db.add(acct)
    db.commit()
    return acct


# 2026-06-19, offset -6h. start = 2026-06-19 06:00:00Z → local 2026-06-19 00:00.
_DAILIES = {
    "userId": "U1",
    "userAccessToken": "uat",
    "calendarDate": "2026-06-19",
    "startTimeInSeconds": 1781762400,
    "startTimeOffsetInSeconds": -21600,
    "steps": 8421,
    "distanceInMeters": 6234.5,
    "activeKilocalories": 540,
    "bmrKilocalories": 1600,
    "floorsClimbed": 12,
    "restingHeartRateInBeatsPerMinute": 58,
    "averageHeartRateInBeatsPerMinute": 74,
}

_SLEEPS = {
    "userId": "U1",
    "userAccessToken": "uat",
    "calendarDate": "2026-06-19",
    "startTimeInSeconds": 1781762400,
    "startTimeOffsetInSeconds": -21600,
    "durationInSeconds": 28800,
    "deepSleepDurationInSeconds": 6000,
    "lightSleepDurationInSeconds": 14400,
    "remSleepInSeconds": 5400,
    "awakeDurationInSeconds": 3000,
}

_HRV = {
    "userId": "U1",
    "userAccessToken": "uat",
    "calendarDate": "2026-06-19",
    "startTimeInSeconds": 1781762400,
    "startTimeOffsetInSeconds": -21600,
    "lastNightAvg": 42,
}

_SKIN_TEMP = {
    "userId": "U1",
    "userAccessToken": "uat",
    "calendarDate": "2026-06-19",
    "startTimeInSeconds": 1781762400,
    "startTimeOffsetInSeconds": -21600,
    "durationInSeconds": 28800,
    "avgDeviationCelsius": -0.4,
    "minDeviationCelsius": -1.2,
    "maxDeviationCelsius": 0.3,
}


def _daily(db, acct):
    return db.scalar(
        select(DailyHealth).where(
            DailyHealth.provider_account_id == acct.id,
            DailyHealth.local_date == date(2026, 6, 19),
        )
    )


def test_dailies_mapping(db):
    acct = _seed(db)
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [_DAILIES]})
    row = _daily(db, acct)
    assert row is not None
    assert row.steps == 8421
    assert row.distance_m == pytest.approx(6234.5)
    assert row.calories == pytest.approx(2140.0)  # active + bmr
    assert row.floors == 12
    assert row.resting_hr == 58
    assert row.hr_avg == 74
    assert row.subject_id == acct.subject_id
    assert row.tz_offset_seconds == -21600
    # raw landed in health_data
    assert db.scalar(select(HealthData).where(HealthData.provider == "garmin")) is not None


def test_merge_does_not_clobber_across_datatypes(db):
    acct = _seed(db)
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [_DAILIES]})
    garmin_ingest.ingest_push(db, "sleeps", {"sleeps": [_SLEEPS]})
    garmin_ingest.ingest_push(db, "hrv", {"hrv": [_HRV]})
    row = _daily(db, acct)
    # dailies fields survive the later sleep/hrv pushes
    assert row.steps == 8421
    assert row.sleep_minutes == (6000 + 14400 + 5400) // 60  # deep+light+rem asleep
    assert row.hrv_ms == pytest.approx(42.0)
    assert row.metrics["sleep"]["stages"]["deep_minutes"] == 100


def test_idempotent_repush(db):
    acct = _seed(db)
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [_DAILIES]})
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [_DAILIES]})
    rows = list(
        db.scalars(select(DailyHealth).where(DailyHealth.provider_account_id == acct.id))
    )
    assert len(rows) == 1  # no duplicate daily row
    assert rows[0].steps == 8421


def test_intraday_hr_opt_in(db):
    acct = _seed(db, intraday_hr=True)
    item = dict(_DAILIES, timeOffsetHeartRateSamples={"0": 60, "60": 62, "300": 70, "360": 72})
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [item]})
    pts = list(
        db.scalars(
            select(HealthDataPoint).where(
                HealthDataPoint.provider_account_id == acct.id,
                HealthDataPoint.datatype == "heart_rate",
            )
        )
    )
    assert pts, "expected bucketed intraday HR points"
    # re-push is idempotent at the point level too
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [item]})
    pts2 = list(
        db.scalars(
            select(HealthDataPoint).where(
                HealthDataPoint.provider_account_id == acct.id,
                HealthDataPoint.datatype == "heart_rate",
            )
        )
    )
    assert len(pts2) == len(pts)


def test_skin_temp_mapping(db):
    acct = _seed(db)
    garmin_ingest.ingest_push(db, "skinTemp", {"skinTemp": [_SKIN_TEMP]})
    row = _daily(db, acct)
    assert row is not None
    st = row.metrics["skin_temp"]
    assert st["deviation_c"] == pytest.approx(-0.4)
    assert st["min_deviation_c"] == pytest.approx(-1.2)
    assert st["max_deviation_c"] == pytest.approx(0.3)
    assert st["duration_seconds"] == 28800


def test_skin_temp_field_name_fallback(db):
    """`deviation_c` takes the first present of the spelling variants."""
    acct = _seed(db)
    item = {k: v for k, v in _SKIN_TEMP.items() if k != "avgDeviationCelsius"}
    item["deviationCelsius"] = -0.7
    garmin_ingest.ingest_push(db, "skinTemperature", {"skinTemperature": [item]})
    row = _daily(db, acct)
    assert row.metrics["skin_temp"]["deviation_c"] == pytest.approx(-0.7)


def test_skin_temp_merge_does_not_clobber_dailies(db):
    acct = _seed(db)
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [_DAILIES]})
    garmin_ingest.ingest_push(db, "skinTemp", {"skinTemp": [_SKIN_TEMP]})
    row = _daily(db, acct)
    assert row.steps == 8421  # dailies survives
    assert row.metrics["skin_temp"]["deviation_c"] == pytest.approx(-0.4)


def test_unresolved_account_lands_raw_only(db):
    _seed(db)
    other = dict(_DAILIES, userId="UNKNOWN")
    # Two registered garmin accounts would make the fallback ambiguous; here there's one, but its
    # provider_user_id is already U1, so an unknown userId resolves to nobody → raw-only.
    db.add(ProviderAccount(subject_id=1, provider="garmin", registered=True, provider_user_id="U2"))
    db.commit()
    garmin_ingest.ingest_push(db, "dailies", {"dailies": [other]})
    assert db.scalar(select(HealthData).where(HealthData.provider == "garmin")) is not None
    assert db.scalar(select(DailyHealth)) is None  # nothing aggregated
