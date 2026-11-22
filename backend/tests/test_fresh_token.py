"""Google Health `_fresh_token` persist: skip-if-fresh, short commit, lock-wait retry.

Uses a file-backed SQLite engine so the token persist session is a *different
connection* from the caller (MariaDB queue pool behaves the same way). In-memory
StaticPool would share one connection and a caller rollback would undo the persist.

No network. Run from `backend/`:

    pytest tests/test_fresh_token.py
"""

import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pymysql
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import consolidation
from app.db import Base
from app.models import DailyHealth, ProviderAccount, Study, Subject
from app.providers.base import TokenResult

D = date(2026, 3, 1)


def _lock_wait(token_param="SECRET-TOKEN-VALUE"):
    orig = pymysql.err.OperationalError(
        1205, "Lock wait timeout exceeded; try restarting transaction"
    )
    return OperationalError(
        "UPDATE provider_accounts SET access_token=%(access_token)s WHERE id=%(id)s",
        {"access_token": token_param, "id": 1},
        orig,
    )


@pytest.fixture()
def file_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tokens.db'}",
        connect_args={"check_same_thread": False, "timeout": 0.3},
    )
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Factory()
    study = Study(name="Demo study", provider="fitbit_gh")
    db.add(study)
    db.flush()
    subj = Subject(study_id=study.id, status="registered")
    db.add(subj)
    db.flush()
    acct = ProviderAccount(
        subject_id=subj.id,
        provider="fitbit_gh",
        registered=True,
        access_token="old-at",
        refresh_token="old-rt",
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    try:
        yield db, Factory, acct.id
    finally:
        db.close()
        engine.dispose()


def _account(db, account_id):
    return db.get(ProviderAccount, account_id)


def _patch_crypto_and_refresh(monkeypatch, *, new_at="new-at", new_rt="new-rt"):
    monkeypatch.setattr(consolidation, "encrypt", lambda v: v)
    monkeypatch.setattr(consolidation, "decrypt", lambda v: v)
    monkeypatch.setattr(
        consolidation.gh_creds, "resolve_for_account", lambda db, acct: SimpleNamespace(source="test")
    )
    monkeypatch.setattr(
        consolidation.fitbit_gh,
        "refresh",
        lambda creds, rt: TokenResult(
            access_token=new_at,
            refresh_token=new_rt,
            expires_at=datetime.utcnow() + timedelta(hours=24),
            scope="s",
            provider_user_id=None,
            raw={},
        ),
    )


def test_fresh_token_skips_refresh_when_valid(file_db, monkeypatch):
    db, _Factory, account_id = file_db
    acct = _account(db, account_id)
    monkeypatch.setattr(consolidation, "decrypt", lambda v: v)
    monkeypatch.setattr(
        consolidation.fitbit_gh,
        "refresh",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no refresh expected")),
    )
    monkeypatch.setattr(
        consolidation,
        "_persist_refreshed_tokens",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no persist expected")),
    )
    assert consolidation._fresh_token(db, acct) == "old-at"


def test_fresh_token_commits_on_own_session_and_survives_caller_rollback(file_db, monkeypatch):
    db, Factory, account_id = file_db
    acct = _account(db, account_id)
    acct.token_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    _patch_crypto_and_refresh(monkeypatch)

    # Uncommitted caller work must not ride the token persist. Do not flush: a flushed
    # child row would hold SQLite's write lock (and in InnoDB a FK share on the parent),
    # which is not how consolidate_day calls _fresh_token (tokens first, then points).
    db.add(
        DailyHealth(
            provider_account_id=account_id,
            subject_id=acct.subject_id,
            local_date=D,
            steps=99,
        )
    )

    token = consolidation._fresh_token(db, acct)
    assert token == "new-at"

    db.rollback()  # drop the uncommitted daily row; tokens must stay
    other = Factory()
    try:
        saved = other.get(ProviderAccount, account_id)
        assert saved.access_token == "new-at"
        assert saved.refresh_token == "new-rt"
        assert other.scalar(select(DailyHealth)) is None
    finally:
        other.close()


def test_persist_retries_lock_wait_then_succeeds(file_db, monkeypatch):
    db, Factory, account_id = file_db
    attempts = {"n": 0}
    orig_commit = Session.commit

    def flaky(self):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _lock_wait()
        return orig_commit(self)

    monkeypatch.setattr(Session, "commit", flaky)
    monkeypatch.setattr(consolidation.time, "sleep", lambda *_: None)

    consolidation._persist_refreshed_tokens(
        db, account_id, "persisted-at", "persisted-rt", datetime.utcnow()
    )
    assert attempts["n"] == 2
    other = Factory()
    try:
        saved = other.get(ProviderAccount, account_id)
        assert saved.access_token == "persisted-at"
        assert saved.refresh_token == "persisted-rt"
    finally:
        other.close()


def test_persist_lock_wait_log_omits_sql_params(file_db, monkeypatch, caplog):
    db, _Factory, account_id = file_db

    def always_fail(self):
        raise _lock_wait("SECRET-TOKEN-VALUE")

    monkeypatch.setattr(Session, "commit", always_fail)
    monkeypatch.setattr(consolidation.time, "sleep", lambda *_: None)

    with pytest.raises(OperationalError):
        consolidation._persist_refreshed_tokens(
            db, account_id, "x", "y", datetime.utcnow()
        )
    logged = caplog.text
    assert "SECRET-TOKEN-VALUE" not in logged
    assert "access_token=" not in logged
    assert "errno=1205" in logged


def test_persist_waits_out_concurrent_writer(file_db, monkeypatch):
    """A second session holding an uncommitted UPDATE of the same row: persist retries
    until that writer rolls back. SQLite serializes writers; MariaDB would 1205 the same
    exclusive lock. Not a claim about which production session held the lock."""
    db, Factory, account_id = file_db
    held = threading.Event()
    release = threading.Event()
    errors = []

    def holder():
        s = Factory()
        try:
            row = s.get(ProviderAccount, account_id)
            row.access_token = "held-by-other-session"
            s.flush()
            held.set()
            release.wait(timeout=5)
            s.rollback()
        except Exception as exc:  # noqa: BLE001 — collect for the main thread
            errors.append(exc)
        finally:
            s.close()

    monkeypatch.setattr(
        consolidation.time, "sleep", lambda *_: release.set()
    )
    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(timeout=5)
    try:
        consolidation._persist_refreshed_tokens(
            db, account_id, "after-wait-at", "after-wait-rt", datetime.utcnow()
        )
    finally:
        release.set()
        t.join(timeout=5)

    assert errors == []
    other = Factory()
    try:
        saved = other.get(ProviderAccount, account_id)
        assert saved.access_token == "after-wait-at"
        assert saved.refresh_token == "after-wait-rt"
        assert saved.access_token != "held-by-other-session"
    finally:
        other.close()
