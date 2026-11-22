"""On-demand pull/consolidation error mapping — safe API bodies + log correlation.

No network. Run from `backend/`:

    pytest tests/test_pull_errors.py
"""

import asyncio
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pymysql
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import consolidation, pull_errors
from app.db import Base, get_db
from app.main import app, unhandled_exception_handler
from app.models import ConsolidationState, Study, StudyMembership, User
from app.security import get_current_user, require_superuser


# --- classify_exception ----------------------------------------------------------

def _http_status(url: str, code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", url)
    resp = httpx.Response(code, request=req, text="upstream-secret-body")
    return httpx.HTTPStatusError("boom", request=req, response=resp)


def test_classify_timeout_and_connect():
    reason, status, msg = pull_errors.classify_exception(httpx.TimeoutException("x"))
    assert reason == pull_errors.REASON_PROVIDER_TIMEOUT
    assert status == 504
    assert "time" in msg.lower()

    reason, status, _ = pull_errors.classify_exception(httpx.ConnectError("x"))
    assert reason == pull_errors.REASON_PROVIDER_UNREACHABLE
    assert status == 502


def test_classify_token_refresh_vs_data_http():
    reason, status, msg = pull_errors.classify_exception(
        _http_status("https://oauth2.googleapis.com/token", 500)
    )
    assert reason == pull_errors.REASON_TOKEN_REFRESH
    assert status == 502
    assert "500" in msg
    assert "upstream-secret-body" not in msg

    reason, status, msg = pull_errors.classify_exception(
        _http_status("https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints", 503)
    )
    assert reason == pull_errors.REASON_PROVIDER_HTTP
    assert status == 502
    assert "503" in msg


def test_classify_lock_wait_omits_sql_params():
    orig = pymysql.err.OperationalError(
        1205, "Lock wait timeout exceeded; try restarting transaction"
    )
    exc = OperationalError(
        "UPDATE provider_accounts SET access_token=%(access_token)s",
        {"access_token": "SECRET-TOKEN-VALUE"},
        orig,
    )
    reason, status, msg = pull_errors.classify_exception(exc)
    assert reason == pull_errors.REASON_DB_LOCK
    assert status == 503
    assert "SECRET-TOKEN-VALUE" not in msg
    assert "access_token" not in msg
    assert "1205" not in msg  # errno stays in logs, not the researcher message
    summary = pull_errors.safe_exc_summary(exc)
    assert "errno=1205" in summary
    assert "SECRET-TOKEN-VALUE" not in summary


def test_classify_integrity_and_unexpected_omit_exc_text():
    reason, status, msg = pull_errors.classify_exception(
        IntegrityError("INSERT INTO health_data_points", {}, Exception("ya29.secret"))
    )
    assert reason == pull_errors.REASON_DATABASE
    assert status == 500
    assert "ya29" not in msg

    reason, status, msg = pull_errors.classify_exception(
        RuntimeError("Bearer ya29.secret TRACEBACK access_token=xyz")
    )
    assert reason == pull_errors.REASON_UNEXPECTED
    assert status == 500
    assert "ya29" not in msg
    assert "TRACEBACK" not in msg
    assert "Bearer" not in msg


def test_build_pull_failure_names_failed_date_and_partial_save():
    failure = pull_errors.build_pull_failure(
        httpx.TimeoutException("ignored"),
        failed_date=date(2026, 10, 24),
        range_start=date(2026, 10, 24),
        range_end=date(2026, 11, 2),
        completed_dates=["2026-10-24"],
        error_id="deadbeef",
    )
    detail = failure.as_detail()
    assert detail["error_id"] == "deadbeef"
    assert detail["failed_date"] == "2026-10-24"
    assert detail["range_start"] == "2026-10-24"
    assert detail["range_end"] == "2026-11-02"
    assert detail["completed_dates"] == ["2026-10-24"]
    assert "2026-10-24" in detail["message"]
    assert "1 earlier day" in detail["message"]
    assert "ignored" not in json.dumps(detail)
    assert set(detail) <= {
        "message", "reason", "guidance", "error_id",
        "failed_date", "range_start", "range_end", "completed_dates",
    }


# --- run_on_demand_range ---------------------------------------------------------

class _Acct:
    def __init__(self):
        self.id = 7
        self.provider = "fitbit_gh"


def test_run_on_demand_range_success_returns_per_day_status():
    def ok(db, acct, d):
        return SimpleNamespace(status="done", detail=None)

    days = pull_errors.run_on_demand_range(
        db=None, account=_Acct(), start=date(2026, 10, 24), end=date(2026, 10, 25),
        consolidate_fn=ok, subject_id=101,
    )
    assert [r["date"] for r in days] == ["2026-10-24", "2026-10-25"]
    assert all(r["status"] == "done" for r in days)


def test_run_on_demand_range_continues_after_returned_error_status():
    """Grant-revoked (and similar) is a returned state, not a raised exception — keep going."""

    def mixed(db, acct, d):
        if d == date(2026, 10, 24):
            return SimpleNamespace(status="error", detail="grant revoked")
        return SimpleNamespace(status="done", detail=None)

    days = pull_errors.run_on_demand_range(
        db=None, account=_Acct(), start=date(2026, 10, 24), end=date(2026, 10, 25),
        consolidate_fn=mixed, subject_id=101,
    )
    assert days[0]["status"] == "error"
    assert days[1]["status"] == "done"


def test_run_on_demand_range_raised_error_is_http_and_does_not_leak(caplog):
    calls = []

    def boom(db, acct, d):
        calls.append(d)
        if d == date(2026, 10, 25):
            raise RuntimeError("Bearer ya29.secret TRACEBACK participant@example.test")
        return SimpleNamespace(status="done", detail=None)

    class FakeDb:
        def rollback(self):
            self.rolled = True

    with pytest.raises(HTTPException) as ei:
        pull_errors.run_on_demand_range(
            db=FakeDb(), account=_Acct(),
            start=date(2026, 10, 24), end=date(2026, 10, 26),
            consolidate_fn=boom, subject_id=101,
        )
    # Persist of ConsolidationState hits FakeDb without the ORM methods — that's
    # swallowed; the HTTPException is what the client sees.
    exc = ei.value
    detail = exc.detail
    assert exc.status_code == 500
    assert detail["failed_date"] == "2026-10-25"
    assert detail["completed_dates"] == ["2026-10-24"]
    assert detail["range_end"] == "2026-10-26"
    body = json.dumps(detail)
    assert "ya29" not in body
    assert "TRACEBACK" not in body
    assert "example.test" not in body
    assert "Bearer" not in body
    assert calls == [date(2026, 10, 24), date(2026, 10, 25)]  # stopped, no 10-26
    assert "error_id=" in caplog.text
    assert detail["error_id"] in caplog.text


def test_unhandled_exception_handler_safe_ref():
    req = SimpleNamespace(method="POST", url=SimpleNamespace(path="/admin/subjects/101/consolidate"))
    resp = asyncio.run(
        unhandled_exception_handler(req, RuntimeError("Bearer ya29.secret TRACEBACK"))
    )
    assert resp.status_code == 500
    payload = json.loads(resp.body)
    detail = payload["detail"]
    assert detail["reason"] == pull_errors.REASON_UNEXPECTED
    assert detail["error_id"]
    raw = resp.body.decode()
    assert "ya29" not in raw
    assert "TRACEBACK" not in raw
    assert "Bearer" not in raw


# --- HTTP endpoint ---------------------------------------------------------------

@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    s = Session()
    su = User(email="su@umn.edu", name="Su", is_superuser=True)
    admin = User(email="admin@umn.edu", is_superuser=False)
    member = User(email="member@umn.edu", is_superuser=False)
    s.add_all([su, admin, member])
    s.flush()
    study = Study(name="Demo study", provider="fitbit_gh")
    s.add(study)
    s.flush()
    s.add_all(
        [
            StudyMembership(user_id=admin.id, study_id=study.id, role="admin"),
            StudyMembership(user_id=member.id, study_id=study.id, role="member"),
        ]
    )
    s.commit()
    ids = {"su": su.id, "admin": admin.id, "member": member.id, "study": study.id}
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


def _add_subject(client, study_id, participant_id="P-062"):
    r = client.post(
        f"/admin/studies/{study_id}/subjects",
        json={"participant_id": participant_id, "subject_label": "alice@umn.edu"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_consolidate_success_still_returns_days(ctx, monkeypatch):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])

    def fake(db, acct, d):
        return SimpleNamespace(status="done", detail=None)

    monkeypatch.setattr(consolidation, "consolidate_day", fake)
    r = admin.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-10-24&end=2026-10-25")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject_id"] == subj["id"]
    assert [d["date"] for d in body["days"]] == ["2026-10-24", "2026-10-25"]
    assert all(d["status"] == "done" for d in body["days"])


