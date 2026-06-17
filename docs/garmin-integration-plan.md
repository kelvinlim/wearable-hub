# Garmin integration — plan

## Context

The hub was built "one app, per-provider OAuth modules" (CLAUDE.md). Fitbit-via-Google-Health is
done. Garmin is the second provider. Garmin differs from Google in three ways that shape the work:

- **OAuth 1.0a** (3-legged, HMAC-signed) — **no refresh tokens, tokens don't expire**; vs Google's
  OAuth2 + PKCE + refresh.
- **Push webhooks carry the actual values** (Garmin POSTs the data) — vs Google's value-less
  notifications that force a *pull* (`dailyRollUp`/`list`). **So Garmin skips the consolidation
  pull entirely.**
- **No subscription API** — Garmin pushes once a user authorizes; vs Google's two-tier
  subscriber/subscription model.

Prior art: `garminrec/app_usercode.py` (16 push endpoints, "always 200") + `garminrec/db_code2.py`
(legacy flat `accounts`/`garmindata`). We reuse the *patterns*, not the flat schema.

## How much of the existing structure is maintained → ~90–95%

**Reused as-is (no change):** `users`, `studies`, `study_memberships`, `subjects`,
`health_data` (raw landing zone — `provider` column already discriminates), `health_data_points`
(intraday), `daily_health` (same typed columns: steps/distance_m/calories/floors/sleep_minutes/
hr_avg/resting_hr/hrv_ms + `metrics` JSON), plus `security.py` auth/RBAC, the console's daily/
intraday/sleep/HR views and JSON/CSV export (all read `daily_health`/`health_data_points`, which
are provider-agnostic).

**`provider_accounts` — reused with NO migration.** Every Garmin field maps onto an existing
(nullable) column, repurposed with provider-appropriate semantics:

