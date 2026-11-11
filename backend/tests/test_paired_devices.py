"""Paired-device refresh replaces the stored set with Google's current pairing.

`refresh_paired_devices` used to upsert whatever GET /users/me/pairedDevices returned and
leave leftover rows for previously paired trackers. The console DevicesPanel then listed
every historical snapshot. These tests pin the prune/replace behaviour.

Google HTTP is monkeypatched — no network. Run from `backend/`:

    pytest tests/test_paired_devices.py
"""

from datetime import datetime

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.consolidation import refresh_paired_devices
from app.db import Base
from app.models import PairedDevice, ProviderAccount, Study, Subject


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


def _seed_account(db, *, label="alice"):
    study = Study(name="S", provider="fitbit_gh")
    db.add(study)
    db.flush()
    subj = Subject(study_id=study.id, status="registered", subject_label=label)
    db.add(subj)
    db.flush()
    acct = ProviderAccount(subject_id=subj.id, provider="fitbit_gh", registered=True)
    db.add(acct)
    db.commit()
    return acct


def _add_device(db, account_id, name, *, version="Charge 6", dtype="TRACKER", battery=50):
    row = PairedDevice(
        provider_account_id=account_id,
        device_name=name,
        device_type=dtype,
        device_version=version,
        battery_level=battery,
        battery_status="Medium",
        last_sync_time=datetime(2026, 8, 13, 8, 16, 54),
    )
    db.add(row)
    db.flush()
    return row


def _names(db, account_id):
    return {
        r.device_name
        for r in db.scalars(select(PairedDevice).where(PairedDevice.provider_account_id == account_id))
    }


def _row(db, account_id, name):
    return db.scalar(
        select(PairedDevice).where(
            PairedDevice.provider_account_id == account_id,
            PairedDevice.device_name == name,
        )
    )


CURRENT = {
    "name": "users/me/pairedDevices/current-charge",
    "deviceType": "TRACKER",
    "deviceVersion": "Charge 6",
    "batteryLevel": 78,
    "batteryStatus": "High",
    "lastSyncTime": "2026-11-11T06:37:00Z",
}
SCALE = {
    "name": "users/me/pairedDevices/current-scale",
    "deviceType": "SCALE",
    "deviceVersion": "Aria Air",
    "batteryLevel": 90,
    "batteryStatus": "High",
    "lastSyncTime": "2026-11-10T12:00:00Z",
}


def test_refresh_prunes_devices_google_no_longer_reports(db, monkeypatch):
    """su-1 style leftover: Sense 2 + old Charge 6 snapshots drop; current Charge 6 stays."""
    acct = _seed_account(db)
    _add_device(db, acct.id, "users/me/pairedDevices/old-sense", version="Sense 2")
    _add_device(db, acct.id, "users/me/pairedDevices/old-charge", version="Charge 6")
    _add_device(db, acct.id, CURRENT["name"], version="Charge 6", battery=54)
    db.commit()

    monkeypatch.setattr(
        "app.consolidation.fitbit_gh.list_paired_devices", lambda token: [CURRENT]
    )
    n = refresh_paired_devices(db, acct, token="tok")
    db.commit()

    assert n == 1
    assert _names(db, acct.id) == {CURRENT["name"]}
    kept = _row(db, acct.id, CURRENT["name"])
    assert kept.device_version == "Charge 6"
    assert kept.battery_level == 78
    assert kept.battery_status == "High"
    assert kept.last_sync_time == datetime(2026, 11, 11, 6, 37, 0)


def test_refresh_keeps_currently_paired_tracker_and_scale(db, monkeypatch):
    acct = _seed_account(db)
    _add_device(db, acct.id, CURRENT["name"], dtype="TRACKER")
    _add_device(db, acct.id, SCALE["name"], version="Aria Air", dtype="SCALE")
    _add_device(db, acct.id, "users/me/pairedDevices/old-sense", version="Sense 2")
    db.commit()

    monkeypatch.setattr(
        "app.consolidation.fitbit_gh.list_paired_devices",
        lambda token: [CURRENT, SCALE],
    )
    refresh_paired_devices(db, acct, token="tok")
    db.commit()

    assert _names(db, acct.id) == {CURRENT["name"], SCALE["name"]}
    assert _row(db, acct.id, SCALE["name"]).device_type == "SCALE"


def test_refresh_inserts_newly_reported_device(db, monkeypatch):
    acct = _seed_account(db)
    db.commit()
    monkeypatch.setattr(
        "app.consolidation.fitbit_gh.list_paired_devices", lambda token: [CURRENT]
    )
    refresh_paired_devices(db, acct, token="tok")
    db.commit()
    assert _names(db, acct.id) == {CURRENT["name"]}


def test_empty_google_list_clears_all_stored_devices(db, monkeypatch):
    acct = _seed_account(db)
    _add_device(db, acct.id, "users/me/pairedDevices/old-sense", version="Sense 2")
    _add_device(db, acct.id, CURRENT["name"])
    db.commit()

    monkeypatch.setattr(
        "app.consolidation.fitbit_gh.list_paired_devices", lambda token: []
    )
    n = refresh_paired_devices(db, acct, token="tok")
    db.commit()

    assert n == 0
    assert _names(db, acct.id) == set()


def test_refresh_does_not_prune_another_account(db, monkeypatch):
    acct = _seed_account(db, label="alice")
    other = _seed_account(db, label="bob")
    _add_device(db, acct.id, "users/me/pairedDevices/old-sense", version="Sense 2")
    _add_device(db, acct.id, CURRENT["name"])
    _add_device(db, other.id, "users/me/pairedDevices/keep-me", version="Charge 5")
    db.commit()

    monkeypatch.setattr(
        "app.consolidation.fitbit_gh.list_paired_devices", lambda token: [CURRENT]
    )
    refresh_paired_devices(db, acct, token="tok")
    db.commit()

    assert _names(db, acct.id) == {CURRENT["name"]}
    assert _names(db, other.id) == {"users/me/pairedDevices/keep-me"}


def test_failed_google_list_does_not_prune(db, monkeypatch):
    acct = _seed_account(db)
    _add_device(db, acct.id, "users/me/pairedDevices/old-sense", version="Sense 2")
    _add_device(db, acct.id, CURRENT["name"])
    db.commit()

    req = httpx.Request("GET", "https://health.googleapis.com/v4/users/me/pairedDevices")
    resp = httpx.Response(503, request=req)

    def boom(_token):
        raise httpx.HTTPStatusError("unavailable", request=req, response=resp)

    monkeypatch.setattr("app.consolidation.fitbit_gh.list_paired_devices", boom)
    with pytest.raises(httpx.HTTPStatusError):
        refresh_paired_devices(db, acct, token="tok")
    db.rollback()

    assert _names(db, acct.id) == {
        "users/me/pairedDevices/old-sense",
        CURRENT["name"],
    }
