"""Study admins assign + onboard research staff.

TestClient against in-memory SQLite. A non-superuser who is `admin` of a study can list assignable
researchers, add existing ones, and onboard brand-new ones (auto-created as non-superusers) — but
cannot mint a superuser, and a non-admin is forbidden. Run from `backend/`: pytest tests/test_members.py
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Study, StudyMembership, User
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
    admin = User(email="admin@umn.edu", is_superuser=False)
    member = User(email="member@umn.edu", is_superuser=False)
    other = User(email="other@umn.edu", is_superuser=False)  # researcher, not on the study
    s.add_all([su, admin, member, other])
    s.flush()
    study = Study(name="A", provider="fitbit_gh")
    s.add(study)
    s.flush()
    s.add_all([
        StudyMembership(user_id=admin.id, study_id=study.id, role="admin"),
        StudyMembership(user_id=member.id, study_id=study.id, role="member"),
    ])
    s.commit()
    ids = {"su": su.id, "admin": admin.id, "member": member.id, "other": other.id, "study": study.id}
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


def test_assignable_excludes_members_and_needs_admin(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    r = admin.get(f"/admin/studies/{ids['study']}/assignable-users")
    assert r.status_code == 200, r.text
    emails = {u["email"] for u in r.json()}
    assert "other@umn.edu" in emails  # researcher not on the study
    assert "admin@umn.edu" not in emails and "member@umn.edu" not in emails  # already members
    # A read-only member of the study is not an admin → forbidden.
    assert as_user(ids["member"]).get(f"/admin/studies/{ids['study']}/assignable-users").status_code == 403


def test_admin_adds_existing_researcher(ctx):
    as_user, ids, _ = ctx
    admin = as_user(ids["admin"])
    r = admin.post(f"/admin/studies/{ids['study']}/members", json={"email": "other@umn.edu", "role": "member"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "other@umn.edu"
    # now excluded from assignable
    emails = {u["email"] for u in admin.get(f"/admin/studies/{ids['study']}/assignable-users").json()}
    assert "other@umn.edu" not in emails


def test_admin_onboards_new_researcher_as_nonsuper(ctx):
    as_user, ids, Session = ctx
    admin = as_user(ids["admin"])
    r = admin.post(
        f"/admin/studies/{ids['study']}/members",
        json={"email": "New.Person@UMN.edu", "name": "New Person", "role": "admin"},
    )
    assert r.status_code == 201, r.text
    db = Session()
    u = db.query(User).filter(User.email == "new.person@umn.edu").one()  # normalized lowercase
    assert u.is_superuser is False  # study admin can never mint a superuser
    assert u.name == "New Person"
    db.close()


def test_member_cannot_add(ctx):
    as_user, ids, _ = ctx
    member = as_user(ids["member"])
    r = member.post(f"/admin/studies/{ids['study']}/members", json={"email": "x@umn.edu", "role": "member"})
    assert r.status_code == 403
