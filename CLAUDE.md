# CLAUDE.md

Working notes for Claude Code in this repo. See [README.md](README.md) for the product
overview and [PLAN.md](PLAN.md) for the current implementation plan.

## What this project is

A full-stack app to register research subjects' wearables against the **new Google Health
API** (Fitbit's successor; legacy Fitbit Web API sunsets Sept 2026) and ingest their data.
Stack: **FastAPI + React (Vite) + MariaDB**, Docker Compose. One backend app with
**per-provider OAuth modules** (Fitbit-via-Google-Health now; Garmin later).

## Architecture decisions (locked)

- **One app, per-provider modules** — not separate Fitbit/Garmin apps. The researcher UI,
  study/subject model, webhook ingestion, and DB are unified; only the OAuth layer differs
  per provider (`app/providers/fitbit_gh.py`, later `app/providers/garmin.py`).
- **Fresh normalized schema** — do **not** reuse the legacy flat `accounts`/`garmindata`
  tables from `garmin_django`. New tables: `users, studies, subjects, provider_accounts,
  subscriptions, health_data` (+ `roles`/`study_memberships` when auth lands).
- **Tokens encrypted at rest** (Fernet, key in env) — an improvement over the prior
  plaintext storage.

## Provider differences that matter

- **Fitbit (Google Health API):** Google OAuth 2.0 + PKCE, **refresh tokens** (use
  `access_type=offline` + `prompt=consent`). Data via **two-tier subscriptions**: register
  a project subscriber once, then per-user subscriptions; data arrives by webhook.
- **Garmin (later):** OAuth **1.0a** — 3-legged, HMAC-signed, **no refresh tokens**, tokens
  don't expire. Data arrives via push webhooks (~16 POST endpoints). No subscription API;
  Garmin pushes once authorized.

## Conventions

- **Webhook handlers must always return 200 quickly**, even on internal error, so the
  provider doesn't disable the subscription. Do the work, swallow/log exceptions, return
  200. (Pattern from `garminrec/app_usercode.py`.) Land raw payloads in `health_data` and
  process async/later rather than inline.
- **Entry-code enrollment:** staff pre-create a `subjects` row with a unique `entry_code`;
  the subject registers by entering that code, which kicks off the provider OAuth flow.
  (Pattern from `garminrec` / `fitbitreg`.)
- **OAuth state** is persisted on the `provider_accounts` row (keyed by `state`), not in
  process globals — `garminrec` used module globals, which are not request-safe. Don't copy
  that.
- Store the full raw token response (`raw_token_json`) alongside the denormalized
  `access_token`/`refresh_token`/`token_expires_at` columns.
- Always refresh Fitbit tokens before a data read if near expiry.

## Google Health API reference

- Authorize: `https://accounts.google.com/o/oauth2/v2/auth`
- Token: `https://oauth2.googleapis.com/token`
- Data: `GET https://health.googleapis.com/v4/users/*/dataTypes/*/dataPoints`
- Subscriber: `POST /v4/projects/{project}/subscribers`
- Subscription: `POST /v4/projects/{project}/subscribers/{subscriber}/subscriptions`
  (PATCH/DELETE/LIST for lifecycle)
- Scopes are **Restricted** (prod needs Google security review); dev = testing mode, ≤100
  test users added manually in Cloud Console. Pull exact scope strings from the Cloud
  Console "Data Access" page into `GOOGLE_HEALTH_SCOPES`.

## Current status

Greenfield. Milestone 1 (Fitbit OAuth2 end-to-end) not yet scaffolded. When implementing,
follow the plan file and create: `backend/` (FastAPI), `frontend/` (Vite), `docker-compose.yml`,
`.env.sample`, alembic migrations.

## Prior art (symlinked, reference only — do not edit)

- `fitbitreg/` — legacy Fitbit OAuth2/PKCE (Flask); OAuth flow at `fitbit_flask.py:74-189`.
- `garminrec/` — Garmin OAuth1a + webhooks; canonical app is `app_usercode.py` + `db_code2.py`.
- `garmin_django/` — Django admin + token-refresh logic + legacy schema.
