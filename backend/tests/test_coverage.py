"""Coverage calendar: per-metric completeness and the study endpoint.

Heart rate, steps, and sleep are scored separately. Zero steps is a recorded
day. Sleep moves to the wake-up date when a session point crosses midnight.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import coverage
from app.coverage import (
    HR_SUFFICIENT_MINUTES,
    SLEEP_SUFFICIENT_MINUTES,
    STEPS_SUFFICIENT_MINUTES,
    assemble_coverage,
    classify_hr,
    classify_sleep,
    classify_steps,
)
from app.db import Base, get_db
from app.main import app
from app.models import DailyHealth, HealthDataPoint, ProviderAccount, Study, StudyMembership, Subject, User
from app.security import get_current_user, require_superuser

NOW = datetime(2026, 11, 24, 18, 0, 0)  # Tuesday
ENROLLED = date(2026, 1, 1)
ACCT = 10


def _subj(**kw):
    base = {
        "id": 1,
        "participant_id": "P-1",
        "subject_label": "ada@umn.edu",
        "status": "registered",
        "archived": False,
        "collection_start": None,
        "collection_end": None,
        "enrolled_on": ENROLLED,
        "account_ids": [ACCT],
    }
    base.update(kw)
    return base


def _daily(day, **kw):
    base = {
        "account_id": ACCT,
        "local_date": day,
        "steps": None,
        "hr_avg": None,
        "resting_hr": None,
        "sleep_minutes": None,
        "pulled_at": None,
        "tz_offset_seconds": 0,
        "non_wear_minutes": None,
    }
    base.update(kw)
    return base


def _build(subjects, dailies=None, point_aggs=None, sleep_points=None, span="7d", **kw):
    return assemble_coverage(
        subjects=subjects,
        dailies=dailies or [],
        point_aggs=point_aggs or [],
        sleep_points=sleep_points or [],
        span=span,
        custom_start=kw.get("custom_start"),
        custom_end=kw.get("custom_end"),
        now=kw.get("now", NOW),
    )


def _day(payload, iso, subject_id=1):
    sub = next(s for s in payload["subjects"] if s["id"] == subject_id)
    return next(d for d in sub["days"] if d["date"] == iso)


def _sub(payload, subject_id=1):
    return next(s for s in payload["subjects"] if s["id"] == subject_id)


def test_classify_hr_thresholds():
    assert classify_hr(coverage_minutes=HR_SUFFICIENT_MINUTES, has_intraday=True, hr_avg=70, resting_hr=60) == (
        "sufficient",
        "intraday",
    )
    # A short intraday wear wins over the daily average: partial, not sufficient.
    assert classify_hr(coverage_minutes=HR_SUFFICIENT_MINUTES - 1, has_intraday=True, hr_avg=70, resting_hr=60) == (
        "partial",
        "intraday",
    )
    assert classify_hr(coverage_minutes=None, has_intraday=False, hr_avg=70, resting_hr=60) == (
        "sufficient",
        "daily_summary",
    )
    assert classify_hr(coverage_minutes=None, has_intraday=False, hr_avg=None, resting_hr=60) == (
        "partial",
        "resting_only",
    )
    assert classify_hr(coverage_minutes=None, has_intraday=False, hr_avg=None, resting_hr=None) == (
        "missing",
        "none",
    )


def test_classify_steps_zero_is_recorded_and_nonwear_is_not():
    assert classify_steps(total=0, coverage_minutes=None, has_recording=False) == ("sufficient", "daily_total")
    assert classify_steps(total=None, coverage_minutes=None, has_recording=False) == ("missing", "none")
    assert classify_steps(total=0, coverage_minutes=STEPS_SUFFICIENT_MINUTES, has_recording=True) == (
        "sufficient",
        "intraday",
    )
    assert classify_steps(total=8000, coverage_minutes=120, has_recording=True) == ("partial", "intraday")
    # Whole-day non-wear reports a recording series of zero minutes: not a valid zero.
    assert classify_steps(total=0, coverage_minutes=0, has_recording=True) == ("missing", "intraday")


def test_classify_sleep_thresholds():
    assert classify_sleep(SLEEP_SUFFICIENT_MINUTES) == ("sufficient", "wake_date")
    assert classify_sleep(SLEEP_SUFFICIENT_MINUTES - 1) == ("partial", "wake_date")
    assert classify_sleep(0) == ("missing", "none")
    assert classify_sleep(None) == ("missing", "none")


def test_sleep_point_moves_to_wake_date_and_ignores_bedtime_total():
    payload = _build(
        [_subj()],
        dailies=[_daily(date(2026, 11, 17), sleep_minutes=999, pulled_at=NOW)],
        sleep_points=[
            {
                "account_id": ACCT,
                "local_date": date(2026, 11, 17),
                "start": datetime(2026, 11, 17, 22, 0),
                "end": datetime(2026, 11, 18, 6, 0),
                "tz_offset_seconds": 0,
                "payload": {
                    "sleep": {
                        "stages": [
                            {"type": "LIGHT", "startTime": "2026-11-17T22:00:00Z", "endTime": "2026-11-18T02:00:00Z"},
                            {"type": "DEEP", "startTime": "2026-11-18T02:00:00Z", "endTime": "2026-11-18T04:00:00Z"},
                            {"type": "AWAKE", "startTime": "2026-11-18T04:00:00Z", "endTime": "2026-11-18T06:00:00Z"},
                        ]
                    }
                },
            }
        ],
    )
    wake = _day(payload, "2026-11-18")
    bed = _day(payload, "2026-11-17")
    assert wake["sleep"]["status"] == "sufficient"
    assert wake["sleep"]["minutes"] == 360  # 4h light + 2h deep; awake excluded
    assert bed["sleep"]["status"] == "missing"
    assert bed["sleep"]["minutes"] is None


def test_sleep_without_points_stays_on_the_stored_day():
    """Garmin and Oura already store sleep on the wake-up calendar day."""
    payload = _build(
        [_subj()],
        dailies=[
            _daily(date(2026, 11, 18), sleep_minutes=300),
            _daily(date(2026, 11, 19), sleep_minutes=90),
        ],
    )
    assert _day(payload, "2026-11-18")["sleep"]["status"] == "sufficient"
    assert _day(payload, "2026-11-19")["sleep"]["status"] == "partial"


def test_last_seven_dims_outside_the_week_and_hatches_the_future():
    payload = _build(
        [_subj()],
        dailies=[_daily(date(2026, 11, 20), steps=0, hr_avg=71, pulled_at=NOW)],
    )
    assert payload["weeks"][0]["dates"][0] == "2026-11-16"
    assert date.fromisoformat(payload["weeks"][0]["start"]).weekday() == 0
    # Tuesday Nov 24 → selected window is Nov 18–24. Mon/Tue of that week are in range;
    # the previous Monday and the days after today are not.
    assert _day(payload, "2026-11-16")["dimmed"] is True
    assert _day(payload, "2026-11-18")["dimmed"] is False
    assert _day(payload, "2026-11-24")["dimmed"] is False
    assert _day(payload, "2026-11-25")["dimmed"] is True
    assert _day(payload, "2026-11-25")["expected"] is False
    assert _day(payload, "2026-11-25")["reason"] == "future"
    # Zero steps, no intraday series: sufficient. Daily HR average with no intraday: sufficient.
    nov20 = _day(payload, "2026-11-20")
    assert nov20["steps"] == {
        "status": "sufficient",
        "basis": "daily_total",
        "total": 0,
        "minutes": None,
        "fraction": None,
    }
    assert nov20["hr"]["status"] == "sufficient"
    assert nov20["hr"]["basis"] == "daily_summary"
    assert nov20["hr"]["hr_avg"] == 71
    sub = _sub(payload)
    assert sub["last_pull_at"] == "2026-11-24T18:00:00Z"
    assert sub["on_screen"]["expected"] == 7
    assert sub["on_screen"]["hr_sufficient"] == 1
    assert sub["on_screen"]["steps_sufficient"] == 1


def test_collection_window_is_not_expected_even_with_data():
    payload = _build(
        [_subj(collection_start=date(2026, 11, 21), collection_end=date(2026, 11, 22))],
        dailies=[_daily(date(2026, 11, 20), hr_avg=80, steps=1000)],
    )
    outside = _day(payload, "2026-11-20")
    assert outside["expected"] is False
    assert outside["reason"] == "collection_window"
    assert outside["hr"]["hr_avg"] == 80  # numbers remain for the hover
    assert _day(payload, "2026-11-21")["expected"] is True
    assert _day(payload, "2026-11-23")["reason"] == "collection_window"
    # On screen, only Nov 21–22 count. Neither has HR, so 0/2.
    assert _sub(payload)["on_screen"] == {
        "hr_sufficient": 0,
        "steps_sufficient": 0,
        "sleep_sufficient": 0,
        "expected": 2,
    }


def test_intraday_minutes_and_oura_nonwear():
    payload = _build(
        [_subj()],
        dailies=[
            _daily(date(2026, 11, 18), steps=4000, hr_avg=70),
            _daily(date(2026, 11, 19), steps=0, non_wear_minutes=1440),
            _daily(date(2026, 11, 20), steps=50, non_wear_minutes=1000),
        ],
        point_aggs=[
            {"account_id": ACCT, "local_date": date(2026, 11, 18), "datatype": "heart_rate", "minutes": 100, "value_sum": None},
            {"account_id": ACCT, "local_date": date(2026, 11, 18), "datatype": "steps", "minutes": 90, "value_sum": 4000},
            {"account_id": ACCT, "local_date": date(2026, 11, 21), "datatype": "heart_rate", "minutes": 800, "value_sum": None},
        ],
    )
    short = _day(payload, "2026-11-18")
    assert short["hr"]["status"] == "partial"
    assert short["hr"]["minutes"] == 100
    assert short["steps"]["status"] == "partial"
    assert short["steps"]["minutes"] == 90
    assert short["steps"]["total"] == 4000
    unworn = _day(payload, "2026-11-19")
    assert unworn["steps"]["status"] == "missing"
    assert unworn["steps"]["minutes"] == 0
    partial_wear = _day(payload, "2026-11-20")
    assert partial_wear["steps"]["status"] == "partial"
    assert partial_wear["steps"]["minutes"] == 440  # 1440 - 1000
    assert _day(payload, "2026-11-21")["hr"]["status"] == "sufficient"


def test_local_today_follows_the_participant_offset():
    # 04:00 UTC is still Nov 23 in UTC-6.
    payload = _build(
        [_subj()],
        dailies=[_daily(date(2026, 11, 20), tz_offset_seconds=-6 * 3600)],
        now=datetime(2026, 11, 24, 4, 0, 0),
    )
    sub = _sub(payload)
    assert sub["local_today"] == "2026-11-23"
    assert sub["tz_offset_seconds"] == -6 * 3600
    assert _day(payload, "2026-11-23")["dimmed"] is False
    assert _day(payload, "2026-11-24")["reason"] == "future"


def test_before_enrollment_is_hatched_and_to_date_starts_then():
    payload = _build([_subj(enrolled_on=date(2026, 11, 22))])
    assert _day(payload, "2026-11-21")["expected"] is False
    assert _day(payload, "2026-11-21")["reason"] == "before_enrollment"
    assert _day(payload, "2026-11-22")["expected"] is True
    assert _sub(payload)["on_screen"]["expected"] == 3  # 22, 23, 24
    assert _sub(payload)["to_date"]["expected"] == 3


def test_custom_range_rejects_inverted_and_huge_windows():
    with pytest.raises(coverage.CoverageQueryError):
        _build([_subj()], span="custom")
    with pytest.raises(coverage.CoverageQueryError):
        _build(
            [_subj()],
            span="custom",
            custom_start=date(2026, 11, 20),
            custom_end=date(2026, 11, 19),
        )
    with pytest.raises(coverage.CoverageQueryError):
        _build(
            [_subj()],
            span="custom",
            custom_start=date(2020, 1, 1),
            custom_end=date(2026, 1, 1),
        )


def test_archived_participants_sort_after_active():
    payload = _build(
        [
            _subj(id=2, participant_id="B", archived=True),
            _subj(id=1, participant_id="A", account_ids=[11]),
        ]
    )
    assert [s["id"] for s in payload["subjects"]] == [1, 2]


# --- HTTP -------------------------------------------------------------------


@pytest.fixture()
def ctx(monkeypatch):
    monkeypatch.setattr(coverage, "_utcnow", lambda: NOW)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    member = User(email="member@umn.edu", is_superuser=False)
    outsider = User(email="outsider@umn.edu", is_superuser=False)
    s.add_all([member, outsider])
    s.flush()
    study = Study(name="Coverage", provider="fitbit_gh")
    s.add(study)
    s.flush()
    s.add(StudyMembership(user_id=member.id, study_id=study.id, role="member"))
    s.commit()
    ids = {"member": member.id, "outsider": outsider.id, "study": study.id}
    s.close()

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db

    def as_user(uid):
        app.dependency_overrides[get_current_user] = lambda: Session().get(User, uid)
        app.dependency_overrides[require_superuser] = lambda: Session().get(User, uid)
        return TestClient(app)

    yield as_user, ids, Session
    app.dependency_overrides.clear()


def _seed(Session, study_id, *, archived=False, collection_start=None, collection_end=None):
    db = Session()
    subj = Subject(
        study_id=study_id,
        participant_id="P-1",
        subject_label="ada@umn.edu",
        status="registered",
        collection_start=collection_start,
        collection_end=collection_end,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        archived_at=NOW if archived else None,
    )
    db.add(subj)
    db.flush()
    acct = ProviderAccount(subject_id=subj.id, provider="fitbit_gh", entry_code=f"CODE{subj.id}")
    db.add(acct)
    db.flush()
    db.add(
        DailyHealth(
            provider_account_id=acct.id,
            subject_id=subj.id,
            local_date=date(2026, 11, 17),
            steps=None,
            hr_avg=64,
            sleep_minutes=999,  # bedtime-dated total; the sleep point must override it
            tz_offset_seconds=0,
            pulled_at=NOW - timedelta(hours=2),
            metrics={"activity": {"non_wear_minutes": 200}},
        )
    )
    db.add(
        DailyHealth(
            provider_account_id=acct.id,
            subject_id=subj.id,
            local_date=date(2026, 11, 20),
            steps=0,
            hr_avg=None,
            resting_hr=58,
            tz_offset_seconds=0,
            pulled_at=NOW,
        )
    )
    db.add(
        HealthDataPoint(
            provider_account_id=acct.id,
            datatype="heart_rate",
            point_key="hr|nov18",
            local_date=date(2026, 11, 18),
            start_time=datetime(2026, 11, 18, 8, 0),
            end_time=datetime(2026, 11, 18, 18, 0),  # 600 min; payload samples must not be used
            value=72,
            payload={"samples": 30, "bucket_minutes": 5, "bpm_avg": 72},
        )
    )
    db.add(
        HealthDataPoint(
            provider_account_id=acct.id,
            datatype="steps",
            point_key="steps|nov18",
            local_date=date(2026, 11, 18),
            start_time=datetime(2026, 11, 18, 9, 0),
            end_time=datetime(2026, 11, 18, 9, 5),
            value=120,
            payload={"samples": 30, "sum": 120, "bucket_minutes": 5},
        )
    )
    db.add(
        HealthDataPoint(
            provider_account_id=acct.id,
            datatype="sleep",
            point_key="sleep|night",
            local_date=date(2026, 11, 17),
            start_time=datetime(2026, 11, 17, 22, 0),
            end_time=datetime(2026, 11, 18, 6, 0),
            tz_offset_seconds=0,
            payload={
                "sleep": {
                    "stages": [
                        {"type": "LIGHT", "startTime": "2026-11-17T22:00:00Z", "endTime": "2026-11-18T02:00:00Z"},
                        {"type": "DEEP", "startTime": "2026-11-18T02:00:00Z", "endTime": "2026-11-18T04:00:00Z"},
                        {"type": "AWAKE", "startTime": "2026-11-18T04:00:00Z", "endTime": "2026-11-18T06:00:00Z"},
                    ]
                }
            },
        )
    )
    db.commit()
    ids = {"subject": subj.id, "account": acct.id}
    db.close()
    return ids


def test_endpoint_scores_stored_points_and_hides_archived(ctx):
    as_user, ids, Session = ctx
    seeded = _seed(Session, ids["study"])
    hidden = _seed(Session, ids["study"], archived=True)

    # Each as_user() replaces the auth override, so rebind before the next call.
    denied = as_user(ids["outsider"]).get(f"/admin/studies/{ids['study']}/coverage")
    assert denied.status_code == 403

    client = as_user(ids["member"])
    missing = client.get("/admin/studies/999999/coverage")
    assert missing.status_code == 404

    bad = client.get(f"/admin/studies/{ids['study']}/coverage?range=custom")
    assert bad.status_code == 400

    res = client.get(f"/admin/studies/{ids['study']}/coverage")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["range"] == "7d"
    assert body["thresholds"]["hr_sufficient_minutes"] == 600
    assert [s["id"] for s in body["subjects"]] == [seeded["subject"]]

    nov18 = _day(body, "2026-11-18", seeded["subject"])
    assert nov18["hr"]["status"] == "sufficient"
    assert nov18["hr"]["minutes"] == 600
    assert nov18["steps"]["status"] == "partial"
    assert nov18["steps"]["minutes"] == 30  # payload samples, not the 5-minute bucket width
    assert nov18["steps"]["total"] == 120
    assert nov18["sleep"]["status"] == "sufficient"
    assert nov18["sleep"]["minutes"] == 360

    nov17 = _day(body, "2026-11-17", seeded["subject"])
    assert nov17["sleep"]["status"] == "missing"
    assert nov17["hr"]["status"] == "sufficient"  # daily average, intraday not stored
    assert nov17["hr"]["basis"] == "daily_summary"
    # non-wear 200 → 1240 recording minutes, and steps is null so the series decides
    assert nov17["steps"]["status"] == "sufficient"
    assert nov17["steps"]["minutes"] == 1240

    nov20 = _day(body, "2026-11-20", seeded["subject"])
    assert nov20["steps"]["status"] == "sufficient"
    assert nov20["steps"]["total"] == 0
    assert nov20["hr"]["status"] == "partial"
    assert nov20["hr"]["basis"] == "resting_only"

    shown = client.get(f"/admin/studies/{ids['study']}/coverage?include_archived=true")
    assert shown.status_code == 200
    assert {s["id"] for s in shown.json()["subjects"]} == {seeded["subject"], hidden["subject"]}

    # The archived row is still readable directly; confirm the flag default really dropped it.
    assert hidden["subject"] not in {s["id"] for s in body["subjects"]}


def test_endpoint_custom_range_dims_to_full_weeks(ctx):
    as_user, ids, Session = ctx
    seeded = _seed(Session, ids["study"])
    client = as_user(ids["member"])
    res = client.get(
        f"/admin/studies/{ids['study']}/coverage?range=custom&start=2026-11-18&end=2026-11-20"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert _day(body, "2026-11-16", seeded["subject"])["dimmed"] is True
    assert _day(body, "2026-11-18", seeded["subject"])["dimmed"] is False
    assert _day(body, "2026-11-20", seeded["subject"])["dimmed"] is False
    assert _day(body, "2026-11-21", seeded["subject"])["dimmed"] is True
    sub = _sub(body, seeded["subject"])
    assert sub["on_screen"]["expected"] == 3


def test_full_calendar_keeps_earlier_scores_and_the_last_seven_window():
    """One payload can be sliced: pre-enrollment data stays scored, and the grid
    still reaches six days before local today when enrollment is more recent."""
    payload = _build(
        [_subj(enrolled_on=date(2026, 11, 22))],
        dailies=[_daily(date(2026, 11, 10), steps=5, hr_avg=60, pulled_at=NOW)],
        span="full",
    )
    sub = _sub(payload)
    assert payload["range"] == "full"
    assert sub["enrolled_on"] == "2026-11-22"
    assert sub["all_start"] == "2026-11-22"
    assert sub["all_end"] == "2026-11-24"
    assert sub["on_screen"] == sub["to_date"]
    assert sub["to_date"]["expected"] == 3  # 22, 23, 24

    early = _day(payload, "2026-11-10")
    assert early["steps"]["total"] == 5
    assert early["hr"]["hr_avg"] == 60
    assert early["expected"] is False
    assert early["reason"] == "before_enrollment"
    assert early["dimmed"] is True  # outside the all-data window

    # Tuesday Nov 24 → last-7 starts Nov 18, whose Monday is Nov 16.
    assert _day(payload, "2026-11-16")["dimmed"] is True
    assert payload["weeks"][0]["dates"][0] <= "2026-11-09"

    seven = _build(
        [_subj(enrolled_on=date(2026, 11, 22))],
        dailies=[_daily(date(2026, 11, 10), steps=5, hr_avg=60, pulled_at=NOW)],
        span="7d",
    )
    assert _sub(seven)["to_date"] == sub["to_date"]
    assert _sub(seven)["on_screen"]["expected"] == 3
    assert "all_start" not in _sub(seven)


def test_endpoint_full_range_exposes_slice_fields(ctx):
    as_user, ids, Session = ctx
    seeded = _seed(Session, ids["study"])
    client = as_user(ids["member"])
    res = client.get(f"/admin/studies/{ids['study']}/coverage?range=full")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["range"] == "full"
    sub = _sub(body, seeded["subject"])
    assert sub["enrolled_on"] == "2026-01-01"
    assert sub["all_start"] == "2026-01-01"
    assert sub["all_end"] == "2026-11-24"
    nov18 = _day(body, "2026-11-18", seeded["subject"])
    assert nov18["hr"]["status"] == "sufficient"
    assert nov18["dimmed"] is False
    # Full uses the all-data window for on_screen. With no collection end before
    # today, that tally is the same as to_date.
    assert sub["on_screen"] == sub["to_date"]