def test_consolidate_unexpected_error_is_structured_and_safe(ctx, monkeypatch):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])

    def fake(db, acct, d):
        if d == date(2026, 10, 25):
            raise RuntimeError("Bearer ya29.secret TRACEBACK alice@umn.edu")
        return SimpleNamespace(status="done", detail=None)

    monkeypatch.setattr(consolidation, "consolidate_day", fake)
    r = admin.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-10-24&end=2026-10-26")
    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert detail["failed_date"] == "2026-10-25"
    assert detail["completed_dates"] == ["2026-10-24"]
    assert detail["range_start"] == "2026-10-24"
    assert detail["range_end"] == "2026-10-26"
    assert detail["reason"] == pull_errors.REASON_UNEXPECTED
    assert detail["error_id"]
    assert "Retry this date" in detail["guidance"]
    raw = r.text
    assert "ya29" not in raw
    assert "TRACEBACK" not in raw
    assert "alice@umn.edu" not in raw
    assert "Bearer" not in raw
    assert "Internal Server Error" not in raw

    db = Session()
    row = db.scalar(
        select(ConsolidationState).where(ConsolidationState.local_date == date(2026, 10, 25))
    )
    assert row is not None
    assert row.status == "error"
    assert detail["error_id"] in (row.detail or "")
    assert "ya29" not in (row.detail or "")
    db.close()