| column | Garmin use |
|---|---|
| `provider` | `'garmin'` |
| `state` | OAuth1a **request token** (transient handshake; cleared after callback) |
| `code_verifier` | OAuth1a **request-token secret** (transient; cleared after callback) |
| `access_token` (enc) | Garmin **user access token (UAT)** |
| `refresh_token` (enc) | Garmin **token secret** (repurposed — needed to sign Garmin API calls) |
| `token_expires_at` | `NULL` (Garmin tokens don't expire) |
| `provider_user_id` | Garmin **userId** (the webhook/identity key, analogous to Google's `sub`) |
| `health_user_id` | `NULL` (Google-only) |
| `raw_token_json` | full token response |
| `registered` | linked / deregistered |

**Not used by Garmin (Google-only, untouched):** `project_subscribers`, `subscriptions`,
`consolidation.py` pull logic, `consolidation_state` + the scheduler drain, and the Google
subscriber/sync admin endpoints. (Garmin re-aggregates locally from landed pushes — see below.)

## Decisions (recommended defaults — adjust if needed)

1. **Device choice → subject picks on the enroll page.** `/enroll` offers "Connect Fitbit" vs
   "Connect Garmin"; one entry code works for either. The `provider_account` is created with the
   chosen provider at `/enroll/start`. **No subject-table change.** (Alternatives: per-subject
   device field, or per-study flag.)
2. **v1 data scope → core metrics mapped to existing columns.** `dailies` (steps/distance/
   calories/floors/resting HR) + `sleeps` (minutes + stages) + `epochs` (intraday HR) + `hrv`
   → fill `daily_health`; land everything else raw in `health_data` for later.
3. **Backfill → push-only going forward** for v1 (matches `garminrec`). Garmin Backfill API is a
   later add.
4. **Garmin access** is a **prerequisite** (consumer key/secret + developer portal to register the
   webhook URLs). Build + unit-test against documented shapes; verify live once granted (same
   pattern as Google's test-user gating).

## New components

- **`backend/app/providers/garmin.py`** — `NAME = "garmin"`; OAuth1a request-token / access-token
  exchange and request signing (add **`requests-oauthlib`** to `pyproject.toml`); `fetch_user_id()`
  (Garmin Health `GET /wellness-api/rest/user/id`, OAuth1-signed) to populate `provider_user_id` at
  callback; `deregister()` (Garmin user-registration `DELETE`). Base URLs to confirm against Garmin
  docs: OAuth `connectapi.garmin.com/oauth-service/oauth/{request_token,access_token}`, authorize
  `connect.garmin.com/oauthConfirm`, data/identity `apis.garmin.com/wellness-api/rest/...`.
- **`backend/app/garmin_ingest.py`** — for an inbound push: land each item in `health_data`
  (`provider='garmin'`, `datatype`, `payload`), resolve the account by `provider_user_id`
  (Garmin `userId`), then **recompute the affected (account, local_date)** `daily_health` +
  `health_data_points` from the landed Garmin rows for that day (idempotent; re-pushes self-heal).
  Local date from `startTimeInSeconds + startTimeOffsetInSeconds` (or `calendarDate`). **Reuse the
  existing write helpers** `consolidation._upsert_daily` / `_upsert_point` (refactor them into a
  shared `app/dailywrite.py` so neither module imports the Google pull code).
- **`/webhooks/garmin/{datatype}`** (extend `routers/webhooks.py` or a new `garmin_webhooks.py`) —
  one parameterized handler for all ~16 push types; **always return 200 fast**, schedule
  aggregation via `BackgroundTasks`. A `{datatype}=="deregistrations"` push → `mark_revoked`.

## Modified components (small, additive)

- **`routers/enroll.py`** — provider dispatch. `GET /enroll`: two buttons (provider). `POST
  /enroll/start` takes `provider`; for Garmin → request-token + store on the account
  (`state`/`code_verifier`) + redirect to Garmin authorize. **One `/enroll/callback` dispatches by
  params present**: `code+state` → Google (existing); `oauth_token+oauth_verifier` → look up the
  account by `state==oauth_token`, do Garmin access-token exchange + `fetch_user_id` + store.
- **`routers/admin.py`** — generalize the `provider == fitbit_gh.NAME` account lookups (e.g.
  `_fitbit_account`) to "the subject's provider account(s)" so daily/points/export/revoke/delete
  work for Garmin; keep Google-only endpoints (subscriber/sync/consolidate) gated to fitbit.
- **`app/accounts.py`** — `revoke_account`: dispatch by `provider` (Google `revoke` vs Garmin
  `deregister`); `mark_revoked` already provider-agnostic.
- **`config.py`** — `garmin_consumer_key`, `garmin_consumer_secret`, `garmin_oauth_redirect_uri`,
  base URLs.
- **Frontend** — enroll page provider choice (server-rendered, already UMN-branded `_page`); a
  small provider badge on subject rows. Daily/intraday/export views need no change.

## Garmin → `daily_health` mapping (v1)

`dailies`: `steps`→steps, `distanceInMeters`→distance_m, `active+bmr Kilocalories`→calories,
`floorsClimbed`→floors, `restingHeartRateInBeatsPerMinute`→resting_hr, `averageHeartRate`→hr_avg,
stress/etc.→`metrics`. `sleeps`: total → sleep_minutes, deep/light/rem/awake → `metrics.sleep.stages`.
`hrvSummary`: avg → hrv_ms. `epochs`: intraday HR → `health_data_points` (datatype `heart_rate`).
Everything else → raw `health_data` + `metrics` passthrough.

## Verification

1. **Unit:** OAuth1a signing produces a valid `Authorization` header; payload→`daily_health`
   mapping for sample `dailies`/`sleeps`/`epochs`/`hrv` JSON (fixtures from `garminrec` shapes).
2. **Webhook:** POST sample Garmin payloads to `/webhooks/garmin/{datatype}` → assert 200, a
   `health_data` row lands, the account resolves by `userId`, and `daily_health` +
   `health_data_points` populate; re-POST → idempotent (no dupes, values self-heal).
3. **Deregistration:** POST `/webhooks/garmin/deregistrations` → account `registered=False`.
4. **Live (once credentials granted):** register the webhook URLs in the Garmin portal; walk a
   real `/enroll` → Garmin authorize → first pushes land → console shows the subject's daily data;
   confirm `provider_user_id` is set at callback via `fetch_user_id`.
5. Console: a Garmin subject appears with a provider badge; daily/intraday/export all work
   unchanged (shared `daily_health`/`health_data_points`).

## Prerequisites / open items

- Garmin Health API program approval + consumer key/secret; register the `{datatype}` webhook URLs
  (e.g. `https://lnpitask.umn.edu/webhooks/garmin/dailies`, …) and the OAuth callback in the
  Garmin developer portal.
- Confirm exact Garmin Health endpoint paths + the `user/id`, `backfill`, and `user/registration`
  routes against current Garmin docs (the legacy app used `connectapi.garmin.com` for OAuth only).
- Decide whether host nginx proxies `/webhooks/garmin/*` to the backend (like `/webhooks/google-health`).
