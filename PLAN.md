# Plan: Google Health API — Milestone 1 (Fitbit OAuth2 end-to-end)

## Context

`googlehealth/` is a greenfield project (only `Description.md` + symlinks to three prior
apps). The goal is to register Fitbit users against the **new Google Health API** (the
successor to the legacy Fitbit Web API, which sunsets Sept 2026) so they can share data
with a server. The legacy Fitbit auth (OAuth2/PKCE against `fitbit.com`) is replaced by
**Google OAuth 2.0** (Cloud Console client), and pull-based polling is replaced by a
**two-tier webhook subscription** model.

The full product (per `Description.md`) is large: React + FastAPI + MariaDB, Google-login
auth with an allowlist + RBAC, study/subject management, **both** Fitbit (Google Health,
OAuth2) and Garmin (OAuth1a, push webhooks), plus data review/download. This plan covers
**only Milestone 1**, agreed with the user:

- **Architecture:** one app, per-provider OAuth modules (not two separate apps).
- **Milestone 1 scope:** Fitbit/Google-Health OAuth end-to-end — subject enrollment by
  code → Google OAuth2 token storage → subscription registration → webhook receiver.
  Minimal researcher UI. **Researcher Google-login auth + RBAC are deferred** to a later
  foundation milestone (researcher endpoints are local/unprotected for now, flagged).
- **Schema:** fresh normalized schema (not the legacy flat `accounts`/`garmindata`).

Designed so Garmin and the auth/RBAC layer slot in later without rework. Reusable patterns
from prior art: PKCE OAuth flow in [fitbitreg/fitbit_flask.py](fitbitreg/fitbit_flask.py)
(lines 74–189); entry-code enrollment + "always return 200" webhook handling in
[garminrec/app_usercode.py](garminrec/app_usercode.py).

## New Google Health API facts (grounding)

- **Authorization endpoint:** `https://accounts.google.com/o/oauth2/v2/auth`
  (params: `client_id`, `redirect_uri`, `scope`, `code_challenge`+`S256`, `state`,
  `access_type=offline`, `prompt=consent` to force a refresh token).
- **Token endpoint:** `https://oauth2.googleapis.com/token`.
- **Data read:** `GET https://health.googleapis.com/v4/users/*/dataTypes/*/dataPoints`.
- **Subscriptions (two-tier):** register a subscriber endpoint once per project —
  `POST /v4/projects/{project}/subscribers` — then per-user
  `POST /v4/projects/{project}/subscribers/{subscriber}/subscriptions`
  (DELETE/PATCH/LIST for lifecycle).
- Scopes are **Restricted** (need Google security review for production); during dev the
  OAuth client runs in testing mode capped at 100 manually-added test users. Exact scope
  strings come from the Cloud Console "Data Access" page — to be filled into config.

## Target layout (monorepo at project root)

```
googlehealth/
  docker-compose.yml          # mariadb + backend (+ frontend dev)
  .env / .env.sample
  backend/
    pyproject.toml
    app/
      main.py                 # FastAPI app, mounts routers
      config.py               # pydantic-settings from env
      db.py                   # SQLAlchemy 2.0 engine + session dependency
      models.py               # ORM (fresh schema, see below)
      schemas.py              # pydantic request/response models
      crypto.py               # token encryption at rest (Fernet)
      providers/
        base.py               # Provider protocol (start_auth, exchange, refresh, subscribe)
        fitbit_gh.py          # Google Health OAuth2 + PKCE + subscription calls
      routers/
        enroll.py             # subject-facing: code -> auth -> callback
        webhooks.py           # subscriber receiver endpoint(s)
        admin.py              # minimal: create study, create subject (-> entry code)
      alembic/                # migrations
  frontend/                   # minimal React (Vite): enroll page + tiny researcher page
```

## Fresh schema (`app/models.py`)

Designed for the full product; Milestone 1 exercises the starred tables.

- `users` — researchers/admins: `id, google_sub, email, name, is_superuser, created_at`
  (table created now, populated later when auth lands).
- `studies`* — `id, name, description, created_by_user_id, created_at`.
- `subjects`* — `id, study_id(fk), subject_label, entry_code(unique), status, created_at`.
- `provider_accounts`* — one row per subject+provider:
  `id, subject_id(fk), provider('fitbit_gh'|'garmin'), state, code_verifier,
   access_token(enc), refresh_token(enc), token_expires_at, scope, provider_user_id,
   registered(bool), raw_token_json, created_at, updated_at`.
- `subscriptions`* — `id, provider_account_id(fk), subscriber_id, provider_subscription_id,
   data_types(json), status, created_at`.
