"""Study admins (and superusers) can rename a study after creation.

TestClient against in-memory SQLite. A study admin can PATCH `name` (trimmed); a plain
member cannot; empty / whitespace-only names are rejected. Run from `backend/`:
pytest tests/test_study_rename.py
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
    s.add_all([su, admin, member])
    s.flush()
    study = Study(name="Original name", provider="fitbit_gh")
    s.add(study)
    s.flush()
    s.add_all([
        StudyMembership(user_id=admin.id, study_id=study.id, role="admin"),
        StudyMembership(user_id=member.id, study_id=study.id, role="member"),
    ])
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

    yield as_user, ids
    app.dependency_overrides.clear()


def _study_name(client, study_id):
    studies = client.get("/admin/studies").json()
    return next(s for s in studies if s["id"] == study_id)["name"]


def test_admin_can_rename_study(ctx):
    as_user, ids = ctx
    admin = as_user(ids["admin"])
    r = admin.patch(f"/admin/studies/{ids['study']}", json={"name": "  Renamed study  "})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed study"
    assert _study_name(admin, ids["study"]) == "Renamed study"


def test_superuser_can_rename_study(ctx):
    as_user, ids = ctx
    su = as_user(ids["su"])
    r = su.patch(f"/admin/studies/{ids['study']}", json={"name": "SU rename"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "SU rename"


def test_member_cannot_rename_study(ctx):
    as_user, ids = ctx
    member = as_user(ids["member"])
    r = member.patch(f"/admin/studies/{ids['study']}", json={"name": "Nope"})
    assert r.status_code == 403
    # Name is unchanged; a study admin can still see the original.
    admin = as_user(ids["admin"])
    assert _study_name(admin, ids["study"]) == "Original name"


def test_empty_name_rejected(ctx):
    as_user, ids = ctx
    admin = as_user(ids["admin"])
    for blank in ("", "   "):
        r = admin.patch(f"/admin/studies/{ids['study']}", json={"name": blank})
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "name must not be empty"
    assert _study_name(admin, ids["study"]) == "Original name"
