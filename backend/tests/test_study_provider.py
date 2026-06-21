"""Per-study provider: chosen at creation, immutable, and inherited by subjects.

Drives the admin API through TestClient with the DB + auth dependencies overridden (in-memory
SQLite, a superuser). Run from `backend/`: pytest tests/test_study_provider.py
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import User
from app.security import get_current_user, require_superuser


@pytest.fixture()
def client():
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

    # Seed a superuser and make the auth deps return it.
    seed = TestingSession()
    su = User(email="su@umn.edu", name="Su", is_superuser=True)
    seed.add(su)
    seed.commit()
    seed.refresh(su)
    seed.close()

    def _user():
        s = TestingSession()
        try:
            yield s.get(User, su.id)
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: TestingSession().get(User, su.id)
    app.dependency_overrides[require_superuser] = lambda: TestingSession().get(User, su.id)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_study(client, provider):
    r = client.post("/admin/studies", json={"name": f"{provider} study", "provider": provider})
    assert r.status_code == 201, r.text
    return r.json()


def test_study_records_provider(client):
    assert _make_study(client, "garmin")["provider"] == "garmin"
    assert _make_study(client, "fitbit_gh")["provider"] == "fitbit_gh"


def test_unknown_provider_rejected(client):
    r = client.post("/admin/studies", json={"name": "x", "provider": "whoop"})
    assert r.status_code == 400


def test_subject_autocreates_registration_with_study_provider(client):
    study = _make_study(client, "garmin")
    r = client.post(f"/admin/studies/{study['id']}/subjects", json={"participant_id": "P1"})
    assert r.status_code == 201, r.text
    subj_id = r.json()["id"]
    # The subject list carries the registration; it must be the study's provider, with a code.
    subjects = client.get(f"/admin/studies/{study['id']}/subjects").json()
    regs = next(s for s in subjects if s["id"] == subj_id)["registrations"]
    assert len(regs) == 1
    assert regs[0]["provider"] == "garmin"
    assert regs[0]["entry_code"]


def test_cannot_register_other_provider(client):
    study = _make_study(client, "fitbit_gh")
    subj = client.post(f"/admin/studies/{study['id']}/subjects", json={}).json()
    # A subject in a Fitbit study cannot get a Garmin device.
    r = client.post(f"/admin/subjects/{subj['id']}/registrations", json={"provider": "garmin"})
    assert r.status_code == 409, r.text


def test_provider_immutable_via_patch(client):
    study = _make_study(client, "fitbit_gh")
    # PATCH ignores unknown fields (StudyUpdate has no `provider`), so it stays fitbit_gh.
    client.patch(f"/admin/studies/{study['id']}", json={"provider": "garmin"})
    studies = client.get("/admin/studies").json()
    assert next(s for s in studies if s["id"] == study["id"])["provider"] == "fitbit_gh"