- `health_data`* — raw webhook landing zone:
  `id, provider_account_id(fk, nullable), provider, datatype, start_time, payload(json),
   received_at`.
- (Deferred to auth milestone: `roles`, `study_memberships`, `permissions`.)

Tokens encrypted at rest via `crypto.py` (Fernet key in env) — improvement over prior
plaintext storage.

## Flow to implement

**Enrollment + OAuth ([enroll.py](backend/app/routers/enroll.py), patterned on fitbitreg lines 74–189):**
1. `GET /enroll` → React form; subject submits `entry_code`.
2. `POST /enroll/start` → validate code (`subjects` exists, not yet `registered`).
   Generate PKCE verifier/challenge + random `state`; upsert a `provider_accounts` row
   (provider=`fitbit_gh`) storing `state` + `code_verifier`; redirect to Google auth URL.
3. `GET /enroll/callback?code&state` → look up provider_account by `state`; POST to
   `oauth2.googleapis.com/token` with `client_id/secret`, `code`, `code_verifier`,
   `redirect_uri`. Store `access_token`/`refresh_token`/`expires_at`/`scope`/`provider_user_id`,
   set `registered=True`. Render success page.
4. After token: ensure project subscriber is registered (idempotent, cached), then
   `POST .../subscriptions` for this user; persist into `subscriptions`.

**Token refresh** (`providers/fitbit_gh.py`): helper refreshes via `refresh_token` grant
when `token_expires_at` is near; updates stored tokens. Reused before any data read.

**Webhook receiver ([webhooks.py](backend/app/routers/webhooks.py), patterned on garminrec):**
- `POST /webhooks/google-health` — the registered subscriber endpoint. Parse notification,
  insert into `health_data`, **always return 200 fast** so Google doesn't disable the
  subscription. Handle the user-deletion/deregistration notification → mark
  `provider_account.registered=False`. Signature verification: add per Google's webhook
  auth scheme (to confirm in reference docs) — stub with a TODO + config secret.

**Minimal researcher UI / admin ([admin.py](backend/app/routers/admin.py)):**
- `POST /admin/studies`, `POST /admin/studies/{id}/subjects` (auto-generates `entry_code`),
  `GET /admin/studies/{id}/subjects` (list codes + registration status). Unprotected for
  now (flagged TODO: gate behind Google login in the auth milestone).
- React: one researcher page (create study, add subjects, see codes/status) + the subject
  enroll page. Keep minimal.

## Key files to create

- `backend/app/providers/fitbit_gh.py` — the core new integration (auth URL build, token
  exchange/refresh, subscriber + subscription API calls).
- `backend/app/models.py`, `backend/app/db.py`, `backend/app/config.py`,
  `backend/app/crypto.py`.
- `backend/app/routers/{enroll,webhooks,admin}.py`, `backend/app/main.py`.
- `docker-compose.yml`, `.env.sample`, `backend/pyproject.toml`, `frontend/` (Vite scaffold).
- Alembic initial migration.

Config (`.env`): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_HEALTH_SCOPES`,
`GH_PROJECT_ID`, `OAUTH_REDIRECT_URI`, `WEBHOOK_PUBLIC_URL`, `FERNET_KEY`, DB creds.

## Verification (end-to-end)

1. `docker compose up` (MariaDB + backend); run alembic migration; backend healthcheck OK.
2. Create a study + subject via `POST /admin/...`; confirm an `entry_code` is returned and
   a `subjects` row exists.
3. In Google Cloud Console: enable Google Health API, create a Web OAuth client, add the
   callback as an authorized redirect URI, add your Google account as a test user, select
   the Health scopes. Put client id/secret + scopes in `.env`.
4. Walk the enroll flow in the browser with the test user → confirm `provider_accounts` row
   has encrypted tokens, `registered=True`, and a `subscriptions` row was created (verify
   subscription via the LIST endpoint).
5. Expose the webhook (ngrok / `WEBHOOK_PUBLIC_URL`) and trigger or simulate a notification
   POST to `/webhooks/google-health`; assert a `health_data` row lands and the endpoint
   returns 200. Test the deregistration notification flips `registered=False`.
6. Refresh path: force-expire `token_expires_at`, call a data read, confirm tokens refresh
   and a `dataPoints` read succeeds.

## Deferred (later milestones, not in this plan)

- Garmin (OAuth1a + push-webhook endpoints), reusing `garminrec/app_usercode.py` patterns
  under `providers/garmin.py` and additional `/webhooks/garmin/*` routes.
- Google-login researcher auth (2FA) with allowlist; RBAC (super-admin → study-admin →
  permissions); `roles`/`study_memberships` tables.
- Data review + download UI.
