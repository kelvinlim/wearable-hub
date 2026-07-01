# Changelog

All notable changes to Wearable Hub are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); this is pre-1.0, so it tracks
milestone progress rather than released versions.

## [0.5.1] — 2026-07-01

### Fixed

- **"Gateway Time-out" on long Pull + consolidate.** The synchronous backfill of a multi-month
  range could exceed the nginx `proxy_read_timeout` (300s) and return a 504 even though the pull
  succeeded server-side. The console now sends the range in ≤10-day windows sequentially
  (`SubjectDetail.doConsolidate`), so each request stays well under the gateway timeout, days appear
  incrementally, and a failed window keeps the earlier ones. No backend change (the endpoint is
  idempotent per day).

## [0.5.0] — 2026-07-01

### Added

- **Phase 2 — per-project real-time webhook push.** Google Health Tier-1 **subscriber
  registration** and webhook validation now work per **credential set** (per GCP project), not just
  globally, so each project delivers real-time data. Subscriber ops (`register_subscriber`/
  `get_subscriber`/`list_subscriptions`/`create_subscription`, `project_access_token`) take a
  resolved `GHCreds` and load the project's **service account from the set's encrypted `sa_json`**
  (`from_service_account_info`), falling back to the global file/ADC. New superuser endpoints
  `POST/GET /admin/credential-sets/{id}/subscriber` + a **"Register subscriber"** button in the
  Google-projects console (requires the set's project number, SA JSON, a unique webhook secret, and
  data types). `project_subscribers.credential_set_id` (migration `0018`) links each registration
  to its set.
- **Match-any-secret webhook routing.** All projects register the **same** webhook URL with their
  **own** secret; the handler authorizes by trying every known secret (global + each set) and the
  match **identifies the project** — so no nginx change, no new URL, and the global subscriber is
  untouched. Account resolution's unlinked-candidate fallback is now **scoped to the matched
  project** (`credential_set_id`), preventing cross-project mislinks. `_maybe_subscribe` reads the
  account's set policy (AUTOMATIC stays a no-op — Google auto-subscribes).

## [0.4.0] — 2026-07-01

### Added

- **Per-study Google credentials via shared credential sets.** Each study can run on its **own GCP
  project** (own 100-user cap) instead of the single global credential set. A superuser registers a
  named **credential set** (OAuth client id/secret, scopes, project id/number, subscriber id,
  service-account JSON, webhook secret — secrets Fernet-encrypted in `google_credential_sets`) and
  assigns studies to it (`studies.credential_set_id`); many studies may share one set. Enrollment
  resolves the study's set; each `ProviderAccount` **pins the issuing set** so token refresh/revoke
  always use the client that granted the token (reassigning a study affects only new enrollments).
  Unassigned studies fall back to the global env creds (existing `Fitbit Demo` unchanged). Superuser
  "Google projects" console view + per-study picker. Also: per-study **PI name** + **IRB approval
  number** fields. Migration `0017`.

### Verified against the live Google Health API (2026-06-30)

- **Restricted health scopes run unverified in Production under the 100-user cap.** Publishing
  `fitbitdata-499001` to production *without* submitting for verification let a **non-test-user**
  enroll (standard "unverified app" warning, no block). So ≤100 users/project needs **no
  verification and no CASA**; the third-party review is required only for **>100 users**. The cap is
  **per GCP project**, over the project's lifetime — hence per-study projects to scale the program.

## [0.3.10] — 2026-06-29

### Added

