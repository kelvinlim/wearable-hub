"""Google Search Console verification on public server-rendered pages.

Homepage / privacy / the HTML-file route do not touch the DB.
"""

from fastapi.testclient import TestClient

from app.branding import GOOGLE_SITE_VERIFICATION
from app.main import app
from app.routers.public import GSC_HTML_BODY, GSC_HTML_FILE

client = TestClient(app)

META = f"<meta name='google-site-verification' content='{GOOGLE_SITE_VERIFICATION}' />"


def test_homepage_and_privacy_carry_gsc_meta():
    for path in ("/", "/privacy"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert META in r.text, path


def test_gsc_html_file_get_and_head():
    r = client.get(f"/{GSC_HTML_FILE}")
    assert r.status_code == 200
    assert r.text == GSC_HTML_BODY
    assert r.text == f"google-site-verification: {GOOGLE_SITE_VERIFICATION}"

    h = client.head(f"/{GSC_HTML_FILE}")
    assert h.status_code == 200
