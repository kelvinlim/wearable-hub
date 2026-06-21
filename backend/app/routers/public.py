"""Public, unauthenticated pages required for Google OAuth verification.

Google's restricted-scope review requires a publicly reachable **homepage** and a
**privacy policy on the same domain**, neither behind a login. These render with the
shared UMN-branded shell (`app.branding`). The privacy-policy copy here is the live
mirror of `docs/google-verification/03-privacy-policy.md` — keep the two in sync.

Contact / PI / IRB details are constants below — update them if the study contact changes.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.branding import page

router = APIRouter(tags=["public"])

# 150x150 UMN icon hosted at a stable root URL so external developer portals
# (e.g. Garmin Connect Developer's required "branding image") can resolve it on
# our verified domain. Baked into the backend image via `COPY . .`.
BRANDING_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "branding.png"
BRANDING_IMAGE_JPG = Path(__file__).resolve().parent.parent / "assets" / "branding.jpg"

# Bump when the policy text changes (Google expects a dated, versioned policy).
PRIVACY_LAST_UPDATED = "June 18, 2026"

# Study contact shown in the homepage / privacy policy and the OAuth consent screen.
PI_NAME = "Kelvin O. Lim"
SUPPORT_EMAIL = "kolim@umn.edu"
IRB_NUMBER = "STUDY00026668"


@router.get("/", response_class=HTMLResponse)
def homepage() -> HTMLResponse:
    """Public landing page — the OAuth consent screen's Home Page URL."""
    body = (
        "<h1>University of Minnesota Wearable Hub</h1>"
        "<p class='lead'>Wearable Hub is a University of Minnesota research application that "
        "lets enrolled study participants securely share data from their wearable device "
        "(such as a Fitbit) with their study team.</p>"
        "<h2>What it does</h2>"
        "<p>With your permission, Wearable Hub collects your activity, sleep, heart-rate, "
        "blood-oxygen (SpO2), heart-rate-variability, and wearable-device information and makes "
        "it available to the research team for the study you enrolled in. Data is collected only "
        "after you authorize it through Google, and only for as long as you take part.</p>"
        "<h2>Who it's for</h2>"
        "<p>Wearable Hub is used only by participants enrolled in University of Minnesota research "
        "studies and by the authorized researchers running those studies. It is not a "
        "general-purpose consumer app.</p>"
        "<h2>Getting started</h2>"
        "<p>If your study staff gave you a study code, you can connect your device on the "
        "enrollment page. Taking part is voluntary, and you can stop sharing at any time.</p>"
        "<a class='btn' href='/enroll'>Enroll with your study code</a>"
        "<h2>Your privacy</h2>"
        "<p>We explain exactly what we collect, how we use it, and how to withdraw in our "
        "<a href='/privacy'>Privacy Policy</a>. Wearable Hub's use of information received from "
        "Google APIs adheres to the "
        "<a href='https://developers.google.com/terms/api-services-user-data-policy'>Google API "
        "Services User Data Policy</a>, including the Limited Use requirements.</p>"
        f"<p class='muted'>Questions? Contact the study team at {SUPPORT_EMAIL}.</p>"
    )
    return page("Wearable Hub", body)


@router.get("/branding.png", include_in_schema=False)
def branding_image() -> FileResponse:
    """Branding icon for external developer-portal registration (Garmin, etc.)."""
    return FileResponse(BRANDING_IMAGE, media_type="image/png")


@router.get("/branding.jpg", include_in_schema=False)
def branding_image_jpg() -> FileResponse:
    """JPEG variant — Garmin's branding-image validator rejects the PNG."""
    return FileResponse(BRANDING_IMAGE_JPG, media_type="image/jpeg")