- **Reprocess stored Garmin data (no re-fetch).** New `POST /admin/subjects/{id}/reprocess`
  (`garmin_ingest.reprocess_account`) re-runs the per-datatype appliers over an account's
  already-stored raw `health_data` to (re)derive `daily_health`/points — for when you enable an
  intraday opt-in or change a mapping after data already arrived, without asking Garmin to re-push
  (which it won't for an already-delivered window). Idempotent, doesn't re-land raw rows, returns
  per-datatype counts. Console: a **Reprocess stored** button on Garmin subjects (next to backfill).
  Replaces the one-off scripts previously used for the stress and body-battery rollouts.

## [0.3.9] — 2026-06-29

### Added

- **Body Battery (Garmin).** Garmin already sends body battery inside the stress push
  (`timeOffsetBodyBatteryValues`) plus daily charge/drain on `dailies`
  (`bodyBatteryChargedValue`/`bodyBatteryDrainedValue`) — now surfaced. Daily summary
  `metrics.body_battery` carries `charged`/`drained` (from dailies) + `min`/`max`/`latest` (from the
  stress offsets), merged without clobbering across the two pushes; shown as a Body Battery card.
  Intraday body-battery levels are stored as `body_battery` points under the **same opt-in as stress**
  (`ingest_intraday_stress`), rendered over time like heart rate.
- **Steps over time (Garmin epochs).** New `_apply_epochs` stores each ~15-min epoch's `steps` as an
  intraday `steps` point (the only Garmin source of within-day steps; `dailies` carries the day total
  only), gated by the existing `ingest_intraday_activity` opt-in. Requires the **Epochs** webhook
  enabled in the Garmin portal. Distance/intensity/activityType kept in the point payload.

### Changed

- Refactored the duplicated intraday HR/stress downsamplers into one `_store_intraday_avg`; study
  opt-in labels updated (`stress + body battery`, `steps over time`).

## [0.3.8] — 2026-06-29

### Changed

- **The console remembers your page and selected study across a refresh.** Previously a browser
  refresh always dropped you back on Studies and reset the study picker. The current view and
  selected study are now persisted to `localStorage` (same pattern as dark mode); on reload the
  selected study is validated against the studies you can access (falling back to the first), and a
  persisted superuser-only "Researchers" page falls back to Studies for non-superusers. Frontend-only.

## [0.3.7] — 2026-06-29

### Added

- **Intraday stress over time (Garmin).** New per-study opt-in `ingest_intraday_stress` (migration
  `0016`) stores the Garmin stress push's `timeOffsetStressLevelValues` into `health_data_points`
  (datatype `stress`), downsampled to N-minute average buckets (`stress_downsample_minutes`, default
  5; Garmin's negative sentinels −1/−2 dropped). The console's expanded day detail renders it as a
  stress-over-time table just like heart rate. The daily avg/max stress stay in
  `daily_health.metrics.stress` regardless. Toggle on the study's intraday opt-ins (off by default).

## [0.3.6] — 2026-06-29

### Added

- **Expanded day detail now shows a "Daily measures" summary.** Previously the expandable subject
  day only listed intraday point series (for Garmin, just heart rate), so backfilled/pushed sleep,
  stress, respiration, SpO2, user metrics, and skin temperature were invisible even though they were
  stored in `daily_health.metrics`. The detail panel now renders compact cards from that JSON: sleep
  stages (Garmin; Fitbit keeps its session-level `SleepGroup`), stress (avg/max + per-band minutes),
  respiration (avg/min/max), SpO2, user metrics (VO₂max, fitness age), skin-temp deviation, and body
  composition — each shown only when present. Frontend-only; the `/daily` API already returned
  `metrics`.

## [0.3.5] — 2026-06-28

### Fixed

- **Garmin backfill only requests backfillable summary types.** A live backfill showed `pulseox`
  (404), `bodyComps` (400), and `skinTemp` (400) are **webhook-only** — Garmin does not support them
  on the `/backfill/{type}` path (corroborated by the 404/400 codes and Garmin's pipeline docs). They
  are removed from `garmin_backfill_types`, leaving the types that actually backfill
  (`dailies,sleeps,stressDetails,hrv,respiration,userMetrics`); their data still arrives live via
  webhook going forward. Documented Garmin's backfill horizon (~30 days before the user connected),
  which is why historical depth is shallow.

## [0.3.4] — 2026-06-28

### Fixed

- **Garmin backfill no longer trips Garmin's rate limit.** Garmin throttles the backfill endpoint
  hard — a burst got only the first request through (`dailies`) and `429`'d the rest, so sleep /
  stress / HRV / SpO2 / respiration / body-comp / user-metrics / skin-temp were never queued.
  `garmin.request_backfill` now retries each `429` with capped exponential backoff (honoring
  `Retry-After`), and `garmin_backfill` spaces requests apart
  (`garmin_backfill_request_spacing_seconds`, default 3s; `garmin_backfill_max_retries`, default 5).
  Because spacing + retries make the fan-out take minutes, `POST /admin/subjects/{id}/backfill` now
  runs the work in the **background** (`run_backfill`) and returns immediately with a queued shape
  (`{queued, types, windows, requests}`); the console notice reflects the async behavior.

## [0.3.3] — 2026-06-28

### Added

- **Garmin historical backfill.** Garmin has no pull API, so historical data is obtained by asking
  Garmin to re-push summaries to the registered webhooks via `GET /backfill/{summaryType}`. New
  `garmin.request_backfill()` (OAuth1-signed; async `202`, `409` duplicate tolerated) +
  `app/garmin_backfill.py`, which chunks a date range into **≤90-day windows** (Garmin's per-request
  cap, configurable) and fans out across the configured summary types, recording per-`(type, window)`
  status without failing the batch on one bad request. New endpoint
  `POST /admin/subjects/{id}/backfill` (Garmin-only — Fitbit/Google still uses `/consolidate`;
  study-admin scoped, range capped at 2 years). Settings `garmin_backfill_max_window_days` (90) and
  `garmin_backfill_types`. Backfilled data flows through the existing `/webhooks/garmin/{type}` →
  `garmin_ingest` path (idempotent; only **enabled** webhook types actually deliver).
- **Garmin Skin Temperature mapping.** `skinTemp` / `skinTemperature` pushes are aggregated into
  `daily_health.metrics["skin_temp"]` (overnight deviation-from-baseline °C, sleep-only) instead of
  only landing raw. Field naming varies by payload version, so `deviation_c` takes the first present
  of `avgDeviationCelsius` / `averageDeviationCelsius` / `deviationCelsius`; `raw` is always kept.
- **`frontend/build-check.sh`** — runs the production frontend build (`node:20-alpine` + `npm ci`
  against the committed lockfile) in a throwaway container, so a green run matches the image build
  without installing Node on the host and without writing `node_modules` into the working tree.

### Changed

- **Subject-detail data control is now provider-aware.** The console shows "Pull + consolidate" for
  Fitbit/Google subjects (synchronous pull) and "Request backfill" for Garmin subjects (async
  re-push, with an inline notice that data arrives later via webhook); a subject with both devices
  gets both. Fixes the prior bug where the pull button on a Garmin subject hit the Fitbit-only
  consolidate endpoint and errored with `No fitbit_gh account`.

## [0.3.2] — 2026-06-21

### Changed

- **Study admins can onboard + assign research staff via a pulldown.** The study "Research staff"
  card now offers a dropdown of assignable researchers (those not already members) plus an
  "➕ Add new researcher…" option to onboard someone by email. New endpoint
  `GET /admin/studies/{id}/assignable-users` (study-admin scoped). `add_member` now **auto-creates**
  a researcher when the email is new — always as a **non-superuser** (minting superusers stays on
  the superuser-only `POST /admin/users` path). Previously a study admin couldn't add anyone who
  wasn't already allowlisted by a superuser. `MemberCreate` gains an optional `name`.

## [0.3.1] — 2026-06-21

### Changed

- **Provider is now a per-study, immutable attribute.** Each study declares its wearable
  (`fitbit_gh` or `garmin`) at creation; it cannot be changed afterward. All of a study's subjects
  inherit that provider, so a subject has exactly one device registration. Creating a subject now
  **auto-creates** its registration (and entry code) using the study's provider — no per-subject
  device choice. `add_registration` only re-issues a code for the study's provider (rejects a
  mismatched one). Migration `0015` adds `studies.provider` with a `server_default` of `fitbit_gh`,
  **grandfathering all existing studies to Fitbit**. Console: studies get a required Device selector
  at creation (shown read-only after) + a Device column; the subject form drops the device dropdown.

## [0.3.0] — 2026-06-21

### Added

- **Garmin provider (OAuth 1.0a + push webhooks).** The second provider, alongside
  Fitbit-via-Google-Health. Garmin differs fundamentally: OAuth **1.0a** (3-legged, HMAC-signed,
  **no refresh tokens**, tokens don't expire), and **push webhooks that carry the actual values**
  (so there's **no pull/consolidation** step and **no subscription API**). New
  `app/providers/garmin.py` (request-token → authorize → access-token via `requests-oauthlib`;
  `fetch_user_id` resolves the Garmin `userId` identity key at callback; `deregister` for
  revocation). New `app/garmin_ingest.py` lands each push raw in `health_data`, resolves the
  account by `userId`, and **merges** the mapped metrics into `daily_health` /
  `health_data_points` per-datatype and idempotently (`dailies` → steps/distance/calories/floors/
  HR + intraday HR from `timeOffsetHeartRateSamples`; `sleeps` → sleep + stages; `hrv` → hrv_ms;
  everything else landed raw). New parameterized webhook `POST /webhooks/garmin/{datatype}`
  (always 200; `deregistrations` → `mark_revoked`). Shared `daily_health`/`points` write helpers
  factored into `app/dailywrite.py` so the Google and Garmin paths write identically.
- **Per-device enrollment (entry code moved to the registration).** A subject can now register
  **both** a Fitbit and a Garmin device; the unique `entry_code` moved from `subjects` onto
  `provider_accounts` (one per device), created by staff up front. Migration `0014` back-fills
  every existing `subjects.entry_code` onto that subject's `fitbit_gh` account (production-safe;
  no code lost) and relaxes `subjects.entry_code` to nullable. New
  `POST/DELETE /admin/subjects/{id}/registrations`; `/enroll` looks up the code, customizes the
  message, and launches that provider's OAuth (one `/enroll/callback` dispatches Google vs Garmin
  by the params present). The console shows **one subject row with a device chip per registration**
  (provider + entry code + linked/stale), an "Add device" control, and a provider-tagged daily
  view / export.

## [0.2.0] — 2026-06-18

### Added

- **SpO2 (blood oxygen) ingestion.** Like HR/HRV, SpO2 is **not webhook-subscribable**, so the
  daily summary is pulled during consolidation via a day-filtered `daily-oxygen-saturation` list
  (`daily_oxygen_saturation.date`). The headline average lands in the new `daily_health.spo2_avg`
  typed column; lower/upper bound % stay in `daily_health.metrics.spo2`. Surfaced in the console
  daily table (`SpO₂` column), JSON export, and daily CSV. Migration `0009`.
- **Paired-device snapshots (battery / model / last sync).** Device info is **profile data, not a
  dataType** — fetched from the HealthProfile endpoint `GET /users/me/pairedDevices` with the
  subject's token. One `paired_devices` row per (account, device) holds `device_type`
  (TRACKER|SCALE), `device_version`, `battery_level`, `battery_status` (High|Medium|Low|Empty),
  `last_sync_time`, `mac_address`, `features[]`. Refreshed during consolidation of a *recent* day
  only (battery is a "now" value; avoids hammering the endpoint on long backfills). New
  `GET /admin/subjects/{id}/devices`, included in subject export, and shown as a "Paired devices"
  panel in the console. Migration `0009`.
- **Required OAuth scopes.** Both features need scopes on the subject grant
  (`GOOGLE_HEALTH_SCOPES`): SpO2 → `…/auth/googlehealth.health_metrics_and_measurements.readonly`;
  paired devices → `…/auth/googlehealth.settings.readonly`. Add these in the Cloud Console "Data
  Access" page and to `GOOGLE_HEALTH_SCOPES`, then **re-enroll** subjects so the new scopes are
  granted. Both pulls are fault-isolated, so a missing scope degrades gracefully (the metric/panel
  is just empty) rather than failing the day.
- **Intraday HRV + SpO2 ingestion (per-study opt-in).** Two new `studies` flags
  (`ingest_intraday_hrv`, `ingest_intraday_spo2`, migration `0010`) alongside the existing
  `ingest_intraday_hr`. Both are **sample-time** dataTypes (`heart-rate-variability` → RMSSD ms;
  `oxygen-saturation` → percentage), pulled with a `sample_time.physical_time` UTC-window filter
  for the local day. They're sleep-period and low-frequency (tens of points/day), so unlike HR
  they're stored **raw** (no downsampling) as `heart_rate_variability` / `oxygen_saturation`
  points in `health_data_points` — visible in the day expansion + export; per-day counts in
  `daily_health.metrics.intraday`. Toggled from the Studies console ("Intraday ingestion").
  (Note: the API exposes only time-domain HRV — RMSSD, plus entropy/deep-sleep-RMSSD on the daily
  summary — **no LF/HF** frequency-domain power.)
- **Subjects-list health indicators + sorting.** The study Subjects table is now sortable by
  Label / Status / Linked (default: linked-first) and shows a per-subject summary computed in
  `list_subjects`: lowest **battery** across paired devices (red when Low/Empty or ≤20%), a 7-pip
  **Data (7d)** coverage bar (`n/7` days with data), and **Latest** data date — with a "stale"
  badge for linked, in-window subjects with no data in 2+ days. `SubjectStatusOut` gains
  `battery_level/status/low`, `last_data_date`, `days_with_data_7`, `data_stale`. The paired-device
  panel also re-fetches after a Pull + consolidate.

### Infrastructure

- **Host + DB migration:** moved from `omnikog.asuscomm.com` to `lnpitask.umn.edu` and
  switched from the bundled `mariadb:11` compose service to an external MariaDB at
  `cnc3.med.umn.edu`. The `db` service + `db_data` volume are gone from `docker-compose.yml`;
  backend/scheduler get `DATABASE_URL` from `.env` only. `entrypoint.sh`'s wait-for-db loop
  now targets `DB_WAIT_HOST`/`DB_WAIT_PORT` (set in `.env`). Host nginx on lnpitask gained
  three locations under the existing TLS server block: `/wearable/` → frontend:8020
  (prefix stripped), `/enroll` → backend:8010, `/webhooks/google-health` → backend:8010.
  Public redirect URIs (`OAUTH_REDIRECT_URI`, `WEBHOOK_PUBLIC_URL`,
  `RESEARCHER_OAUTH_REDIRECT_URI`) updated; Google Cloud Console redirect URIs and the
  Tier-1 webhook subscriber were re-registered against the new host. Started fresh on cnc3
  (no data migrated from the old container).
- **Prod runtime is Podman Quadlets, not compose.** `lnpitask` doesn't ship
  `podman-compose`; the three services now run as systemd quadlet units
  (`wearable.network`, `wearable-backend.container`, `wearable-scheduler.container`,
  `wearable-frontend.container`) checked in at `deploy/quadlet/` and installed to
  `/etc/containers/systemd/`. Backend takes `NetworkAlias=backend` so the frontend's
  internal nginx `proxy_pass http://backend:8000` resolves unchanged. Auto-start on boot,
  `systemctl restart wearable-backend.service` for restarts, `journalctl -u …` for logs.
  `docker-compose.yml` is kept for local dev only.
- **Outbound HTTP egress through corporate proxy.** lnpitask sits behind
  `http://ctsigate.ahc.umn.edu:3128`; without `HTTPS_PROXY`/`HTTP_PROXY` the backend's
  httpx + google-auth calls to `oauth2.googleapis.com` and `health.googleapis.com` fail
  with `[Errno 101] Network is unreachable` (broke researcher OAuth callback with a 500
  on first attempt). Added `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` (`.med.umn.edu`,
  `.ahc.umn.edu`, cnc3, loopback) to `.env`; the quadlet's `EnvironmentFile=` passes them
  through to the container as a `--env-file`. Also affects `podman build` itself — `sudo`
  strips proxy env, so image builds need `sudo -E podman build`.
- **Frontend nginx re-resolves `backend` per request.** With nginx's default behavior of
  resolving `proxy_pass` hostnames once at config-parse time, any backend container
  restart (which assigns a new IP on the user-defined network) caused permanent 502s on
  the SPA until the frontend was bounced too. Fixed by adding `resolver <ns> valid=10s`
  and a variable in `proxy_pass`; the nameserver IP is read from `/etc/resolv.conf` at
  container start by `frontend/30-set-resolver.sh` (runs from `/docker-entrypoint.d/`).
  Verified: bouncing the backend now auto-recovers in ~3s without touching the frontend.
- **nginx proxy timeouts bumped to 300s on the consolidate path.** On-demand
  `POST /admin/subjects/{id}/consolidate` is synchronous and iterates day-by-day through
  Google Health API calls; for a multi-week range through the corp proxy this easily
  exceeds nginx's default 60s `proxy_read_timeout` and returns 504 even while the backend
  is still successfully completing the work. Added `proxy_connect_timeout 10s`,
  `proxy_send_timeout 300s`, `proxy_read_timeout 300s` to both `/wearable/` on the host
  nginx and `/admin/` in `frontend/nginx.conf`. **Future-proofing note:** 300s covers the
  current 120-day range cap (`backend/app/routers/admin.py`) at reasonable Google +
  proxy latency. If the cap goes up or upstream latency increases, this ceiling will
  bite again — the proper fix at that point is converting the endpoint to FastAPI
  `BackgroundTasks` + a job-status endpoint and polling from the console.

### Fixes

- **Consolidation 500 on duplicate intraday `point_key` (within a single pull).** On-demand
  Pull / consolidation returned a 500 (`IntegrityError 1062 … uq_hdp_acct_dt_key`) when a
  day's pulled dataPoints contained two points that collapse to the same
  `(provider_account_id, datatype, point_key)` — e.g. two `name`-less step points sharing a
  start minute (`steps|2026-06-01T23:26:00`), or overlapping points returned across pages by
  the unfiltered newest-first list path. The `SessionLocal` is `autoflush=False`, so the
  find-or-create `SELECT` in `_upsert_point` / `_upsert_hr_bucket` couldn't see rows
  `db.add()`-ed earlier in the *same* run; the second occurrence was added as a new row and
  the unique constraint failed at `commit()`. (Cross-run re-pulls were always fine — committed
  rows are visible.) Fix: `db.flush()` immediately after adding a new point row so a later
  same-run duplicate finds it and updates instead of re-inserting. Consolidation is now truly
  idempotent within a run, not just across runs.

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
  **Public deployment:** served at `https://lnpitask.umn.edu/wearable/` — the SPA is built
  with Vite `base: /wearable/` and prefixes its API calls, and the host nginx strips the prefix
  to the frontend container (so the container is unchanged). Host nginx snippet (not in repo):
  `location /wearable/ { proxy_pass http://127.0.0.1:8020/; }` (trailing slash strips the prefix).
- **UMN-branded redesign** — the console look & feel now follows the chan_cras CRMS app with
  University of Minnesota branding (maroon `#7A0019` / gold `#FFCC33`). Stack: **Tailwind CSS v4**
  (`@theme` tokens) + **lucide-react** icons; Open Sans body + Poppins headings; **class-based
  dark mode** (header toggle, persisted). Layout: collapsible maroon **sidebar** (logo + icon nav
  + user footer) + white/dark header (page title + study selector + dark toggle); multi-section
  nav (Studies / Subjects / Researchers / About) driven by a `currentView` state (no router).
  `App.jsx` split into `Layout` + `views/` + `ui.jsx`/`lib.js`; `styles.css` retired. Backend +
  `api.js` unchanged. Plan: `docs/ui-redesign-plan.md`.
- **Enrollment page** — the server-rendered `/enroll` is UMN-branded with participant info: a
  header band, thank-you/intro, a "what happens next" 3-step explainer (enter code → Google
  sign-in → approve sharing activity/sleep/heart-rate), and a voluntary-participation /
  how-to-withdraw note; matching success/error pages.
- **Console data views + export** — clicking a subject's daily row **expands to its intraday
  points** (`GET /admin/subjects/{id}/daily/{day}/points`), grouped by datatype with local
  start–end times and values; **sleep** shows its stage architecture (AWAKE/LIGHT/DEEP/REM
  minutes — a day summary from `metrics.sleep` plus per-session breakdowns). **Export**
  (`GET /admin/subjects/{id}/export?start=&end=`, study-view) with From/To range and three
  formats: **JSON** (each day's summary with intraday points + sleep stages nested), **CSV
  daily** (one row/day incl. stage-minute totals), **CSV intraday points** (one row/point). CSV
  is generated client-side from the export JSON. **Whole-study export**
  (`GET /admin/studies/{id}/export`) does the same across every subject at once (JSON nests
  `subjects[]`; the CSVs prefix `subject_label`/`entry_code` columns). Small UX: add-forms
  disable until an email is typed; duplicate-researcher returns a clear "&lt;email&gt; is
  already a researcher".
- **Subject edit + data-collection window** — subjects gain an editable **Study ID**
  (`subjects.participant_id`, distinct from the `study_id` FK; `subject_label` is the
  participant's Google/Fitbit account) and an optional inclusive **collection window**
  (`collection_start`/`collection_end`, subject-local days; either bound nullable =
  unbounded). New `PATCH /admin/subjects/{id}` (study-admin; `exclude_unset` so a present-null
  clears a field, validates end ≥ start); `SubjectCreate`/`SubjectOut` carry the new fields.
  The window **hard-clamps every pull path** — enforced once at the `consolidate_day()` choke
  point, so real-time webhook, nightly safety-net, and on-demand backfill all skip
  out-of-window days (`consolidation_state.status = "skipped"`) **before** any token refresh
  or Google API call. Console: a per-row **Edit** button (pencil, next to delete/lock; works
  on linked subjects too) opens a modal (Study ID, label, start→end with live end ≥ start
  check); Subjects table gains Study ID + Collection-window columns; SubjectDetail shows the
  window as a header badge and pre-fills the Pull + consolidate pickers to it. Saving the
  window stores bounds only — backfill still runs via the manual pull or the nightly job.
  Migration `0008`.
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

### Fixed

- **Frontend `Failed to resolve module specifier "scheduler"`** — a flaky `npm install` in the
  frontend image build dropped `scheduler` (react-dom's runtime dep); Rollup leaves an
  unresolvable bare import external (warns, doesn't fail), so the shipped bundle carried a bare
  `import "scheduler"` that the browser can't resolve. Pinned the build with a committed
  `package-lock.json` + `npm ci` (`frontend/Dockerfile`) so image builds are reproducible.

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
- **Active Zone Minutes available as a daily rollup (verified 2026-06-18).** dataType
  `active-zone-minutes` → `dailyRollUp` returns `activeZoneMinutes` with `sumInCardioHeartZone` /
  `sumInPeakHeartZone` / `sumInFatBurnHeartZone` (string ints; real data, e.g. 06-05 = 48/4/79).
  It is **pull-only** (not webhook-subscribable) and **not listable** — an intraday `list` filter
  returns `400 INVALID_DATA_POINT_FILTER_DATA_TYPE_RESTRICTION`, so it's a daily summary only.
  Stored as `daily_health.azm_total` (Fitbit-weighted: fat-burn ×1 + cardio/peak ×2) with the
  per-zone breakdown in `metrics.active_zone_minutes`.
- **Active minutes by activity level available as a daily rollup (verified 2026-06-18).** dataType
  `active-minutes` → `dailyRollUp` returns `activeMinutes.activeMinutesRollupByActivityLevel`, a
  list of `{activityLevel: LIGHT|MODERATE|VIGOROUS, activeMinutesSum}` (string ints; e.g. 06-05 =
  368/25/5). Pull-only daily rollup; a multi-day range errors `INVALID_ROLLUP_QUERY_DURATION`, so
  it's pulled per day like the others. Stored as `daily_health.mvpa_minutes` (moderate + vigorous,
  the public-health MVPA standard) with the per-level breakdown in `metrics.active_minutes`.
- **`dailyRollUp` is daily-granularity only (verified 2026-06-18).** The
  `dataPoints:dailyRollUp` request schema accepts **only** `range` — probing `bucketByTime`
  (Google-Fit-style) and `period` both return `400 INVALID_ARGUMENT` *"Cannot find field"*. A
  multi-day `range` returns **one `rollupDataPoint` per civil day** (3-day range → 3 points;
  HR → per-day avg/min/max). So there is **no single-call sub-daily (hourly/5-min) bucketing** —
  intraday curves still require pulling raw points + client-side downsampling. The civil bounds
  *do* accept a `time` component, so an **arbitrary time window is summed** (06-01 `00:00–06:00`
  → `countSum 355`), but only one aggregate per call — emulating N intraday buckets would cost N
  calls/day, far more than one `list` page. Confirmed rollup == stored daily total (steps
  `countSum 9264` == the day's `daily_health.steps`). Implication: rollup's storage lever is
  *dropping* intraday step/distance points (keep the daily total only), not finer buckets.
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
- Per-session sleep hypnogram view; HR sparkline in the day expansion.
- Production Restricted-scope security review (CASA) for non-test users.
