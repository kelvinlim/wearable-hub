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
- **Researcher auth + RBAC** — Google sign-in (reuses the project's OAuth client; id_token
  verified via google-auth) establishes a Fernet-signed session cookie. Allowlist = the `users`
  table; `SUPERADMIN_EMAILS` bootstraps superadmin(s) on first login. Access model: superusers
  do anything; other researchers are scoped to studies they have a `study_memberships` row for
  ('admin' manages the study's subjects + members, 'member' is read-only). Every `/admin` route
  is gated; project-level ops (subscriber/sync/run-due) are superuser-only; `/enroll` +
  `/webhooks` stay public. Endpoints: `/auth/{login,callback,logout,me}`, `/admin/users`,
  `/admin/studies/{id}/members`. Verified headlessly (401 gating, superuser vs scoped access,
  member→admin escalation, cross-study 403, bootstrap provisioning). The console now gates its UI
  by role (create-study = superuser; add-subject/consolidate/revoke = study admin; researcher +
  member management panels). **Setup needed:** add `RESEARCHER_OAUTH_REDIRECT_URI` to the Google
  client's authorized redirect URIs + set `SUPERADMIN_EMAILS`; the live browser login is then
  end-to-end.
- **Researcher console (Vite/React)** — `frontend/`: create/list studies, add subjects (shows
  entry codes + linked status), view a subject's consolidated `daily_health` (steps/distance/
  calories/floors/sleep/points), pull+consolidate a date range, and revoke a subject. Served by
  nginx (`frontend` compose service, host `:8020`) which also reverse-proxies `/admin`,
  `/enroll`, `/webhooks` to the backend — same-origin, no CORS, no backend changes. The subject
  enrollment flow stays the server-rendered `/enroll` (OAuth-coupled), linked from the console.
  **Public deployment:** served at `https://omnikog.asuscomm.com/wearable/` — the SPA is built
  with Vite `base: /wearable/` and prefixes its API calls, and the host nginx strips the prefix
  to the frontend container (so the container is unchanged). Host nginx snippet (not in repo):
  `location /wearable/ { proxy_pass http://127.0.0.1:8020/; }` (trailing slash strips the prefix).
- **Console data views + export** — clicking a subject's daily row **expands to its intraday
  points** (`GET /admin/subjects/{id}/daily/{day}/points`), grouped by datatype with local
  start–end times and values; **sleep** shows its stage architecture (AWAKE/LIGHT/DEEP/REM
  minutes — a day summary from `metrics.sleep` plus per-session breakdowns). **Export**
  (`GET /admin/subjects/{id}/export?start=&end=`, study-view) with From/To range and three
  formats: **JSON** (each day's summary with intraday points + sleep stages nested), **CSV
  daily** (one row/day incl. stage-minute totals), **CSV intraday points** (one row/point). CSV
  is generated client-side from the export JSON. Small UX: add-forms disable until an email is
  typed; duplicate-researcher returns a clear "&lt;email&gt; is already a researcher".
- **Daily consolidation** — one row per subject per **local** day in `daily_health` (hybrid:
  typed `steps`/`distance_m`/`calories`/`floors`/`sleep_minutes` columns + a JSON `metrics`
  blob). Since webhooks carry no values, each touched subject-day is *pulled* from Google and
  aggregated: summable metrics from Google's **`dailyRollUp`** (server-computed daily totals),
  **sleep** from listed stages (AWAKE/LIGHT/DEEP/REM minutes), raw intraday points persisted in
  `health_data_points`. Three triggers: real-time (webhook marks the day dirty in
  `consolidation_state` → `BackgroundTasks` drain), a **`scheduler` compose service**
  (APScheduler: a nightly safety-net that re-marks recent days + a short-interval drain of the
  dirty-day queue that recovers any missed real-time task), and on-demand
  `POST /admin/subjects/{id}/consolidate?start=&end=` (backfill). Idempotent (unique keys); revoked tokens mark the day `error` and flip the account.
  Verified end-to-end: subject 3 / 2026-06-11 — steps/distance/calories/sleep populated, raw-point
  sum == rollup, re-run produced no duplicates.
- **Heart rate + HRV** — NOT webhook-subscribable, so pulled during consolidation: daily
  average/min/max BPM via `dailyRollUp`, plus resting HR and HRV via day-filtered `list`
  (read ids `heart-rate`, `daily-resting-heart-rate`, `daily-heart-rate-variability`). Stored as
  typed `daily_health.hr_avg`/`resting_hr`/`hrv_ms` columns (migration 0006) + full detail in
  `metrics`; surfaced in the console daily table, JSON export, and daily CSV. Days get pulled
  via other datatypes' dirty marking + the nightly job; older rows backfill HR/HRV on the next
  consolidation.
- **Intraday heart rate (opt-in per study)** — raw HR is 1000+ samples/day, so it's off by
  default and **downsampled**: a `studies.ingest_intraday_hr` flag (migration 0007; toggle in
  the console / `PATCH /admin/studies/{id}`) makes consolidation pull the day's HR samples and
  store **N-minute average-BPM buckets** (`HR_DOWNSAMPLE_MINUTES`, default 5 → ~288/day) as
  `heart_rate` points — visible in the day expansion and the export. Verified: 288 buckets/day
  (e.g. 16:00–16:05 UTC → 63.1 BPM from 129 samples).
- **Revocation handling** — three converging triggers flip `provider_account.registered` and
  drop stored tokens: (1) **outbound** `POST /admin/subjects/{id}/revoke` revokes the grant at
  Google then marks the account revoked; (2) **reactive** — a token refresh returning
  `invalid_grant` raises `GrantRevokedError` so read paths can mark the account revoked
  without retrying a dead token; (3) **inbound** — a best-effort deregistration-webhook hook
  (shape unverified; logs loudly to capture the real payload). Revocation is idempotent.

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

- **Subject enroll page as React** — the researcher console is React, but the subject-facing
  `/enroll` flow is still server-rendered HTML (it's OAuth-redirect-coupled and works as-is).
- **Inbound deregistration shape** — the deregistration-webhook handler is best-effort; the
  real Google payload is undocumented/unobserved. Confirm and tighten once one is captured.
- **Consolidation follow-ups** — deep *historical* sleep/height backfill is bounded (those
  types aren't civil-time filterable, so we page newest-first and stop at the target day —
  fine for recent days, limited for far-back dates). Real-time drain uses in-process
  `BackgroundTasks`; promote to a standalone worker if pull latency/volume grows. floors &
  calories have no raw intraday points (rollup-only — not listable).
- **Scheduled token refresh before reads** — consolidation refreshes per pull; there's still
  no standalone data-read endpoint, but the reactive `GrantRevokedError` path is now exercised
  by consolidation.

### Deferred (later milestones)

- Garmin provider (OAuth 1.0a + push webhooks).
- Whole-study export (all subjects at once); per-session sleep hypnogram view.
- Production Restricted-scope security review (CASA) for non-test users.
