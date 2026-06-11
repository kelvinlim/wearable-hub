# Changelog

All notable changes to Wearable Hub are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); this is pre-1.0, so it tracks
milestone progress rather than released versions.

## [Unreleased] — Milestone 1: Fitbit-via-Google-Health OAuth end-to-end

The first vertical slice: register research subjects' Fitbit data against the new
Google Health API (Google OAuth 2.0 + two-tier webhook subscriptions), replacing the
legacy Fitbit Web API. One FastAPI app with per-provider OAuth modules; fresh normalized
schema; tokens encrypted at rest. Researcher auth/RBAC and Garmin are deferred.

### Working

- **Backend scaffold** — FastAPI app (`backend/`), SQLAlchemy 2.0 models, pydantic-settings
  config, Fernet token encryption, Alembic migrations, Docker Compose (MariaDB + backend).
- **OAuth enrollment (Tier-0)** — entry-code enrollment → Google OAuth2 + PKCE
  (`access_type=offline` + `prompt=consent` for refresh tokens) → token exchange →
  encrypted storage of access/refresh tokens, expiry, scope, and `provider_user_id`
  (from the id_token `sub`). State + PKCE verifier persisted on the `provider_accounts`
  row (request-safe), not in process globals.
- **Tier-1 project subscriber registration** — `POST /admin/subscriber` mints a token from
  the project **service account** (`secrets/health-sa.json`, mounted read-only) and
  registers the project's webhook subscriber. Idempotent (treats Google's `409
  ALREADY_EXISTS` as success and reconciles the DB row from the live resource).
  `GET /admin/subscriber` reports status. Subscriber persisted in `project_subscribers`.
- **Webhook receiver** — `POST /webhooks/google-health` satisfies Google's registration-time
  verification handshake (authorized probe → 200, unauthorized → 401), parses real
  notifications, links them to subjects by `healthUserId`, lands them in `health_data`, and
  always returns 200 fast so Google doesn't disable the subscription.
- **Tier-2 per-user data flow (AUTOMATIC) — verified end-to-end.** After a fresh consent,
  Google auto-creates per-user subscriptions and pushes webhook notifications with real
  Fitbit data (Charge 6: steps, distance, calories, floors, altitude, sleep). Each
  notification's `healthUserId` is captured and linked to the subject's account; 219 real
  data points landed and linked for the test subject.
- **Minimal admin API** — create study, create subject (auto entry code), list subjects +
  registration status. Unprotected for Milestone 1 (auth deferred).

### Verified against the live Google Health API (2026-06-11)

- Subscriber path uses the project **NUMBER**, not the ID; `subscriberId` is a query param.
- `endpointAuthorization.secret` is the **full header value** (`"Bearer <secret>"`), echoed
  verbatim on inbound notifications.
- **Only a fixed set of dataTypes is webhook-subscribable:** `steps, sleep, distance,
  calories, weight, height, floors, exercise, altitude`. Heart rate (any spelling), HRV,
  SpO2, VO2 max, active/zone minutes, body fat, and respiratory rate are **pull-only** via
  the dataPoints read and return a bare `400 INVALID_ARGUMENT` if used in a subscription.
  `fitbit_gh.SUBSCRIBABLE_DATA_TYPES` guards config with a clear error. All 9 subscribable
  types are registered.
- Subscriber `create` can return a long-running **Operation** (async endpoint verification);
  there is no GET-by-id route (only LIST), so the subscriber is resolved via LIST.
- **Token refresh works** — refreshing the enrolled subject's expired access token via the
  stored refresh token succeeds.
- **Pull data read works** — `GET /v4/users/me/dataTypes/steps/dataPoints` with the subject's
  user token returns real Fitbit data (Charge 6, live step intervals).
- **AUTOMATIC behavior (verified):**
  - Subscriptions are created on a **fresh authorization grant only** — re-consenting an
    existing grant does nothing; the grant must be revoked first (we revoke via
    `oauth2.googleapis.com/revoke`). It is also not retroactive to already-consented subjects.
  - AUTOMATIC subscriptions (named `auto-{project}-{subscriber}-WEBHOOK_DATA_TYPE_*`) do
    **not** appear in `subscribers.subscriptions.list` — so `/admin/subscriptions/sync` is for
    MANUAL only; under AUTOMATIC, account linking comes from webhook payloads.
- **Real notification shape (verified):** the webhook body is a JSON **array** of
  `{"data": {version, clientProvidedSubscriptionName, healthUserId, operation, dataType,
  intervals}}` items (Google batches up to ~15 per POST); interval start is at
  `intervals[].physicalTimeInterval.startTime`. `healthUserId` (e.g. `2390357961573276417`)
  differs from the OAuth `sub` and is the key used to link data to a subject.
- **Tier-2 manual-create shape** (for the MANUAL path, if adopted):
  `POST /v4/projects/{NUMBER}/subscribers/{sub}/subscriptions` with
  `{"user": "users/{healthUserId}", "dataTypes": [...]}`. `list_subscriptions()` /
  `create_subscription()` corrected to this (previously used project ID + a non-existent
  `userId` field). Manual create requires the subscriber policy to be MANUAL.

### Not yet done (remaining Milestone 1)

- **Frontend (Vite)** — enroll page + minimal researcher page are still server-rendered
  placeholders; not scaffolded as React.
- **Revocation handling** — when a subject's grant is revoked (or Google sends a
  deregistration notification), flip `provider_account.registered` automatically.
- **Async processing of `health_data`** — payloads land raw; downstream normalization/
  parsing into typed tables is deferred.
- Frontend (Vite): enroll page + minimal researcher page — not scaffolded.
- Token-refresh-before-read path exists but is unexercised.

### Deferred (later milestones)

- Researcher Google-login auth + RBAC (`roles`, `study_memberships`).
- Garmin provider (OAuth 1.0a + push webhooks).
- Data review + download UI.
