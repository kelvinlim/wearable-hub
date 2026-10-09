"""Subject hard-delete requires an explicit confirmation body.

A stray DELETE (or an old frontend that only sent the path) must not destroy health data.
Run from `backend/`: pytest tests/test_subject_delete.py
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    DailyHealth,
    HealthDataPoint,
    ProviderAccount,
    Study,
    StudyMembership,
    Subject,
    User,
)
from app.security import get_current_user, require_superuser


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
    study = Study(name="Sleep study", provider="fitbit_gh")
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


def _add_subject(client, study_id, participant_id="P-001"):
    r = client.post(
        f"/admin/studies/{study_id}/subjects",
        json={"participant_id": participant_id, "subject_label": "alice@umn.edu"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _confirm(participant_id, **extra):
    body = {"confirm": True, "confirm_participant_id": participant_id, "confirm_exported": True}
    body.update(extra)
    return body


def test_delete_refused_without_confirmation(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    r = admin.delete(f"/admin/subjects/{subj['id']}")
    assert r.status_code == 400, r.text
    assert "Confirmation required" in r.json()["detail"]
    db = Session()
    assert db.get(Subject, subj["id"]) is not None
    db.close()


def test_delete_refused_with_mismatched_id(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"], "P-001")
    r = admin.request(
        "DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-999")
    )
    assert r.status_code == 400, r.text
    assert "does not match" in r.json()["detail"]
    db = Session()
    assert db.get(Subject, subj["id"]) is not None
    db.close()


def test_delete_allowed_with_correct_confirmation(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"], "P-001")
    r = admin.request(
        "DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-001")
    )
    assert r.status_code == 204, r.text
    db = Session()
    assert db.get(Subject, subj["id"]) is None
    db.close()


def test_delete_allowed_with_su_fallback_id(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"], "P-001")
    r = admin.request(
        "DELETE",
        f"/admin/subjects/{subj['id']}",
        json=_confirm(f"su-{subj['id']}"),
    )
    assert r.status_code == 204, r.text
    db = Session()
    assert db.get(Subject, subj["id"]) is None
    db.close()


def test_delete_refused_when_confirm_false(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    r = admin.request(
        "DELETE",
        f"/admin/subjects/{subj['id']}",
        json=_confirm("P-001", confirm=False),
    )
    assert r.status_code == 400, r.text
    db = Session()
    assert db.get(Subject, subj["id"]) is not None
    db.close()


def test_delete_refused_when_export_not_acked(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    r = admin.request(
        "DELETE",
        f"/admin/subjects/{subj['id']}",
        json=_confirm("P-001", confirm_exported=False),
    )
    assert r.status_code == 400, r.text
    db = Session()
    assert db.get(Subject, subj["id"]) is not None
    db.close()


def test_delete_refused_while_linked(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    db = Session()
    acct = db.scalar(select(ProviderAccount).where(ProviderAccount.subject_id == subj["id"]))
    acct.registered = True
    db.commit()
    db.close()
    r = admin.request(
        "DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-001")
    )
    assert r.status_code == 409, r.text
    db = Session()
    assert db.get(Subject, subj["id"]) is not None
    db.close()


def test_member_cannot_delete_even_with_confirmation(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    member = as_user(ids["member"])
    r = member.request(
        "DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-001")
    )
    assert r.status_code == 403, r.text


def test_deletion_preview_counts(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"], "P-001")
    db = Session()
    acct = db.scalar(select(ProviderAccount).where(ProviderAccount.subject_id == subj["id"]))
    db.add(
        DailyHealth(
            provider_account_id=acct.id,
            subject_id=subj["id"],
            local_date=date(2026, 6, 1),
            steps=100,
        )
    )
    db.add(
        DailyHealth(
            provider_account_id=acct.id,
            subject_id=subj["id"],
            local_date=date(2026, 6, 3),
            steps=200,
        )
    )
    db.add(
        HealthDataPoint(
            provider_account_id=acct.id,
            datatype="heart_rate",
            local_date=date(2026, 6, 1),
            point_key="k1",
            value=70,
        )
    )
    db.commit()
    db.close()

    r = admin.get(f"/admin/subjects/{subj['id']}/deletion-preview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["participant_id"] == "P-001"
    assert body["study_name"] == "Sleep study"
    assert body["fallback_id"] == f"su-{subj['id']}"
    assert body["linked"] is False
    assert body["daily_row_count"] == 2
    assert body["point_count"] == 1
    assert body["first_date"] == "2026-06-01"
    assert body["last_date"] == "2026-06-03"


def test_member_cannot_see_deletion_preview(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    member = as_user(ids["member"])
    assert member.get(f"/admin/subjects/{subj['id']}/deletion-preview").status_code == 403
