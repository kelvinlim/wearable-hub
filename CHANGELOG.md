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
  verification handshake (authorized probe → 200, unauthorized → 401), lands payloads in
  `health_data`, and always returns 200 fast so Google doesn't disable the subscription.
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

### Not yet done (remaining Milestone 1)

- **Tier-2 per-user subscription** — request/response shape and credential unverified; with
  `subscriptionCreatePolicy=AUTOMATIC`, Google may auto-create per-user subscriptions on
  consent. Needs end-to-end verification.
- Full enroll → subscription → webhook → `health_data` walk-through with a real subject.
- Webhook account linking: notification `healthUserId` may differ from the stored OAuth
  `sub`; data can currently land with a null account.
- Frontend (Vite): enroll page + minimal researcher page — not scaffolded.
- Token-refresh-before-read path exists but is unexercised.

### Deferred (later milestones)

- Researcher Google-login auth + RBAC (`roles`, `study_memberships`).
- Garmin provider (OAuth 1.0a + push webhooks).
- Data review + download UI.
