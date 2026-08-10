"""Superusers edit research staff (`PATCH /admin/users/{id}`).

TestClient against in-memory SQLite. Covers the first/last-name edit, email normalization +
google_sub unlinking, the duplicate-email conflict, and the self-demotion guard.
Run from `backend/`: pytest tests/test_users.py
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
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    s = Session()
    su = User(email="su@umn.edu", is_superuser=True)
    staff = User(email="staff@umn.edu", name="Old Name", google_sub="google-123")
    taken = User(email="taken@umn.edu")
    s.add_all([su, staff, taken])
    s.commit()
    ids = {"su": su.id, "staff": staff.id, "taken": taken.id}
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


def test_edit_names_and_promote(ctx):
    as_user, ids, Session = ctx
    su = as_user(ids["su"])
    r = su.patch(
        f"/admin/users/{ids['staff']}",
        json={"first_name": "Ada", "last_name": "Lovelace", "is_superuser": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["first_name"], body["last_name"]) == ("Ada", "Lovelace")
    assert body["is_superuser"] is True
    assert body["name"] == "Old Name"  # the Google display name is untouched

    db = Session()
    u = db.get(User, ids["staff"])
    assert (u.first_name, u.last_name) == ("Ada", "Lovelace")
    db.close()


def test_blank_name_clears_column(ctx):
    as_user, ids, Session = ctx
    su = as_user(ids["su"])
    su.patch(f"/admin/users/{ids['staff']}", json={"first_name": "Ada", "last_name": "Lovelace"})
    r = su.patch(f"/admin/users/{ids['staff']}", json={"last_name": "   "})
    assert r.status_code == 200, r.text
    assert r.json()["last_name"] is None
    assert r.json()["first_name"] == "Ada"  # untouched: absent from the body


def test_email_normalized_and_unlinks_google_sub(ctx):
    as_user, ids, Session = ctx
    su = as_user(ids["su"])
    r = su.patch(f"/admin/users/{ids['staff']}", json={"email": "  New.Staff@UMN.edu "})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "new.staff@umn.edu"

    db = Session()
    u = db.get(User, ids["staff"])
    assert u.google_sub is None  # old Google identity dropped so the new address can link
    db.close()


def test_unchanged_email_keeps_google_sub(ctx):
    as_user, ids, Session = ctx
    su = as_user(ids["su"])
    r = su.patch(f"/admin/users/{ids['staff']}", json={"email": "STAFF@umn.edu", "first_name": "A"})
    assert r.status_code == 200, r.text
    db = Session()
    assert db.get(User, ids["staff"]).google_sub == "google-123"
    db.close()


def test_duplicate_email_conflicts(ctx):
    as_user, ids, _ = ctx
    su = as_user(ids["su"])
    r = su.patch(f"/admin/users/{ids['staff']}", json={"email": "taken@umn.edu"})
    assert r.status_code == 409, r.text


def test_blank_email_rejected(ctx):
    as_user, ids, _ = ctx
    assert as_user(ids["su"]).patch(f"/admin/users/{ids['staff']}", json={"email": " "}).status_code == 400


def test_cannot_demote_self(ctx):
    as_user, ids, Session = ctx
    su = as_user(ids["su"])
    r = su.patch(f"/admin/users/{ids['su']}", json={"is_superuser": False})
    assert r.status_code == 400, r.text
    db = Session()
    assert db.get(User, ids["su"]).is_superuser is True
    db.close()
    # ...but editing your own name is fine.
    assert su.patch(f"/admin/users/{ids['su']}", json={"first_name": "Root"}).status_code == 200


def test_unknown_user_404(ctx):
    as_user, ids, _ = ctx
    assert as_user(ids["su"]).patch("/admin/users/99999", json={"first_name": "X"}).status_code == 404
