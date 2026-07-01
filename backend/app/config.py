"""Application settings, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "Wearable Hub"
    app_version: str = "0.5.0"  # keep in sync with backend/pyproject.toml + frontend/package.json
    environment: str = "dev"  # dev | prod

    # Public URL path prefix the app is served under on the host (e.g. "/wearable" on lnpitask,
    # where everything lives under https://host/wearable/ to avoid colliding with other apps).
    # Used only for building subject-facing enroll links/redirects so they stay inside the prefix;
    # the backend routes themselves are unprefixed (host nginx strips it). "" = served at root.
    public_path_prefix: str = ""

    # --- Database ---
    # External MariaDB; override per environment via .env.
    database_url: str = "mysql+pymysql://wearable:wearable@localhost:3306/wearable_hub"

    # --- Token encryption at rest (Fernet) ---
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str = ""

    # --- Google Health API / Fitbit OAuth (Milestone 1) ---
    google_client_id: str = ""
    google_client_secret: str = ""
    # Space-delimited; pull exact (Restricted) strings from the Cloud Console "Data Access" page.
    google_health_scopes: str = ""
    gh_project_id: str = ""
    # The subscriber API addresses the project by NUMBER, not ID (e.g. 569496656627).
    gh_project_number: str = ""
    # Client-chosen subscriber id (query param on the subscribers endpoint).
    gh_subscriber_id: str = "wearable-hub"
    # Space-separated dataTypes for the subscriber config (e.g. "steps sleep heart_rate").
    gh_subscription_data_types: str = ""
    # AUTOMATIC = Google auto-creates per-user subscriptions on consent; MANUAL = we create them.
    gh_subscription_create_policy: str = "AUTOMATIC"

    # --- Garmin Health API (OAuth 1.0a; second provider) ---
    # Consumer key/secret from the Garmin Developer portal. OAuth1a tokens don't expire and
    # there's no subscription API — Garmin pushes data to the per-datatype webhook endpoints.
    garmin_consumer_key: str = ""
    garmin_consumer_secret: str = ""
    # Subject OAuth callback (must match the redirect registered in the Garmin portal).
    garmin_oauth_redirect_uri: str = "https://lnpitask.umn.edu/enroll/callback"
    # Base URLs (confirm against current Garmin docs before live test).
    garmin_request_token_url: str = "https://connectapi.garmin.com/oauth-service/oauth/request_token"
    garmin_authorize_url: str = "https://connect.garmin.com/oauthConfirm"
    garmin_access_token_url: str = "https://connectapi.garmin.com/oauth-service/oauth/access_token"
    # Garmin Health (wellness) REST base — used for the user-id lookup and deregistration.
    garmin_api_base: str = "https://apis.garmin.com/wellness-api/rest"
    # Backfill (historical re-push) — Garmin caps each request at 90 days AND only serves ~30 days
    # before the user connected, so history is shallow. Only these summary types are **backfillable**;
    # `pulseox`/`bodyComps`/`skinTemp`/`epochs`/`healthSnapshot` are **webhook-only** (Garmin returns
    # 404/400 on their backfill path), so they're excluded — their data still arrives live going
    # forward, just not via backfill. Comma-separated; override per deployment.
    garmin_backfill_max_window_days: int = 90
    garmin_backfill_types: str = "dailies,sleeps,stressDetails,hrv,respiration,userMetrics"
    # Garmin throttles backfill hard (a burst gets one request through, then 429s). Space requests
    # out and retry each on 429 (honoring Retry-After). Spacing is seconds between requests; retries
    # are per request. The fan-out runs in the background, so minutes-long pacing is fine.
    garmin_backfill_request_spacing_seconds: float = 3.0
    garmin_backfill_max_retries: int = 5

    # --- Researcher auth (Google login + RBAC) ---
    # Reuses GOOGLE_CLIENT_ID/SECRET. The researcher login callback (add this exact URI to the
    # Cloud Console OAuth client's authorized redirect URIs).
    researcher_oauth_redirect_uri: str = "http://localhost:8020/auth/callback"
    researcher_google_scopes: str = "openid email profile"
    # Bootstrap superadmins: these emails are auto-provisioned as superusers on first login.
    superadmin_emails: str = ""  # comma-separated
    # Signed+encrypted session cookie (Fernet, reuses FERNET_KEY) lifetime.
    session_ttl_seconds: int = 60 * 60 * 12  # 12h

    # --- Daily consolidation scheduler (the `scheduler` compose service) ---
    # Nightly safety-net: re-mark recent days dirty + drain, at this hour (container TZ, UTC).
    consolidation_nightly_hour: int = 4
    # Also drain the pending dirty-day queue every N minutes (catches missed real-time tasks);
    # set 0 to disable.
    consolidation_drain_interval_minutes: int = 5
    # Intraday heart-rate (opt-in per study) is downsampled to N-minute bucket averages before
    # storage (raw HR is 1000+ samples/day). Set 0 to store raw samples (heavy).
    hr_downsample_minutes: int = 5
    # Intraday steps/distance (opt-in per study via `ingest_intraday_activity`) are integrated into
    # N-minute SUM buckets (raw is 1-min, ~350/day each). Set 0 to store raw 1-min points.
    steps_bucket_minutes: int = 5
    # Intraday SpO2 (opt-in per study via `ingest_intraday_spo2`) is downsampled to N-minute
    # average buckets (bucket min preserved in payload). Set 0 to store raw samples (~390/day).
    spo2_downsample_minutes: int = 5
    # Intraday stress (opt-in per study via `ingest_intraday_stress`, Garmin) is downsampled to
    # N-minute average buckets (raw is ~3-min, ~480/day). Set 0 to store raw samples.
    stress_downsample_minutes: int = 5

    # --- Project-level credentials for Tier-1 subscriber registration ---
    # Subscriber registration is a project op, NOT a user op (a subject's token gets 403).
    # Path to a service-account key JSON mounted into the container; empty → fall back to
    # Application Default Credentials (google.auth.default).
    gh_sa_credentials_file: str = ""
    # Scopes for the service-account token used for project/subscriber management.
    gh_sa_scopes: str = "https://www.googleapis.com/auth/cloud-platform"

    # --- Public URLs (host: lnpitask.umn.edu, HTTPS) ---
    # Google requires HTTPS redirect URIs; must exactly match the Cloud Console authorized URI.
    oauth_redirect_uri: str = "https://lnpitask.umn.edu/enroll/callback"
    webhook_public_url: str = "https://lnpitask.umn.edu/webhooks/google-health"
    # Shared secret for verifying inbound webhook notifications (scheme TBD per Google docs).
    webhook_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
