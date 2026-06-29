"""Unit tests for Garmin backfill orchestration (window chunking + per-type request fan-out).

No network: `garmin.request_backfill` is monkeypatched to capture calls. Run from `backend/`:

    pytest tests/test_garmin_backfill.py
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app import garmin_backfill
from app.models import ProviderAccount
from app.providers import garmin


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


# --- window chunking ------------------------------------------------------------

def test_windows_single_when_within_cap():
    wins = list(garmin_backfill._windows(date(2026, 1, 1), date(2026, 1, 10), 90))
    assert wins == [(date(2026, 1, 1), date(2026, 1, 10))]


def test_windows_chunk_long_range():
    start, end = date(2026, 1, 1), date(2026, 12, 31)
    wins = list(garmin_backfill._windows(start, end, 90))
    # contiguous, in order, and fully covering [start, end]
    assert wins[0][0] == start
    assert wins[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(wins, wins[1:]):
        assert next_start == prev_end + timedelta(days=1)
    # every window spans at most 90 days (epoch end is exclusive: end+1 day)
    for cstart, cend in wins:
        span_days = (_epoch(cend + timedelta(days=1)) - _epoch(cstart)) / 86400
        assert span_days <= 90


def test_windows_exact_boundary():
    # 90 inclusive days -> one window; the 91st day spills to a second.
    start = date(2026, 1, 1)
    assert len(list(garmin_backfill._windows(start, start + timedelta(days=89), 90))) == 1
    assert len(list(garmin_backfill._windows(start, start + timedelta(days=90), 90))) == 2


# --- orchestration --------------------------------------------------------------

@pytest.fixture()
def acct():
    return ProviderAccount(
        id=7, subject_id=1, provider="garmin", registered=True,
        access_token="uat", refresh_token="secret",
    )


def _patch(monkeypatch, fn):
    monkeypatch.setattr(garmin_backfill, "decrypt", lambda x: x)
    monkeypatch.setattr(garmin_backfill.time, "sleep", lambda *_: None)  # no real spacing in tests
    calls = []

    def fake(uat, secret, summary_type, start_epoch, end_epoch):
        calls.append((uat, secret, summary_type, start_epoch, end_epoch))
        return fn(summary_type)

    monkeypatch.setattr(garmin_backfill.garmin, "request_backfill", fake)
    return calls


def test_backfill_fans_out_types_and_windows(monkeypatch, acct):
    calls = _patch(monkeypatch, lambda t: 202)
    start, end = date(2026, 1, 1), date(2026, 4, 10)  # 100 days -> 2 windows of <=90
    results = garmin_backfill.backfill_account(
        None, acct, start, end, types=["dailies", "sleeps"]
    )
    assert len(calls) == 4  # 2 types x 2 windows
    assert len(results) == 4
    assert all(r["status"] == 202 for r in results)
    # token threaded through; first call covers the first window with exclusive end bound
    uat, secret, stype, s_epoch, e_epoch = calls[0]
    assert (uat, secret, stype) == ("uat", "secret", "dailies")
    assert s_epoch == _epoch(date(2026, 1, 1))
    assert e_epoch == _epoch(date(2026, 4, 1))  # first window end (3/31) + 1 day, exclusive


def test_backfill_records_error_and_continues(monkeypatch, acct):
    def fn(summary_type):
        if summary_type == "sleeps":
            raise RuntimeError("boom")
        return 202

    _patch(monkeypatch, fn)
    results = garmin_backfill.backfill_account(
        None, acct, date(2026, 1, 1), date(2026, 1, 5), types=["dailies", "sleeps", "hrv"]
    )
    by_type = {r["type"]: r for r in results}
    assert by_type["dailies"]["status"] == 202
    assert by_type["hrv"]["status"] == 202
    assert "error" in by_type["sleeps"] and "boom" in by_type["sleeps"]["error"]


def test_backfill_requires_tokens(monkeypatch, acct):
    monkeypatch.setattr(garmin_backfill, "decrypt", lambda x: None)
    with pytest.raises(ValueError):
        garmin_backfill.backfill_account(None, acct, date(2026, 1, 1), date(2026, 1, 2), types=["dailies"])


def test_backfill_spaces_requests(monkeypatch, acct):
    # 3 types x 1 window = 3 requests -> 2 inter-request sleeps (none before the first).
    sleeps = []
    monkeypatch.setattr(garmin_backfill, "decrypt", lambda x: x)
    monkeypatch.setattr(garmin_backfill.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(garmin_backfill.garmin, "request_backfill", lambda *a: 202)
    garmin_backfill.backfill_account(
        None, acct, date(2026, 1, 1), date(2026, 1, 5), types=["dailies", "sleeps", "hrv"]
    )
    assert len(sleeps) == 2
    assert all(s > 0 for s in sleeps)


def test_window_count():
    assert garmin_backfill.window_count(date(2026, 1, 1), date(2026, 1, 10)) == 1
    assert garmin_backfill.window_count(date(2026, 1, 1), date(2026, 4, 10)) == 2  # 100 days


def test_run_backfill_opens_and_closes_own_session(monkeypatch, acct):
    captured = {}

    class FakeSession:
        def get(self, model, pk):
            captured["pk"] = pk
            return acct

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(garmin_backfill, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        garmin_backfill, "backfill_account",
        lambda db, account, start, end: [{"status": 202}],
    )
    garmin_backfill.run_backfill(7, date(2026, 1, 1), date(2026, 1, 2))
    assert captured["pk"] == 7
    assert captured.get("closed") is True


# --- request_backfill 429 retry (provider layer) --------------------------------

class _Resp:
    def __init__(self, code, headers=None):
        self.status_code = code
        self.headers = headers or {}

    def raise_for_status(self):
        raise RuntimeError(f"HTTP {self.status_code}")


def _fake_session(codes):
    it = iter(codes)

    class S:
        def get(self, url, params=None, timeout=None):
            return _Resp(next(it))

    return S()


def test_request_backfill_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(garmin.time, "sleep", lambda *_: None)
    monkeypatch.setattr(garmin, "_user_session", lambda u, s: _fake_session([429, 429, 202]))
    assert garmin.request_backfill("uat", "sec", "hrv", 1, 2) == 202


def test_request_backfill_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(garmin.time, "sleep", lambda *_: None)
    monkeypatch.setattr(garmin, "_user_session", lambda u, s: _fake_session([429] * 20))
    with pytest.raises(RuntimeError):
        garmin.request_backfill("uat", "sec", "hrv", 1, 2)


def test_retry_after_header_is_honored(monkeypatch):
    waits = []
    monkeypatch.setattr(garmin.time, "sleep", lambda s: waits.append(s))
    monkeypatch.setattr(
        garmin, "_user_session",
        lambda u, s: type("S", (), {"get": lambda self, url, params=None, timeout=None:
                                    _Resp(429, {"Retry-After": "12"})
                                    if not waits else _Resp(202)})(),
    )
    assert garmin.request_backfill("uat", "sec", "hrv", 1, 2) == 202
    assert waits == [12.0]