def test_consolidate_timeout_is_504_with_reason(ctx, monkeypatch):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])

    def fake(db, acct, d):
        raise httpx.TimeoutException("read timeout")

    monkeypatch.setattr(consolidation, "consolidate_day", fake)
    r = admin.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-10-24&end=2026-10-24")
    assert r.status_code == 504, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == pull_errors.REASON_PROVIDER_TIMEOUT
    assert detail["failed_date"] == "2026-10-24"
    assert detail["completed_dates"] == []
    assert "read timeout" not in r.text


def test_consolidate_lock_wait_is_503_and_omits_token_params(ctx, monkeypatch, caplog):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])

    def fake(db, acct, d):
        orig = pymysql.err.OperationalError(
            1205, "Lock wait timeout exceeded; try restarting transaction"
        )
        raise OperationalError(
            "UPDATE provider_accounts SET access_token=%(access_token)s",
            {"access_token": "SECRET-TOKEN-VALUE"},
            orig,
        )

    monkeypatch.setattr(consolidation, "consolidate_day", fake)
    r = admin.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-10-24&end=2026-10-24")
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == pull_errors.REASON_DB_LOCK
    assert detail["failed_date"] == "2026-10-24"
    assert "re-link" in detail["guidance"].lower() or "Retry shortly" in detail["guidance"]
    raw = r.text + caplog.text
    assert "SECRET-TOKEN-VALUE" not in raw
    assert "Internal Server Error" not in r.text


def test_consolidate_integrity_error_is_database_reason(ctx, monkeypatch):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])

    def fake(db, acct, d):
        raise IntegrityError("INSERT INTO health_data_points ... ya29", {}, Exception("dup"))

    monkeypatch.setattr(consolidation, "consolidate_day", fake)
    r = admin.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-10-24&end=2026-10-24")
    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == pull_errors.REASON_DATABASE
    assert "ya29" not in r.text
    assert "health_data_points" not in r.text


def test_consolidate_member_forbidden_and_bad_range_unchanged(ctx, monkeypatch):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    monkeypatch.setattr(
        consolidation, "consolidate_day",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not pull")),
    )

    member = as_user(ids["member"])
    r = member.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-10-24&end=2026-10-25")
    assert r.status_code == 403, r.text

    r = admin.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-11-02&end=2026-10-24")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "end must be >= start"
