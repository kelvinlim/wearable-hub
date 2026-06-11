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

## Cloud project & account (decision)

Use the **institutional umn.edu org**, not a personal Google account, for everything that
touches real subject data. Current project: **`fitbitdata-499001`** (project number
`569496656627`), under `umn.edu`.

- **Why umn.edu over a personal gmail:** (1) IRB/data governance — identifiable subject
  health data must sit under institutional control, not a personal account; (2) continuity —
  a personal-account project orphans the OAuth client + subscriptions on staff turnover;
  (3) the Restricted-scope **production security review (CASA)** is far more likely to pass
  for a verified organization than for a personal gmail requesting Restricted *health*
  scopes; (4) billing belongs on institutional, not personal, accounts.
- **Dev consent screen:** External / Testing, with `lim.kelvino@gmail.com` + a teammate
  added as **test users** (≤100 in testing mode).
- **Risk to verify (umn.edu Workspace may lock these down):** that you can (a) set the
  consent screen to **External**, (b) add **non-UMN test users** (subjects likely use
  personal Google accounts), and (c) create OAuth clients with **Restricted scopes** /
  publish externally. **Fallback if blocked:** request a UMN OIT exception — do *not* fall
  back to a personal project, which only defers the governance + production-review problems.

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
4. After token: look up the project subscriber (registered out-of-band via the one-time
   admin path — see finding below); if present, `POST .../subscriptions` for this user
   (Tier-2 only) and persist into `subscriptions`. Do NOT register the subscriber here.

**Token refresh** (`providers/fitbit_gh.py`): helper refreshes via `refresh_token` grant
when `token_expires_at` is near; updates stored tokens. Reused before any data read.

> **Finding (2026-06-11) — subscriber registration is a PROJECT op, not a user op.**
> The first live enrollment succeeded (token exchange, encrypted storage, refresh token,
> `provider_user_id` from the id_token all verified). But the inline Tier-1
> `POST /v4/projects/{project}/subscribers` call returned **403** because it was made with
> the *research subject's* user OAuth token — a subject's token is never authorized for
> project-level operations. Correct model:
> - **Tier 1 (once per project, admin/service-account):** register the project subscriber
>   (webhook endpoint). Uses **project credentials** (a service account with the right IAM
>   role), idempotent, run out-of-band — NOT during enrollment.
> - **Tier 2 (per enrollment):** create the per-user subscription referencing the
>   already-registered subscriber.
>
> So the enroll callback must do Tier-2 only; Tier-1 moves to a one-time admin path. The
> subscriber id is persisted (`project_subscribers` table) so Tier-2 can reference it.
> The exact subscription request/response shapes and which credential Tier-2 uses are still
> unverified against Google's docs — flagged TODO in code (current code assumes project
> credentials for both, with the user identified by `provider_user_id` in the body).

> **Finding (2026-06-11) — Tier-1 subscriber registration now works end-to-end.** ✅
> Service-account key `secrets/health-sa.json` (`health-subscriber@fitbitdata-499001`)
> mounted read-only at `/secrets` (compose needs `:z` for SELinux on el8) and pointed at by
> `GH_SA_CREDENTIALS_FILE`. `POST /admin/subscriber` mints an SA token and registers the
> project subscriber; `GET /admin/subscriber` confirms it. Verified facts:
> - **Path uses the project NUMBER** (`projects/569496656627/...`), not the ID.
> - **`subscriberId` is a query param**; pattern `[a-z0-9-]{4,36}` (our `wearable-hub` ok).
> - **`endpointAuthorization.secret` is the full header value** — register `"Bearer <secret>"`;
>   the webhook compares the inbound `Authorization` header against it verbatim. Google's
>   registration-time verification probes the endpoint twice (authorized→200, unauth→401);
>   our `/webhooks/google-health` already satisfies both, so registration verifies cleanly.
> - **Only a fixed set of dataTypes is webhook-subscribable** (a bad one → bare 400
>   INVALID_ARGUMENT, no field detail). Verified subscribable: `steps, sleep, distance,
>   calories, weight, height, floors, exercise, altitude`. **NOT subscribable** (any
>   spelling): `heart_rate`/HRV/resting-HR, SpO2, VO2 max, active(-zone) minutes, body fat,
>   respiratory rate — these are **pull-only** via the dataPoints read, despite appearing in
>   the general data-types docs. `fitbit_gh.SUBSCRIBABLE_DATA_TYPES` guards config with a
>   clear error. Registered set (user choice): all 9 subscribable types.
> - **create can return a long-running Operation**, not the subscriber inline (async endpoint
>   verification on a fresh register). There is **no GET-by-id route** (returns a Google HTML
>   404) — only LIST. So `get_subscriber()` LISTs and matches the trailing id; the admin
>   handler reconciles the DB row from that, not from the create response.
> - **Endpoint is idempotent**: re-running treats Google's `409 ALREADY_EXISTS` as success
>   and reconciles from the live resource.
>
> Still Tier-2 (per-user subscription) shapes are unverified — next up.
>
> **Dev loop note:** the backend image bakes source (`COPY . .`, no reload/mount), so code
> changes need `podman-compose build backend && up -d --force-recreate backend`, and the
> entrypoint waits on the DB + runs migrations (~5–15s) before serving.

> **Finding (2026-06-11) — Tier-2 characterized; refresh + pull read work; AUTOMATIC needs
> a fresh consent to verify.** Verified live against the enrolled subject (acct id=2):
> - **Refresh works** — refreshing the expired access token via the stored refresh token
>   succeeds. **Pull read works** — `GET /v4/users/me/dataTypes/steps/dataPoints` with the
>   subject token returns real Fitbit data (Charge 6, live intervals). So the data plane is
>   reachable end-to-end via pull, independent of webhooks.
> - **Tier-2 shape (verified):** `POST /v4/projects/{NUMBER}/subscribers/{sub}/subscriptions`,
>   body = the Subscription resource: `{"user":"users/{healthUserId}","dataTypes":[...]}`.
>   `create_subscription()`/`list_subscriptions()` corrected to this (were using project ID +
>   a bogus `userId` field).
> - **Blocker 1 — healthUserId:** the `user` field needs the public **healthUserId**, which
>   is NOT the OAuth `sub` (`provider_user_id`) — Google rejects the sub with "Invalid user
>   ID segment", and the id_token carries no health id (standard OIDC claims only).
>   healthUserId is only obtainable from a webhook payload or an auto-created subscription's
>   `user` field.
> - **Blocker 2 — policy:** manual `create` requires `subscriptionCreatePolicy=MANUAL`. We
>   registered **AUTOMATIC**, under which Google subscribes on consent and manual create is
>   rejected. **AUTOMATIC is not retroactive** — the enrolled subject (consented before the
>   subscriber existed) has no subscription; LIST is empty.
> - **To finish Tier-2:** either (A) keep AUTOMATIC and do one *fresh* browser enrollment
>   with a test Google user, then confirm a subscription appears in LIST and a webhook lands
>   in `health_data` — and read healthUserId from the subscription's `user` field to fix
>   account linking; or (B) switch to MANUAL, resolve+store healthUserId, then call
>   `create_subscription`. Recommend (A) to match the chosen AUTOMATIC config.

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
