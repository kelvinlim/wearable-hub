"""Researcher Google-login callback.

Covers the unauthorized-account path Kelvin hit live: a browser landing on
`/auth/callback` must get a readable HTML page (not raw FastAPI JSON), while
programmatic clients that ask for JSON still get `{"detail": "..."}`.
Authorized sign-in still 303s to the console with a session cookie.

Google's token + id_token steps are monkeypatched — no network. Run from
`backend/`: pytest tests/test_auth.py
"""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import User
from app.routers import auth as auth_module
from app.security import COOKIE_NAME, STATE_COOKIE

STATE = "test-oauth-state"
FERNET = Fernet.generate_key().decode()


@pytest.fixture()
def ctx(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db

    settings = get_settings().model_copy(
        update={
            "fernet_key": FERNET,
            "google_client_id": "test-client.apps.googleusercontent.com",
            "google_client_secret": "test-secret",
            "researcher_oauth_redirect_uri": "http://testserver/auth/callback",
            "superadmin_emails": "",
        }
    )
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)
    monkeypatch.setattr("app.security.get_settings", lambda: settings)

    def make_client(users=()):
        seed = Session()
        seed.add_all(list(users))
        seed.commit()
        seed.close()
        client = TestClient(app, follow_redirects=False)
        client.cookies.set(STATE_COOKIE, STATE)
        return client

    yield make_client, Session
    app.dependency_overrides.clear()


def _mock_google(monkeypatch, email, *, verified=True, name="Pat Researcher"):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "fake-id-token"}

    monkeypatch.setattr(auth_module.httpx, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(
        auth_module.google_id_token,
        "verify_oauth2_token",
        lambda *a, **k: {
            "email": email,
            "email_verified": verified,
            "sub": "google-sub-1",
            "name": name,
        },
    )


def _callback(client, **headers):
    return client.get(
        "/auth/callback",
        params={"code": "auth-code", "state": STATE},
        headers=headers,
    )


def test_unauthorized_browser_gets_html_page(ctx, monkeypatch):
    make_client, _ = ctx
    client = make_client()
    _mock_google(monkeypatch, "visitor@umn.edu")

    r = _callback(client, accept="text/html")
    assert r.status_code == 403
    assert "text/html" in r.headers["content-type"]
    assert "This Google account is not set up for Wearable Hub yet." in r.text
    assert "Account not set up" in r.text
    assert "visitor@umn.edu" in r.text
    assert "study PI or administrator" in r.text
    assert "Back to sign in" in r.text
    assert "href='http://testserver/'" in r.text
    # Must not be the raw FastAPI JSON blob researchers were seeing.
    assert r.text.strip() != '{"detail":"This Google account is not authorized"}'
    assert COOKIE_NAME not in r.cookies


def test_unauthorized_json_client_keeps_api_detail(ctx, monkeypatch):
    make_client, _ = ctx
    client = make_client()
    _mock_google(monkeypatch, "visitor@umn.edu")

    r = _callback(client, accept="application/json")
    assert r.status_code == 403
    assert r.json() == {"detail": auth_module.UNAUTHORIZED_DETAIL}
    assert COOKIE_NAME not in r.cookies


def test_unauthorized_default_accept_is_html(ctx, monkeypatch):
    """TestClient / curl send */* — this is a browser callback, so default to HTML."""
    make_client, _ = ctx
    client = make_client()
    _mock_google(monkeypatch, "visitor@umn.edu")

    r = _callback(client)
    assert r.status_code == 403
    assert "text/html" in r.headers["content-type"]
    assert "not set up for Wearable Hub yet" in r.text


def test_unauthorized_email_is_escaped(ctx, monkeypatch):
    make_client, _ = ctx
    client = make_client()
    _mock_google(monkeypatch, "<script>alert(1)</script>@umn.edu")

    r = _callback(client, accept="text/html")
    assert r.status_code == 403
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;@umn.edu" in r.text


def test_authorized_sign_in_redirects(ctx, monkeypatch):
    make_client, Session = ctx
    client = make_client([User(email="staff@umn.edu", name="Staff", is_superuser=False)])
    _mock_google(monkeypatch, "staff@umn.edu", name="Staff Member")

    r = _callback(client, accept="text/html")
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "http://testserver/"
    assert COOKIE_NAME in r.cookies

    db = Session()
    u = db.scalar(select(User).where(User.email == "staff@umn.edu"))
    assert u is not None
    assert u.name == "Staff Member"
    assert u.google_sub == "google-sub-1"
    db.close()


def test_unknown_email_is_not_provisioned(ctx, monkeypatch):
    make_client, Session = ctx
    client = make_client()
    _mock_google(monkeypatch, "stranger@umn.edu")

    r = _callback(client)
    assert r.status_code == 403
    db = Session()
    assert db.scalar(select(func.count()).select_from(User)) == 0
    db.close()


def test_invalid_state_is_html_for_browsers(ctx):
    make_client, _ = ctx
    client = make_client()
    r = client.get(
        "/auth/callback",
        params={"code": "auth-code", "state": "wrong-state"},
        headers={"accept": "text/html"},
    )
    assert r.status_code == 400
    assert "text/html" in r.headers["content-type"]
    assert "Back to sign in" in r.text
    assert "expired" in r.text.lower()
