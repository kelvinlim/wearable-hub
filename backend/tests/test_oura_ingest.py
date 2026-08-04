"""Oura provider tests: mapping, consolidation, token rotation, webhooks, enrollment dispatch.

Runs against an in-memory SQLite DB with all Oura HTTP calls monkeypatched (no network).
Fixture payloads are shaped like /v2/sandbox/usercollection/* responses. Run from `backend/`:

    pytest tests/test_oura_ingest.py
"""

import hashlib
import hmac
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import consolidation, oura_ingest
from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import (
    ConsolidationState,
    DailyHealth,
    HealthData,
    HealthDataPoint,
    ProviderAccount,
    Study,
    Subject,
    User,
)
from app.providers import oura
from app.providers.base import TokenResult
from app.security import get_current_user, require_superuser

D = date(2026, 7, 30)


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


def _seed(db, *, intraday_hr=False, intraday_hrv=False, user_id="OU1", **subject_kw):
    study = Study(
        name="S", provider="oura", ingest_intraday_hr=intraday_hr, ingest_intraday_hrv=intraday_hrv
    )
    db.add(study)
    db.flush()
    subj = Subject(study_id=study.id, status="registered", **subject_kw)
    db.add(subj)
    db.flush()
    acct = ProviderAccount(
        subject_id=subj.id, provider="oura", registered=True, provider_user_id=user_id,
        access_token="at", refresh_token="rt",
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(acct)
    db.commit()
    return acct


# --- sandbox-shaped fixture documents --------------------------------------------

_ACTIVITY = {
    "id": "a1",
    "day": D.isoformat(),
    "timestamp": "2026-07-30T04:00:00-05:00",
    "score": 82,
    "steps": 9876,
    "active_calories": 450,
    "total_calories": 2450,
    "equivalent_walking_distance": 7100,
    "high_activity_time": 1200,      # 20 min
    "medium_activity_time": 3000,    # 50 min
    "low_activity_time": 14400,
    "sedentary_time": 28800,
    "non_wear_time": 600,
    "average_met_minutes": 1.4,
}

# Two sleep periods (a nap + the main night) — aggregation must sum and weight them.
_SLEEP_MAIN = {
    "id": "s1",
    "day": D.isoformat(),
    "type": "long_sleep",
    "bedtime_start": "2026-07-29T23:30:00-05:00",
    "bedtime_end": "2026-07-30T07:00:00-05:00",
    "total_sleep_duration": 24000,   # 400 min
    "deep_sleep_duration": 6000,     # 100 min
    "light_sleep_duration": 12000,   # 200 min
    "rem_sleep_duration": 6000,      # 100 min
    "awake_time": 3000,              # 50 min
    "efficiency": 89,
    "average_heart_rate": 58.0,
    "lowest_heart_rate": 47,
    "average_hrv": 45,
    "hrv": {
        "interval": 300.0,
        "timestamp": "2026-07-30T04:30:00-05:00",
        "items": [40.0, None, 52.0],
    },
}
_SLEEP_NAP = {
    "id": "s2",
    "day": D.isoformat(),
    "type": "sleep",
    "bedtime_start": "2026-07-30T14:00:00-05:00",
    "bedtime_end": "2026-07-30T14:40:00-05:00",
    "total_sleep_duration": 2400,    # 40 min
    "light_sleep_duration": 2400,
    "awake_time": 0,
    "average_heart_rate": 62.0,
    "lowest_heart_rate": 55,
    "average_hrv": 30,
}

_DAILY_SLEEP = {"id": "ds1", "day": D.isoformat(), "score": 78}
_READINESS = {"id": "r1", "day": D.isoformat(), "score": 85, "temperature_deviation": -0.2}
_SPO2 = {
    "id": "o1", "day": D.isoformat(),
    "spo2_percentage": {"average": 97.234},
    "breathing_disturbance_index": 2,
}
_STRESS = {
    "id": "st1", "day": D.isoformat(),
    "stress_high": 1800, "recovery_high": 5400, "day_summary": "normal",
}
_WORKOUT = {
    "id": "w1", "day": D.isoformat(), "activity": "running", "intensity": "moderate",
    "calories": 320, "distance": 5000,
    "start_datetime": "2026-07-30T17:00:00-05:00", "end_datetime": "2026-07-30T17:40:00-05:00",
}
_HEARTRATE = [
    {"bpm": 60, "source": "ppg", "timestamp": "2026-07-30T10:00:30-05:00"},
    {"bpm": 70, "source": "ppg", "timestamp": "2026-07-30T10:02:00-05:00"},
    {"bpm": 80, "source": "ppg", "timestamp": "2026-07-30T10:07:00-05:00"},
]

_COLLECTIONS = {
    "daily_activity": [_ACTIVITY],
    "sleep": [_SLEEP_MAIN, _SLEEP_NAP],
    "daily_sleep": [_DAILY_SLEEP],
    "daily_readiness": [_READINESS],
    "daily_spo2": [_SPO2],
    "daily_stress": [_STRESS],
    "workout": [_WORKOUT],
    "session": [],
    "enhanced_tag": [],
}


def _patch_pulls(monkeypatch, collections=None, heartrate=None):
    data = _COLLECTIONS if collections is None else collections
    monkeypatch.setattr(
        oura, "fetch_collection", lambda token, dt, start, end: list(data.get(dt, []))
    )
    monkeypatch.setattr(
        oura, "fetch_heartrate",
        lambda token, s, e: list(_HEARTRATE if heartrate is None else heartrate),
    )
    monkeypatch.setattr(oura_ingest, "_fresh_token", lambda db, acct: "tok")


# --- mapping units ---------------------------------------------------------------

def test_map_daily_activity():
    typed, metrics = oura_ingest.map_daily_activity(_ACTIVITY)
    assert typed["steps"] == 9876
    assert typed["distance_m"] == 7100
    assert typed["calories"] == 2450
    assert typed["mvpa_minutes"] == 70  # (1200 + 3000) / 60
    assert metrics["score"] == 82
    assert metrics["high_minutes"] == 20
    assert metrics["sedentary_minutes"] == 480


def test_aggregate_sleep_multi_period():
    typed, metrics, tz_off = oura_ingest.aggregate_sleep([_SLEEP_MAIN, _SLEEP_NAP])
    assert typed["sleep_minutes"] == 440  # 400 + 40
    # duration-weighted HRV: (45*24000 + 30*2400) / 26400
    assert typed["hrv_ms"] == pytest.approx(43.6, abs=0.05)
    assert typed["resting_hr"] == 47  # min lowest_heart_rate across periods
    assert metrics["stages"] == {"DEEP": 100, "LIGHT": 240, "REM": 100, "AWAKE": 50}
    assert metrics["total_min"] == 490
    assert metrics["asleep_min"] == 440
    assert metrics["segments"] == 2
    assert metrics["efficiency"] == 89
    assert tz_off == -5 * 3600  # from bedtime_start offset


def test_aggregate_sleep_empty():
    typed, metrics, tz_off = oura_ingest.aggregate_sleep([])
    assert typed == {} and metrics == {} and tz_off is None


def test_map_daily_stress_and_readiness():
    assert oura_ingest.map_daily_stress(_STRESS) == {
        "high_minutes": 30, "recovery_minutes": 90, "day_summary": "normal",
    }
    r = oura_ingest.map_daily_readiness(_READINESS)
    assert r == {"score": 85, "temperature_deviation": -0.2}


def test_bucket_hr_samples():
    samples = [
        (datetime(2026, 7, 30, 10, 0, 30), 60.0),
        (datetime(2026, 7, 30, 10, 2, 0), 70.0),
        (datetime(2026, 7, 30, 10, 7, 0), 80.0),
    ]
    buckets = oura_ingest.bucket_hr_samples(samples, 5)
    assert len(buckets) == 2
    assert buckets[0]["avg"] == 65.0 and buckets[0]["n"] == 2
    assert buckets[1]["avg"] == 80.0 and buckets[1]["n"] == 1
    # bucket_min <= 0 keeps raw samples
    assert len(oura_ingest.bucket_hr_samples(samples, 0)) == 3


def test_for_day_filters_by_local_day():
    other = {**_ACTIVITY, "day": "2026-07-29"}
    assert oura_ingest._for_day([_ACTIVITY, other], D) == [_ACTIVITY]


# --- consolidate_day -------------------------------------------------------------

def test_consolidate_day_full(db, monkeypatch):
    acct = _seed(db)
    _patch_pulls(monkeypatch)
    state = oura_ingest.consolidate_day(db, acct, D)
    assert state.status == "done"

    row = db.scalar(select(DailyHealth).where(DailyHealth.provider_account_id == acct.id))
    assert row.local_date == D
    assert row.steps == 9876
    assert row.distance_m == 7100
    assert row.calories == 2450
    assert row.mvpa_minutes == 70
    assert row.sleep_minutes == 440
    assert row.resting_hr == 47
    assert row.hrv_ms == pytest.approx(43.6, abs=0.05)
    assert row.spo2_avg == 97.2
    assert row.hr_avg == 70.0  # mean of the intraday samples (60, 70, 80)
    assert row.tz_offset_seconds == -5 * 3600

    m = row.metrics
    assert m["sleep"]["score"] == 78
    assert m["sleep"]["stages"]["DEEP"] == 100
    assert m["readiness"]["temperature_deviation"] == -0.2
    assert m["stress"]["day_summary"] == "normal"
    assert m["workouts"]["count"] == 1
    assert m["workouts"]["items"][0]["activity"] == "running"
    assert m["heart_rate"]["samples"] == 3
    assert "_errors" not in m

    # Intraday flags are off -> no points stored.
    assert db.scalar(select(HealthDataPoint)) is None
    assert row.point_count == 0


def test_consolidate_day_intraday_opt_ins(db, monkeypatch):
    acct = _seed(db, intraday_hr=True, intraday_hrv=True)
    _patch_pulls(monkeypatch)
    state = oura_ingest.consolidate_day(db, acct, D)
    assert state.status == "done"

    hr_pts = list(db.scalars(
        select(HealthDataPoint).where(HealthDataPoint.datatype == "heart_rate")
    ))
    assert len(hr_pts) == 2  # 5-min buckets from the 3 samples
    assert {p.value for p in hr_pts} == {65.0, 80.0}

    hrv_pts = list(db.scalars(
        select(HealthDataPoint).where(HealthDataPoint.datatype == "heart_rate_variability")
    ))
    assert len(hrv_pts) == 2  # None item in the series is skipped
    assert {p.value for p in hrv_pts} == {40.0, 52.0}
    # 5-min spacing from the series timestamp (UTC: 09:30 + i*300s)
    assert {p.start_time for p in hrv_pts} == {
        datetime(2026, 7, 30, 9, 30), datetime(2026, 7, 30, 9, 40),
    }

    row = db.scalar(select(DailyHealth))
    assert row.point_count == 4
    # Re-running is idempotent (replace-then-upsert).
    oura_ingest.consolidate_day(db, acct, D)
    assert len(list(db.scalars(select(HealthDataPoint)))) == 4


def test_consolidate_day_outside_window_skips(db, monkeypatch):
    acct = _seed(db, collection_start=D + timedelta(days=5))

    def _boom(*a, **k):
        raise AssertionError("no API call expected outside the collection window")

    monkeypatch.setattr(oura_ingest, "_fresh_token", _boom)
    state = oura_ingest.consolidate_day(db, acct, D)
    assert state.status == "skipped"
    assert db.scalar(select(DailyHealth)) is None


def test_consolidate_day_fault_isolation(db, monkeypatch):
    """One data type's HTTP error is recorded in metrics._errors, the rest still lands."""
    import httpx

    acct = _seed(db)

    def _fetch(token, dt, start, end):
        if dt == "daily_spo2":
            resp = httpx.Response(500, request=httpx.Request("GET", "http://x"), text="boom")
            raise httpx.HTTPStatusError("boom", request=resp.request, response=resp)
        return list(_COLLECTIONS.get(dt, []))

    monkeypatch.setattr(oura, "fetch_collection", _fetch)
    monkeypatch.setattr(oura, "fetch_heartrate", lambda t, s, e: list(_HEARTRATE))
    monkeypatch.setattr(oura_ingest, "_fresh_token", lambda db, acct: "tok")

    state = oura_ingest.consolidate_day(db, acct, D)
    assert state.status == "done"
    row = db.scalar(select(DailyHealth))
    assert row.steps == 9876
    assert row.spo2_avg is None
    assert row.metrics["_errors"] == {"spo2": 500}


def test_consolidate_day_revoked_grant(db, monkeypatch):
    acct = _seed(db)

    def _revoked(db_, acct_):
        raise oura.GrantRevokedError("revoked")

    monkeypatch.setattr(oura_ingest, "_fresh_token", _revoked)
    state = oura_ingest.consolidate_day(db, acct, D)
    assert state.status == "error" and "revoked" in state.detail
    db.refresh(acct)
    assert acct.registered is False
    assert db.get(Subject, acct.subject_id).status == "revoked"


# --- token rotation --------------------------------------------------------------

def test_fresh_token_rotation_committed(db, monkeypatch):
    """A refresh must persist BOTH rotated tokens and commit before returning (single-use
    refresh tokens: an uncommitted rotation would orphan the grant)."""
    acct = _seed(db)
    acct.token_expires_at = datetime.utcnow() - timedelta(minutes=1)  # force refresh
    db.commit()

    monkeypatch.setattr(oura_ingest, "encrypt", lambda v: v)
    monkeypatch.setattr(oura_ingest, "decrypt", lambda v: v)
    monkeypatch.setattr(
        oura, "refresh",
        lambda rt: TokenResult(
            access_token="new-at", refresh_token="new-rt",
            expires_at=datetime.utcnow() + timedelta(hours=24),
            scope="daily", provider_user_id=None, raw={},
        ),
    )
    token = oura_ingest._fresh_token(db, acct)
    assert token == "new-at"

    db.rollback()  # a rollback after the call must NOT lose the rotation
    db.refresh(acct)
    assert acct.access_token == "new-at"
    assert acct.refresh_token == "new-rt"


def test_fresh_token_skips_refresh_when_valid(db, monkeypatch):
    acct = _seed(db)  # expires in 1h
    monkeypatch.setattr(oura_ingest, "decrypt", lambda v: v)
    monkeypatch.setattr(
        oura, "refresh", lambda rt: (_ for _ in ()).throw(AssertionError("no refresh expected"))
    )
    assert oura_ingest._fresh_token(db, acct) == "at"


# --- consolidate_due dispatch ----------------------------------------------------

def test_consolidate_due_dispatches_by_provider(db, monkeypatch):
    oura_acct = _seed(db)
    subj = Subject(study_id=db.get(Subject, oura_acct.subject_id).study_id, status="registered")
    db.add(subj)
    db.flush()
    fitbit_acct = ProviderAccount(subject_id=subj.id, provider="fitbit_gh", registered=True)
    db.add(fitbit_acct)
    db.commit()
    consolidation.mark_dirty(db, oura_acct.id, [D])
    consolidation.mark_dirty(db, fitbit_acct.id, [D])

    calls = []

    def _fake(kind):
        def run(db_, acct, d):
            calls.append((kind, acct.id))
            row = db_.scalar(select(ConsolidationState).where(
                ConsolidationState.provider_account_id == acct.id))
            row.status = "done"
            db_.commit()
            return row
        return run

    monkeypatch.setattr(oura_ingest, "consolidate_day", _fake("oura"))
    monkeypatch.setattr(consolidation, "consolidate_day", _fake("google"))
    result = consolidation.consolidate_due(db)
    assert result == {"done": 2, "errors": 0}
    assert ("oura", oura_acct.id) in calls
    assert ("google", fitbit_acct.id) in calls


# --- HTTP layer: webhooks + enrollment + admin ------------------------------------

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    seed = TestingSession()
    su = User(email="su@umn.edu", name="Su", is_superuser=True)
    seed.add(su)
    seed.commit()
    seed.refresh(su)
    seed.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: TestingSession().get(User, su.id)
    app.dependency_overrides[require_superuser] = lambda: TestingSession().get(User, su.id)

    # Webhook secrets/tokens for the Oura routes, without touching the real env.
    test_settings = get_settings().model_copy(
        update={
            "oura_client_id": "cid",
            "oura_client_secret": "csecret",
            "oura_webhook_verification_token": "vtoken",
            "oura_webhook_data_types": "daily_activity sleep",
            "oura_webhook_event_types": "create update",
        }
    )
    import app.routers.admin as admin_module
    import app.routers.webhooks as webhooks_module
    monkeypatch.setattr(webhooks_module, "get_settings", lambda: test_settings)
    monkeypatch.setattr(admin_module, "get_settings", lambda: test_settings)
    monkeypatch.setattr("app.providers.oura.get_settings", lambda: test_settings)
    # Keep webhook BackgroundTasks off the real database.
    monkeypatch.setattr(consolidation, "run_due_background", lambda: None)

    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def _sign(body: bytes) -> str:
    return hmac.new(b"csecret", body, hashlib.sha256).hexdigest()


def test_webhook_challenge(client):
    c, _ = client
    r = c.get("/webhooks/oura", params={"verification_token": "vtoken", "challenge": "abc123"})
    assert r.status_code == 200
    assert r.json() == {"challenge": "abc123"}
    assert c.get(
        "/webhooks/oura", params={"verification_token": "wrong", "challenge": "abc123"}
    ).status_code == 401
    assert c.get("/webhooks/oura", params={"verification_token": "vtoken"}).status_code == 401


def test_webhook_event_marks_dirty(client):
    c, Session = client
    s = Session()
    acct = _seed(s, user_id="OU9")
    acct_id = acct.id
    s.close()

    event = {
        "event_type": "create", "data_type": "daily_sleep", "object_id": "obj1",
        "event_time": "2026-07-30T12:00:00+00:00", "user_id": "OU9",
    }
    body = json.dumps(event).encode()
    r = c.post("/webhooks/oura", content=body,
               headers={"x-oura-signature": _sign(body), "content-type": "application/json"})
    assert r.status_code == 200

    s = Session()
    landed = s.scalar(select(HealthData).where(HealthData.provider == "oura"))
    assert landed.provider_account_id == acct_id
    assert landed.datatype == "daily_sleep"
    pending = list(s.scalars(select(ConsolidationState).where(
        ConsolidationState.provider_account_id == acct_id)))
    assert len(pending) == 2  # today + yesterday
    assert all(p.status == "pending" for p in pending)
    s.close()


def test_webhook_event_bad_signature_rejected(client):
    c, Session = client
    body = json.dumps({"user_id": "OU9"}).encode()
    r = c.post("/webhooks/oura", content=body, headers={"x-oura-signature": "sha256=deadbeef"})
    assert r.status_code == 401
    assert c.post("/webhooks/oura", content=body).status_code == 401
    s = Session()
    assert s.scalar(select(HealthData)) is None
    s.close()


def test_webhook_event_unknown_user_lands_unlinked(client):
    c, Session = client
    s = Session()
    _seed(s, user_id="OU9")  # linked account -> no single-unlinked fallback available
    s.close()

    event = {"event_type": "create", "data_type": "sleep", "object_id": "x", "user_id": "STRANGER"}
    body = json.dumps(event).encode()
    assert c.post("/webhooks/oura", content=body,
                  headers={"x-oura-signature": _sign(body)}).status_code == 200
    s = Session()
    landed = s.scalar(select(HealthData).where(HealthData.provider == "oura"))
    assert landed is not None and landed.provider_account_id is None
    assert s.scalar(select(ConsolidationState)) is None
    s.close()


def test_enroll_callback_dispatches_on_account_provider(client, monkeypatch):
    """Google and Oura both return code+state — the account found by state decides."""
    c, Session = client
    s = Session()
    oura_acct = _seed(s, user_id=None)
    oura_acct.registered = False
    oura_acct.state = "oura-state"
    fit_subj = Subject(study_id=s.get(Subject, oura_acct.subject_id).study_id)
    s.add(fit_subj)
    s.flush()
    s.add(ProviderAccount(
        subject_id=fit_subj.id, provider="fitbit_gh", state="google-state", code_verifier="cv"
    ))
    s.commit()
    oura_id = oura_acct.id
    s.close()

    import app.routers.enroll as enroll_module
    monkeypatch.setattr(enroll_module, "encrypt", lambda v: v)
    monkeypatch.setattr(
        oura, "exchange",
        lambda code: TokenResult(
            access_token="at2", refresh_token="rt2",
            expires_at=datetime.utcnow() + timedelta(hours=24),
            scope="daily personal", provider_user_id="OUX", raw={"access_token": "at2"},
        ),
    )
    monkeypatch.setattr(
        enroll_module.fitbit_gh, "exchange",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Google exchange must not run")),
    )

    r = c.get("/enroll/callback", params={"code": "authcode", "state": "oura-state"})
    assert r.status_code == 200
    assert "Oura Ring" in r.text

    s = Session()
    acct = s.get(ProviderAccount, oura_id)
    assert acct.registered is True
    assert acct.access_token == "at2" and acct.refresh_token == "rt2"
    assert acct.provider_user_id == "OUX"
    assert acct.state is None
    assert s.get(Subject, acct.subject_id).status == "registered"
    s.close()


def test_enroll_start_redirects_to_oura(client):
    c, Session = client
    s = Session()
    acct = _seed(s)
    acct.registered = False
    acct.entry_code = "OURA22"
    s.commit()
    s.close()

    r = c.post("/enroll/start", data={"entry_code": "oura22"}, follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("https://cloud.ouraring.com/oauth/authorize")
    assert "client_id=cid" in loc and "state=" in loc

    s = Session()
    acct = s.scalar(select(ProviderAccount).where(ProviderAccount.entry_code == "OURA22"))
    assert acct.state and acct.code_verifier is None
    s.close()


def test_admin_accepts_oura_studies(client):
    c, _ = client
    r = c.post("/admin/studies", json={"name": "ring study", "provider": "oura"})
    assert r.status_code == 201
    assert r.json()["provider"] == "oura"


def test_admin_oura_webhooks_idempotent_create(client, monkeypatch):
    c, _ = client
    existing = [{"id": "sub1", "data_type": "daily_activity", "event_type": "create",
                 "callback_url": "cb", "expiration_time": "2026-10-01T00:00:00+00:00"}]
    created = []

    monkeypatch.setattr(oura, "list_webhook_subscriptions", lambda: list(existing))

    def _create(data_type, event_type):
        created.append((data_type, event_type))
        return {"id": f"new-{len(created)}", "data_type": data_type, "event_type": event_type,
                "expiration_time": "2026-10-01T00:00:00+00:00"}

    monkeypatch.setattr(oura, "create_webhook_subscription", _create)

    r = c.post("/admin/oura/webhooks")
    assert r.status_code == 201
    statuses = {(x["data_type"], x["event_type"]): x["status"] for x in r.json()["subscriptions"]}
    # 2 data types x 2 event types configured; one pair already exists.
    assert statuses[("daily_activity", "create")] == "exists"
    assert statuses[("daily_activity", "update")] == "created"
    assert statuses[("sleep", "create")] == "created"
    assert statuses[("sleep", "update")] == "created"
    assert ("daily_activity", "create") not in created

    assert c.get("/admin/oura/webhooks").json() == existing


# --- provider module unit bits ----------------------------------------------------

def test_verify_signature(monkeypatch):
    monkeypatch.setattr(
        "app.providers.oura.get_settings",
        lambda: SimpleNamespace(oura_client_secret="csecret"),
    )
    body = b'{"x":1}'
    good = hmac.new(b"csecret", body, hashlib.sha256).hexdigest()
    assert oura.verify_signature(body, good)
    assert oura.verify_signature(body, f"sha256={good}")
    assert not oura.verify_signature(body, "nope")
    assert not oura.verify_signature(body, None)
