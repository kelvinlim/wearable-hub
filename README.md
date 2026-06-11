# wearable-hub

Register research subjects' wearables and ingest their data through provider APIs.
Milestone 1 targets **Fitbit via the new Google Health API**, with **Garmin** to follow.
This replaces prior work built on the legacy Fitbit Web API, which Google sunsets in
**September 2026**.

## Why this exists

The legacy Fitbit Web API (OAuth2/PKCE against `fitbit.com`, pull-based polling) is being
turned down. Its successor, the **Google Health API**, changes two things fundamentally:

- **Auth** moves to **Google OAuth 2.0** (a Google Cloud Console client), not Fitbit auth.
- **Data delivery** moves to a **two-tier webhook subscription** model instead of polling.

This project is a fresh full-stack app that handles registration, token storage, and data
subscriptions for research subjects, with a researcher-facing UI for managing studies and
reviewing collected data.

## Target stack

- **Backend:** FastAPI (Python), one app with **per-provider OAuth modules**.
- **Frontend:** React (Vite).
- **Database:** MariaDB, a fresh normalized schema (users, studies, subjects,
  provider_accounts, subscriptions, health_data; RBAC tables to follow).
- **Deploy:** Docker Compose.

## Providers

| Provider | Auth | Data delivery |
|----------|------|---------------|
| **Fitbit** (via Google Health API) | Google OAuth 2.0 + PKCE, refresh tokens | Subscriber endpoint + per-user subscriptions → webhooks |
| **Garmin** (later) | OAuth **1.0a** (3-legged, HMAC-signed, no refresh) | Push webhooks (~16 POST endpoints) |

Garmin and Fitbit use genuinely different OAuth protocols, so each gets its own provider
module — but they share one study/subject model, one webhook ingestion path, one DB, and
one researcher UI.

## Roadmap

This is built in milestones (see [the implementation plan](#implementation-plan)):

1. **Milestone 1 (current): Fitbit / Google Health OAuth end-to-end** — subject enrollment
   by code → Google OAuth2 token storage → subscription registration → webhook receiver.
   Minimal researcher UI; researcher auth deferred.
2. **Foundation / auth** — Google-login for researchers (2FA) with an allowlist (only
   pre-entered users, must belong to a study); RBAC: super-admin → study-admin →
   per-permission grants (add subjects, download data).
3. **Garmin provider** — OAuth1a + push-webhook endpoints, reusing the `garminrec` patterns.
4. **Data review + download UI.**

## Key endpoints (Google Health API)

- Authorize: `https://accounts.google.com/o/oauth2/v2/auth`
- Token: `https://oauth2.googleapis.com/token`
- Read data: `GET https://health.googleapis.com/v4/users/*/dataTypes/*/dataPoints`
- Register subscriber: `POST /v4/projects/{project}/subscribers`
- Create subscription: `POST /v4/projects/{project}/subscribers/{subscriber}/subscriptions`

> Google Health scopes are **Restricted** — production access needs a Google security
> review. In dev, the OAuth client runs in testing mode (max 100 manually-added test users).

## Getting started

> Scaffolding is created during Milestone 1. Once present:

```bash
cp .env.sample .env        # fill in Google client id/secret, scopes, DB creds, FERNET_KEY
docker compose up          # MariaDB + backend
# run DB migrations, then visit the enroll + researcher pages
```

Required config: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_HEALTH_SCOPES`,
`GH_PROJECT_ID`, `OAUTH_REDIRECT_URI`, `WEBHOOK_PUBLIC_URL`, `FERNET_KEY`, and DB creds.

In Google Cloud Console: enable the Google Health API, create a **Web** OAuth client, add
your callback as an authorized redirect URI, add test users, and select the Health scopes.

## Prior art (reference, symlinked)

- `fitbitreg/` — legacy Fitbit OAuth2 + PKCE (Flask). Pattern source for the OAuth flow.
- `garminrec/` — Garmin OAuth1a + push-webhook ingestion (Flask). Pattern source for
  webhooks and entry-code enrollment.
- `garmin_django/` — Django admin + shared `accounts`/`garmindata` schema and token-refresh
  logic. Reference only; the new schema is fresh, not this one.

## Implementation plan

The detailed, current implementation plan lives at [PLAN.md](PLAN.md). See also
[CLAUDE.md](CLAUDE.md) for working notes and conventions.