@router.get("/privacy", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    """Privacy policy — the OAuth consent screen's Privacy Policy URL."""
    body = (
        "<h1>Privacy Policy</h1>"
        f"<p class='muted'>Last updated: {PRIVACY_LAST_UPDATED}</p>"
        "<p class='lead'>This policy explains how the University of Minnesota Wearable Hub "
        "application (\"Wearable Hub\", \"we\", \"us\") collects, uses, stores, and shares "
        "information when you connect your wearable device to a research study.</p>"

        "<h2>Who is responsible for your data</h2>"
        "<p>The data controller is the Regents of the University of Minnesota, on behalf of the "
        f"research study led by {PI_NAME}. This study is conducted under University of Minnesota "
        f"IRB approval {IRB_NUMBER}. Questions can be directed to {SUPPORT_EMAIL}.</p>"

        "<h2>What information we collect</h2>"
        "<p>After you authorize access through your Google/Fitbit account, we collect the "
        "following health and wellness data from the Google Health API:</p>"
        "<ul>"
        "<li><b>Activity &amp; fitness</b> — steps, distance, calories, floors, and exercise "
        "sessions (daily totals and intraday detail).</li>"
        "<li><b>Sleep</b> — sleep duration and sleep-stage breakdown.</li>"
        "<li><b>Heart rate</b> — average, minimum, maximum, and resting heart rate, and (when "
        "your study enables it) intraday heart-rate samples.</li>"
        "<li><b>Other health metrics</b> — heart-rate variability and blood-oxygen saturation "
        "(SpO2).</li>"
        "<li><b>Device information</b> — your paired wearable's model, battery level, and last "
        "sync time.</li>"
        "<li><b>Account linkage</b> — OAuth tokens and a Google-provided account identifier so we "
        "can retrieve your data on an ongoing basis.</li>"
        "</ul>"

        "<h2>How we use your information</h2>"
        "<p>We use your data solely to carry out the research study you enrolled in — to retrieve, "
        "store, summarize, and analyze your wearable measurements. We do <b>not</b> use your data "
        "for advertising, we do <b>not</b> sell it, and we do <b>not</b> use it for any purpose "
        "unrelated to the research. Wearable Hub's use of information received from Google APIs "
        "adheres to the "
        "<a href='https://developers.google.com/terms/api-services-user-data-policy'>Google API "
        "Services User Data Policy</a>, including the <b>Limited Use</b> requirements.</p>"

        "<h2>How we store and protect your information</h2>"
        "<p>Your data is stored in a secured University of Minnesota database with restricted, "
        "role-based access limited to authorized members of your study team. Access and refresh "
        "tokens are encrypted at rest. Access to the researcher console requires authenticated "
        "sign-in and is scoped to each researcher's authorized studies.</p>"

        "<h2>How we share your information</h2>"
        "<p>Your data is accessed only by the authorized research team for your study. We do not "
        "share it with third parties except as required to operate the study's secure "
        "infrastructure or as required by law or University policy.</p>"

        "<h2>Data retention</h2>"
        "<p>We retain your data for the duration of the research study and any retention period "
        "required by the study protocol, University policy, or applicable law. You may request "
        "deletion of your data at any time (see below).</p>"

        "<h2>Withdrawing and deleting your data</h2>"
        "<p>Taking part is voluntary. You can stop sharing at any time by:</p>"
        "<ul>"
        "<li>contacting your study staff, who can revoke the connection and remove your data; or</li>"
        "<li>removing the app's access in your Google Account security settings.</li>"
        "</ul>"
        "<p>When access is revoked, we stop collecting new data and delete the stored "
        "authorization tokens. You may also request deletion of previously collected data by "
        f"contacting the study team at {SUPPORT_EMAIL}.</p>"

        "<h2>Changes to this policy</h2>"
        "<p>We may update this policy; the \"Last updated\" date above reflects the current "
        "version.</p>"

        "<h2>Contact</h2>"
        f"<p>For privacy questions, contact the study team at {SUPPORT_EMAIL}.</p>"
    )
    return page("Privacy Policy", body)
