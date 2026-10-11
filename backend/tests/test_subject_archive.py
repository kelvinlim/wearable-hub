"""Subject archive (soft-delete) + gated hard-delete.

Archive is reversible and study-admin scoped. Permanent delete is superuser-only
and only allowed for an already-archived, unlinked subject (still with the
PR #32 confirmation body).

Run from `backend/`: pytest tests/test_subject_archive.py tests/test_subject_delete.py
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import DailyHealth, ProviderAccount, Study, StudyMembership, Subject, User
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


def _archive(client, subject_id):
    r = client.post(f"/admin/subjects/{subject_id}/archive")
    assert r.status_code == 200, r.text
    return r.json()


def test_archive_unarchive_round_trip(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    assert subj["archived"] is False
    assert subj["archived_at"] is None

    archived = _archive(admin, subj["id"])
    assert archived["archived"] is True
    assert archived["archived_at"] is not None
    assert archived["archived_by"] == ids["admin"]
    assert archived["status"] == subj["status"]
    assert archived["participant_id"] == "P-001"

    db = Session()
    row = db.get(Subject, subj["id"])
    assert row.archived_at is not None
    assert row.archived_by == ids["admin"]
    db.close()

    restored = admin.post(f"/admin/subjects/{subj['id']}/unarchive")
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["archived"] is False
    assert body["archived_at"] is None
    assert body["archived_by"] is None
    assert body["participant_id"] == "P-001"
    assert body["status"] == subj["status"]


def test_list_hides_archived_by_default(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    active = _add_subject(admin, ids["study"], "P-ACTIVE")
    hidden = _add_subject(admin, ids["study"], "P-DONE")
    _archive(admin, hidden["id"])

    default = admin.get(f"/admin/studies/{ids['study']}/subjects")
    assert default.status_code == 200, default.text
    ids_default = {s["id"] for s in default.json()}
    assert active["id"] in ids_default
    assert hidden["id"] not in ids_default

    shown = admin.get(f"/admin/studies/{ids['study']}/subjects?include_archived=true")
    assert shown.status_code == 200, shown.text
    by_id = {s["id"]: s for s in shown.json()}
    assert active["id"] in by_id
    assert hidden["id"] in by_id
    assert by_id[hidden["id"]]["archived"] is True
    assert by_id[active["id"]]["archived"] is False


def test_member_can_list_archived_with_flag(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    hidden = _add_subject(admin, ids["study"], "P-DONE")
    _archive(admin, hidden["id"])
    member = as_user(ids["member"])
    shown = member.get(f"/admin/studies/{ids['study']}/subjects?include_archived=true")
    assert shown.status_code == 200, shown.text
    assert any(s["id"] == hidden["id"] and s["archived"] for s in shown.json())


def test_archive_refused_while_linked(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    db = Session()
    acct = db.scalar(select(ProviderAccount).where(ProviderAccount.subject_id == subj["id"]))
    acct.registered = True
    db.commit()
    db.close()
    r = admin.post(f"/admin/subjects/{subj['id']}/archive")
    assert r.status_code == 409, r.text
    assert "linked" in r.json()["detail"]
    db = Session()
    assert db.get(Subject, subj["id"]).archived_at is None
    db.close()


def test_member_cannot_archive_or_unarchive(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    member = as_user(ids["member"])
    assert member.post(f"/admin/subjects/{subj['id']}/archive").status_code == 403
    admin = as_user(ids["admin"])
    _archive(admin, subj["id"])
    member = as_user(ids["member"])
    assert member.post(f"/admin/subjects/{subj['id']}/unarchive").status_code == 403


def test_delete_refused_when_not_archived(ctx):
    as_user, ids, Session = ctx
    su = as_user(ids["su"])
    subj = _add_subject(su, ids["study"], "P-001")
    r = su.request("DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-001"))
    assert r.status_code == 409, r.text
    assert "Archive" in r.json()["detail"]
    db = Session()
    assert db.get(Subject, subj["id"]) is not None
    db.close()


def test_delete_allowed_for_archived_with_confirmation(ctx):
    as_user, ids, Session = ctx
    su = as_user(ids["su"])
    subj = _add_subject(su, ids["study"], "P-001")
    _archive(su, subj["id"])
    r = su.request("DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-001"))
    assert r.status_code == 204, r.text
    db = Session()
    assert db.get(Subject, subj["id"]) is None
    db.close()


def test_study_admin_cannot_delete_even_when_archived(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"], "P-001")
    _archive(admin, subj["id"])
    r = admin.request("DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-001"))
    assert r.status_code == 403, r.text
    assert "Superuser" in r.json()["detail"]
    db = Session()
    assert db.get(Subject, subj["id"]) is not None
    db.close()


def test_member_cannot_delete_archived(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"], "P-001")
    _archive(admin, subj["id"])
    member = as_user(ids["member"])
    r = member.request("DELETE", f"/admin/subjects/{subj['id']}", json=_confirm("P-001"))
    assert r.status_code == 403, r.text


def test_archived_subject_still_exportable(ctx):
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
    db.commit()
    db.close()
    _archive(admin, subj["id"])
    r = admin.get(f"/admin/subjects/{subj['id']}/export")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject"]["archived"] is True
    assert body["days"][0]["steps"] == 100


def test_archived_subject_refuses_consolidate(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    _archive(admin, subj["id"])
    r = admin.post(f"/admin/subjects/{subj['id']}/consolidate?start=2026-06-01&end=2026-06-02")
    assert r.status_code == 409, r.text
    assert "archived" in r.json()["detail"]


def test_archive_is_idempotent(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    subj = _add_subject(admin, ids["study"])
    first = _archive(admin, subj["id"])
    second = _archive(admin, subj["id"])
    assert first["archived_at"] == second["archived_at"]
    assert second["archived"] is True
