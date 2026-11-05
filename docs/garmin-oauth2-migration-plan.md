# Garmin Connect OAuth 1.0a → OAuth 2.0 migration plan

Audience: Kelvin Lim and wearable-hub maintainers. This is the implementation brief
for the Garmin auth cutover. **No migration code ships with this document** — it is
the plan only.

**Hard deadline:** Garmin retires OAuth 1.0 on **2026-12-31**. A Garmin device is
not available for live testing until **~2026-12-09 / 12-10**. Work that does not
need a watch (portal conversion, userId backfill, code + unit tests against
fixtures) should start before then.

**Repo:** this plan is for [`kelvinlim/wearable-hub`](https://github.com/kelvinlim/wearable-hub)
(the hub that already has `app/providers/garmin.py`, push ingest, and the
`/wearable/enroll` callback). It is not the older `garminrec` / `garmin_django`
apps.

Facts below are either (a) read from this repo as of the commit that added this
doc, or (b) taken from Garmin's 2026-07-27 partner email and the OAuth2 PKCE PDFs
on developerportal.garmin.com. **Endpoints and lifetimes not in those sources
are marked unknown — do not invent them at implementation time.**

---

## 1. Executive summary and timeline

Garmin Health in this hub is a **push** provider: subjects enroll with OAuth 1.0a,
Garmin POSTs values to `/webhooks/garmin/{datatype}`, and we match the account by
Garmin `userId` (`provider_accounts.provider_user_id`). OAuth 1.0a tokens do not
expire and there is no refresh path.

Garmin is converting Connect Developer Program apps to **OAuth 2.0**
(authorization-code + PKCE S256 + `client_secret` on the token call). After
2026-12-31, OAuth 1 request/access-token endpoints and HMAC-signed user calls
stop working. New enrolls, outbound deregister, historical backfill, and any
remaining OAuth1 user tokens must already be on OAuth2 by then.

Data delivery does **not** change model: we stay on **PUSH** (Starter-compatible).
The partner-email PING/PULL warning (honor callback URL; extra token param) is
**N/A** unless someone later switches the portal app to Ping. After an OAuth1
token expires post-exchange, Garmin says the "new PING/PUSH structure" takes
effect — PUSH bodies already identify the user by `userId`, which we already
use. We do **not** match pushes on the user access token.

| When | What |
|---|---|
| **Now (before a device is back)** | Email `connect-support@developer.garmin.com` with the consumer key(s) and ask them to convert the app. Confirm the new OAuth2 secret on the portal Apps tab. Inventory every `provider='garmin'` row: `registered`, `provider_user_id` nulls, token shape. Backfill any null `provider_user_id` **while OAuth1 `GET /user/id` still works**. Write the code + unit tests (no live watch required). |
| **~Dec 9–10, 2026** | Device available. Implement any remaining gaps, then device-test: new enroll, refresh, push, disconnect, and token-exchange of any leftover OAuth1 subject. |
| **Exchange window** | Once the app is OAuth2-enabled, batch `POST …/user/token-exchange` (OAuth1-signed, **≤200/min**). Each exchanged OAuth1 token stays valid **30 days**; after that, only the OAuth2 pair works. |
| **2026-12-31** | OAuth 1 retired. Un-exchanged OAuth1 subjects cannot backfill, deregister outbound, or re-authorize without a new OAuth2 enroll. Push matching still needs `userId`. |

**Success looks like:** every registered Garmin `provider_accounts` row has a
non-null `provider_user_id`, an OAuth2 access + rotating refresh token, a
populated `token_expires_at`, and all outbound Garmin calls use
`Authorization: Bearer`. New subjects enroll via `oauth2Confirm` + PKCE.
PUSH webhooks keep landing. Staff revoke still calls
`DELETE /user/registration` (now Bearer).

---

## 2. Current-state architecture (OAuth 1.0a)

### 2.1 What is live today

The Garmin module is already shipped (console v0.3.x onward): enroll, push
ingest, deregistration webhook, and on-demand backfill. CHANGELOG records
**live** backfill against Garmin (429 throttle, webhook-only types). Portal
URLs are registered under the `/wearable/` prefix. Remaining work called out
in [CLAUDE.md](../CLAUDE.md) is live device verification of the full enroll
loop and this OAuth2 cutover — not a greenfield Garmin port.

| Concern | Where it lives |
|---|---|
| OAuth1 3-legged + identity + deregister + backfill request | [`backend/app/providers/garmin.py`](../backend/app/providers/garmin.py) |
| Enroll start + callback dispatch | [`backend/app/routers/enroll.py`](../backend/app/routers/enroll.py) |
| Push ingest (match by `userId`, merge daily/points) | [`backend/app/garmin_ingest.py`](../backend/app/garmin_ingest.py) `resolve_account`, `ingest_push` |
| Webhook route (always 200) | [`backend/app/routers/webhooks.py`](../backend/app/routers/webhooks.py) `garmin_push`, `_garmin_deregister` |
| Historical re-push | [`backend/app/garmin_backfill.py`](../backend/app/garmin_backfill.py) + `garmin.request_backfill` |
| Staff revoke → provider deregister | [`backend/app/accounts.py`](../backend/app/accounts.py) `revoke_account` |
| Admin backfill / reprocess | [`backend/app/routers/admin.py`](../backend/app/routers/admin.py) `POST /admin/subjects/{id}/backfill`, `/reprocess` |
| Settings | [`backend/app/config.py`](../backend/app/config.py) + [`.env.sample`](../.env.sample) |
| Host routing | [`deploy/nginx/wearable-hub.conf`](../deploy/nginx/wearable-hub.conf) |
| Portal URL checklist | [`docs/garmin-portal-registration.md`](garmin-portal-registration.md) |
| Original Garmin design (OAuth1 assumptions) | [`docs/garmin-integration-plan.md`](garmin-integration-plan.md) |
| Partner email (saved) | [`docs/20260806_garmin_oauth1_to_oauth2.pdf`](20260806_garmin_oauth1_to_oauth2.pdf) |

Push ingest and daily writers (`app/dailywrite.py`) are **auth-agnostic**. They
do not need an OAuth rewrite. Tests:
[`backend/tests/test_garmin_ingest.py`](../backend/tests/test_garmin_ingest.py),
[`backend/tests/test_garmin_backfill.py`](../backend/tests/test_garmin_backfill.py).
There is **no** dedicated Garmin enroll/OAuth unit test today (Oura has
callback tests in `test_oura_ingest.py`; Garmin should get the same).

### 2.2 Config (OAuth1)

From `Settings` / `.env.sample`:

| Env / setting | Default in `config.py` | Role today |
|---|---|---|
| `GARMIN_CONSUMER_KEY` / `garmin_consumer_key` | `""` | OAuth1 consumer key |
| `GARMIN_CONSUMER_SECRET` / `garmin_consumer_secret` | `""` | OAuth1 consumer secret |
| `GARMIN_OAUTH_REDIRECT_URI` / `garmin_oauth_redirect_uri` | **`https://lnpitask.umn.edu/enroll/callback`** (no `/wearable`) | Passed as OAuth1 `callback_uri` |
| `GARMIN_REQUEST_TOKEN_URL` | `https://connectapi.garmin.com/oauth-service/oauth/request_token` | Leg 1 |
| `GARMIN_AUTHORIZE_URL` | `https://connect.garmin.com/oauthConfirm` | Leg 2 (user consent) |
| `GARMIN_ACCESS_TOKEN_URL` | `https://connectapi.garmin.com/oauth-service/oauth/access_token` | Leg 3 |
| `GARMIN_API_BASE` | `https://apis.garmin.com/wellness-api/rest` | `GET /user/id`, `DELETE /user/registration`, `GET /backfill/{type}` |

**.env.sample and the portal doc disagree with the `config.py` default.**
Production is supposed to use:

`https://lnpitask.umn.edu/wearable/enroll/callback`

That is the URI listed in
[garmin-portal-registration.md](garmin-portal-registration.md) and
`.env.sample`. Host nginx strips `/wearable` and sends `/enroll/callback` to
the backend (`deploy/nginx/wearable-hub.conf`). **Before OAuth2, confirm the
live `.env` and the portal "OAuth callback" field both have the `/wearable/`
URI.** A mismatch will fail the new `redirect_uri` check on the token POST.
While touching config, align the `config.py` default with `.env.sample`.

### 2.3 Column reuse on `provider_accounts` (OAuth1)

Documented on `ProviderAccount` and in CLAUDE.md. No extra Garmin tables.

| Column | Garmin OAuth1 meaning |
|---|---|
| `provider` | `'garmin'` |
| `entry_code` | Per-device enroll code |
| `state` | Transient **request token** (lookup key on callback) |
| `code_verifier` | Transient **request-token secret** |
| `access_token` (Fernet) | User access token (**UAT**) |
| `refresh_token` (Fernet) | **Token secret** (HMAC signing; not a refresh token) |
| `token_expires_at` | `NULL` — tokens do not expire |
| `provider_user_id` | Garmin **`userId`** (webhook identity) |
| `raw_token_json` | Full OAuth1 access-token response |
| `registered` | Linked vs revoked |

`garmin.refresh()` raises `NotImplementedError`.
`garmin.exchange()` already tries `fetch_user_id(uat, secret)` and leaves
`provider_user_id` unset on failure (logged). Ingest then has a one-unlinked-
account fallback in `garmin_ingest.resolve_account`.

### 2.4 Enroll / callback dispatch (the breaking change)

[`enroll.py`](../backend/app/routers/enroll.py) today:

1. `POST /enroll/start` looks up `entry_code` → `provider_accounts`.
2. If `provider == garmin`: `garmin.start_auth()` → persist request token on
   `state`, request secret on `code_verifier` → 303 to `oauthConfirm`.
3. `GET /enroll/callback`:
   - **`oauth_token` + `oauth_verifier` present → Garmin**
     (`_garmin_callback` looks up `state == oauth_token`).
   - **`code` + `state` → look up by `state`, then branch** Oura vs Fitbit.

Google and Oura already share `code`+`state`. **Garmin OAuth2 will arrive on
that same branch.** If we only add PKCE and leave the `oauth_token` gate in
place, Garmin callbacks will be treated as Fitbit (or 400). The Garmin
callback must become a **state lookup + `acct.provider == garmin` branch**,
the same pattern as Oura.

### 2.5 Outbound OAuth1-signed calls (must become Bearer)

All three use `_user_session(uat, secret)` → `OAuth1Session`:

| Function | HTTP | Path |
|---|---|---|
| `fetch_user_id` | GET | `{garmin_api_base}/user/id` → `{"userId": …}` |
| `deregister` | DELETE | `{garmin_api_base}/user/registration` (404 = already gone) |
| `request_backfill` | GET | `{garmin_api_base}/backfill/{summary_type}?summaryStartTimeInSeconds=&summaryEndTimeInSeconds=` |

Callers that decrypt **both** `access_token` and `refresh_token` as UAT +
secret:

- `accounts.revoke_account` (Garmin branch)
- `garmin_backfill.backfill_account`

Those signatures change. Push ingest does **not** call Garmin with a user
token.

### 2.6 Identity and PUSH (already migration-safe)

- Enrollment stores `userId` on `provider_user_id` when `GET /user/id` works.
- `garmin_ingest.resolve_account` matches `item["userId"]`.
- `_garmin_deregister` uses the same resolver, then `mark_revoked`.
- Partner requirement: *retrieve userId for all existing users before
  migration; UAT will not be in PING/PUSH after migration.* We already use
  User ID. The gap is **null `provider_user_id` rows**, not a new matching
  scheme.

Stay on **PUSH** in the portal (see
[garmin-portal-registration.md §3](garmin-portal-registration.md#3-gotchas)).
Do not switch to Ping.

---

## 3. Target-state architecture (OAuth2)

Closest in-repo analogues:

- **Enroll / PKCE / state persistence:** `fitbit_gh.generate_pkce`,
  `generate_state`, `build_authorization_url`, `exchange` — Garmin also needs
  S256 PKCE **and** `client_secret` on the token POST (confidential client).
- **Rotating refresh + commit-before-next-call:** `oura.refresh` +
  `oura_ingest._fresh_token`. Garmin refresh tokens rotate; **do not** copy
  Google's flush-only refresh-every-pull. Commit the new pair immediately.
- **Callback dispatch:** Oura's `code`+`state` → load account → branch on
  `provider`.

### 3.1 Enroll (authorization-code + PKCE S256)

Verified from the Garmin OAuth2 PKCE PDFs (developerportal.garmin.com):

1. Generate `state` and PKCE `code_verifier` / S256 `code_challenge`
   (reuse the `fitbit_gh` helpers or move them to a tiny shared util — do not
   invent a second PKCE).
2. Persist `state` + `code_verifier` on the `provider_accounts` row (same
   columns as Google; **stop** storing a request token/secret).
3. Redirect to:

```
GET https://connect.garmin.com/oauth2Confirm
    ?response_type=code
    &client_id=…
    &code_challenge=…
    &code_challenge_method=S256
    &redirect_uri=…          # exact portal URI
    &state=…
```

4. Garmin redirects to `redirect_uri` with `code` + `state` (and `error` on
   deny), **not** `oauth_token` / `oauth_verifier`.
5. Token POST, `application/x-www-form-urlencoded`:

| Field | Value |
|---|---|
| `grant_type` | `authorization_code` |
| `client_id` | OAuth2 client id (see §4) |
| `client_secret` | **new** OAuth2 secret from the portal |
| `code` | authorization code |
| `code_verifier` | PKCE verifier from the row |
| `redirect_uri` | same URI as the authorize redirect |

**Token URL (prefer, then confirm live):**

`POST https://diauth.garmin.com/di-oauth2-service/oauth/token`

An older (Jun 2025) PDF used a `connectapi.garmin.com` token host. Prefer
**diauth** (Jul 2025 PDF). Make the URL a setting so a one-line env change
can flip hosts if the live server 404s. See §8.

6. Store the full token JSON in `raw_token_json`. Denormalize
   `access_token`, `refresh_token`, `token_expires_at` from `expires_in`.
7. `GET {garmin_api_base}/user/id` with `Authorization: Bearer <access_token>`
   and write `provider_user_id`. Same best-effort-on-failure behavior as
   today.

**Scopes** are not requestable as an authorize query param. API sections are
chosen at app creation; the user ticks permissions on the consent screen.
After enroll (and on `userPermissionsChange` pushes), call
`GET {garmin_api_base}/user/permissions` with Bearer and persist the result
(`scope` column and/or `raw_token_json`). Exact JSON shape is **not** in the
sources below — log the live body during device test and map it then.

### 3.2 Token storage after cutover

Same table, new semantics:

| Column | OAuth2 meaning |
|---|---|
| `state` | Random OAuth `state` (cleared after callback) |
| `code_verifier` | PKCE verifier (cleared after callback) |
| `access_token` | OAuth2 access token (Fernet) |
| `refresh_token` | OAuth2 refresh token (Fernet) — **latest only** |
| `token_expires_at` | `now + expires_in` (naive UTC, same as Google/Oura) |
| `provider_user_id` | Garmin `userId` (unchanged) |
| `raw_token_json` | Full token response, including `expires_in` / `refresh_token_expires_in` if present |
| `registered` | unchanged |

No schema migration is required if we only remap meanings. Optional but
useful during the dual-validity window: a discriminator so code can tell
"this `refresh_token` is still an OAuth1 secret" from "this is an OAuth2
refresh token" — e.g. `raw_token_json.oauth_version = 1|2`, or
"`token_expires_at` is NULL ⇒ still OAuth1". Pick one and use it in
`_fresh_token`, backfill, and deregister. Do not sniff token string shape.

### 3.3 Refresh

Same token URL as enroll.

| Field | Value |
|---|---|
| `grant_type` | `refresh_token` |
| `refresh_token` | current refresh token |
| `client_id` / `client_secret` | OAuth2 pair |

Verified PDF example: `refresh_token_expires_in` ≈ **7775998** (~90 days).
Refresh tokens **rotate** — keep only the latest; commit before any further
Garmin call (copy `oura_ingest._fresh_token`, including the immediate
`db.commit()`).

**Access-token lifetime is contradictory in Garmin's own PDFs:** an example
shows `expires_in: 86400` (24h); prose elsewhere says ~3 months. **Trust the
live `expires_in`.** Refresh when
`token_expires_at <= now + 600s` (minimum 600s skew; a setting is fine).

If a refresh returns an invalid-grant / 401 analogue, raise a typed
`GrantRevokedError` and `mark_revoked` (Oura/Google pattern). Exact status
bodies are **unknown** until device-tested — treat 401 and `invalid_grant`
like Oura, and log anything else.

Garmin is **push-only** for daily data. Idle accounts will not refresh as a
side effect of consolidation (unlike Fitbit/Oura). Add a **scheduler job**
that walks registered Garmin rows and refreshes anything inside the skew
window (and, once `refresh_token_expires_in` is observed live, anything
whose refresh token is near expiry). Hook it in
[`backend/app/scheduler.py`](../backend/app/scheduler.py) next to
`oura_renew`. Without this, a subject who only generates pushes can sit
until the ~90-day refresh token dies, and we lose outbound deregister /
backfill.

### 3.4 Bearer API calls

Replace `_user_session` HMAC signing with:

`Authorization: Bearer <access_token>`

on `{garmin_api_base}` (wellness-api) for:

- `GET /user/id`
- `GET /user/permissions` (new)
- `DELETE /user/registration`
- `GET /backfill/{summary_type}…`

During the 30-day dual-validity window, exchanged users still have a working
OAuth1 token; prefer Bearer once `raw_token_json` says OAuth2 so we do not
depend on the dying HMAC path.

### 3.5 Webhooks

Keep `POST /webhooks/garmin/{datatype}` and PUSH portal config. Always 200.

Handle (or at least land raw, which we already do for unknown types):

- existing summary types + `deregistrations` (already special-cased)
- **`userPermissionsChange`** — persist permissions; do not revoke unless
  the payload says the grant is gone (shape **unknown** until we see a live
  event)

Partner email: after the OAuth1 token expires, "new PING/PUSH structure"
applies. We already key on `userId`. During device test, log one post-
migration dailies body and confirm `userId` is still present and the UAT is
absent. If the wrapper changes, adjust `_grouped_items` / `resolve_account`
only after seeing a payload — do not rewrite ingest speculatively.

### 3.6 What we are not building

- **Garmin Personal API** (ApiKey at
  `personal.connectapi.garmin.com/…/personal-api-key/token`, 24h access
  token, **no refresh**). Single-user only; unusable for a multi-subject
  hub. See §10.
- Ping/Pull callback token handling.
- A second Garmin app or a parallel webhook prefix.

---

## 4. Portal / support prerequisites (do these first)

These are blocking and do **not** need a watch.

1. **Inventory consumer keys.** Prod `GARMIN_CONSUMER_KEY` (and any leftover
   `garminrec` / test apps still pointing at lnpitask). One email can list
   several keys.
2. **Email** `connect-support@developer.garmin.com` (official 2026-07-27
   instruction), subject along the lines of *OAuth 1 → OAuth 2 migration —
   University of Minnesota wearable-hub*, body:
   - We are a **PUSH** partner (not PING/PULL).
   - Consumer key(s): …
   - Please convert the app(s) to OAuth 2.
   - Confirm: existing OAuth1 users/tokens keep working; new OAuth2 secret
     appears on the developer portal Apps tab.
3. **Wait for support** to confirm conversion.
4. **Portal Apps tab:** copy the new OAuth2 secret. Confirm whether
   `client_id` equals the existing consumer key or is a new value
   (**unknown** until we see the tab — do not assume).
5. **Redirect URI** must remain exactly

   `https://lnpitask.umn.edu/wearable/enroll/callback`

   OAuth2 `redirect_uri` is an exact-match. Do not "simplify" to the
   unprefixed `/enroll/callback` (that URI is Google's).
6. **Leave data endpoints on PUSH.** Recheck
   [garmin-portal-registration.md](garmin-portal-registration.md) after
   conversion — some portals grow an OAuth2-specific callback field; if a
   second field appears, it should be the same URI.
7. **API sections / permissions** at app creation: confirm Health / wellness
   coverage still matches what we ingest (dailies, sleeps, HRV, stress,
   pulse ox, respiration, body comp, user metrics, skin temp, backfill,
   deregistration). Scopes are not passed on authorize.

Until conversion, OAuth2 authorize/token hosts will not accept this app.
Token-exchange is also documented as "once your app is enabled for OAuth 2".

---

## 5. Phased implementation checklist

Implement in this order. Each item names the file/function to touch.
**This PR does not do these edits.**

### Phase 0 — Now, no device (ops + inventory)

- [ ] Send the support email (§4). Track the thread next to the saved PDF.
- [ ] On prod MariaDB, count Garmin rows:

  ```sql
  SELECT registered,
         (provider_user_id IS NULL) AS missing_uid,
         (token_expires_at IS NULL) AS no_expiry,
         COUNT(*)
  FROM provider_accounts
  WHERE provider = 'garmin'
  GROUP BY 1, 2, 3;
  ```

- [ ] Confirm live `GARMIN_OAUTH_REDIRECT_URI` and the portal callback.
- [ ] Confirm we can still `GET /user/id` OAuth1-signed for a linked subject
      (admin/repl). If that already 401s, escalate with support before
      writing a lot of exchange code.

### Phase 1 — Config and secrets

- [ ] [`backend/app/config.py`](../backend/app/config.py): add
      `garmin_client_id`, `garmin_client_secret`,
      `garmin_authorize_url` default
      `https://connect.garmin.com/oauth2Confirm`,
      `garmin_token_url` default
      `https://diauth.garmin.com/di-oauth2-service/oauth/token`,
      `garmin_token_exchange_url` default
      `https://apis.garmin.com/partner-gateway/rest/user/token-exchange`,
      `garmin_refresh_skew_seconds` default `600`.
      Keep the OAuth1 consumer key/secret and request/access URLs until
      2026-12-31 (needed to **sign token-exchange** and to finish any
      leftover OAuth1 `fetch_user_id`).
- [ ] Fix `garmin_oauth_redirect_uri` default to the `/wearable/` URI.
- [ ] [`.env.sample`](../.env.sample): document the new vars; comment that
      `GARMIN_CONSUMER_*` stay until the last OAuth1 token is exchanged /
      OAuth1 is retired.
- [ ] Prod `.env` + Quadlet secret injection (not in git): add the OAuth2
      secret after support converts the app. Rebuild/restart backend +
      scheduler (`podman build` then `systemctl restart
      wearable-backend.service` / `wearable-scheduler.service`).

### Phase 2 — Provider module (`garmin.py`)

- [ ] Module docstring: OAuth2 + PKCE + rotating refresh; push ingest
      unchanged.
- [ ] `generate_state` / PKCE: import from `fitbit_gh` or a shared helper.
- [ ] Replace `start_auth()` 3-legged request-token with
      `build_authorization_url(state, code_challenge) -> str` (Oura/Google
      shape). Or keep the name but change the return to
      `(authorize_url, state, code_verifier)` so `enroll_start` stays
      thin.
- [ ] Replace `exchange(oauth_token, oauth_verifier, request_secret)` with
      `exchange(code, code_verifier)` → `TokenResult` (`expires_at` from
      `expires_in`, `refresh_token` = OAuth2 refresh, `provider_user_id`
      from Bearer `fetch_user_id`).
- [ ] Implement `refresh(refresh_token)` (today: `NotImplementedError`).
      Rotate; map invalid grant → `GrantRevokedError`.
- [ ] `fetch_user_id(access_token)`, `deregister(access_token)`,
      `request_backfill(access_token, …)` — Bearer, drop the token-secret
      argument.
- [ ] Add `fetch_permissions(access_token)` →
      `GET {garmin_api_base}/user/permissions`.
- [ ] Add `exchange_oauth1_token(uat, token_secret) -> TokenResult`:
      `POST garmin_token_exchange_url`, request **signed with OAuth1
      credentials** (`OAuth1Session` + consumer key/secret + that user's
      UAT/secret). Rate-limit awareness lives in the job (§5 Phase 5), not
      inside a tight loop here.
- [ ] Keep a private `_user_session` **only** for token-exchange and for
      Phase 0 userId backfill until OAuth1 dies.

Exact token-exchange **request body and response JSON** are not in the
partner email (only the URL, "signed with OAuth 1 credentials", and
"returns OAuth 2 access + refresh"). **Confirm against the portal doc after
conversion.** Do not guess field names in production code; log a redacted
response in the first successful sandbox/device exchange and then lock the
parser. Store the raw body in `raw_token_json`.

### Phase 3 — Enroll router

- [ ] [`enroll.py`](../backend/app/routers/enroll.py) `enroll_start` Garmin
      branch: generate state + PKCE, persist them, redirect to
      `oauth2Confirm` (mirror the Fitbit block, not the current request-token
      block).
- [ ] `enroll_callback`: after the existing `oauth_token`+`oauth_verifier`
      gate (keep it **temporarily** so an in-flight OAuth1 handshake can
      finish), on `code`+`state` look up the account and add
      `acct.provider == garmin.NAME → _garmin_callback(db, acct, code)`.
- [ ] New `_garmin_callback(db, acct, code)`: require `code_verifier`,
      `garmin.exchange(code, acct.code_verifier)`, encrypt tokens, set
      `token_expires_at`, `provider_user_id`, `registered=True`, clear
      state/verifier. Same success page as today.
- [ ] After 2026-12-31 (or once no OAuth1 handshake can exist), delete the
      `oauth_token` branch.
- [ ] Update the module docstring (currently "Garmin recognized by OAuth1a
      params").
- [ ] Tests: start redirects to `oauth2Confirm` with `code_challenge` /
      `state`; callback with `code`+`state` on a garmin row stores tokens
      and does **not** hit Fitbit. Pattern:
      `test_enroll_start_redirects_to_oura` /
      Oura callback test in `test_oura_ingest.py`.

### Phase 4 — Callers of UAT + secret

- [ ] [`accounts.py`](../backend/app/accounts.py) `revoke_account`: Garmin
      branch uses `_fresh_token` then `garmin.deregister(access_token)`
      (Bearer). OAuth1 leftover rows: either exchange first or call the old
      HMAC deregister until 12/31.
- [ ] [`garmin_backfill.py`](../backend/app/garmin_backfill.py): decrypt +
      refresh via `_fresh_token`; pass one Bearer token into
      `request_backfill`. Update `test_garmin_backfill.py` fakes
      (`_user_session` / arity of `request_backfill`).
- [ ] New `garmin_ingest._fresh_token` **or** `providers/garmin.py` helper
      used by backfill, revoke, permissions, and the scheduler — **commit
      rotated refresh immediately** (Oura rule).
- [ ] [`scheduler.py`](../backend/app/scheduler.py): Garmin refresh sweep
      (Phase 3.3).
- [ ] [`webhooks.py`](../backend/app/routers/webhooks.py): optional
      `userPermissionsChange` hook; ingest path otherwise unchanged.
- [ ] [`models.py`](../backend/app/models.py) `ProviderAccount` docstring:
      stop saying Garmin `refresh_token` is a token secret /
      `token_expires_at` stays null.

### Phase 5 — Migration job (token-exchange)

- [ ] New module e.g. [`backend/app/garmin_oauth_migrate.py`](../backend/app/garmin_oauth_migrate.py)
      (name flexible):
      1. Select `provider='garmin' AND registered` rows still on OAuth1
         (discriminator from §3.2).
      2. Skip (and alert) if `provider_user_id` is null — run Phase 6
         backfill first.
      3. Decrypt UAT + secret; `exchange_oauth1_token`; encrypt new pair;
         set `token_expires_at`; mark `oauth_version=2` in `raw_token_json`
         (keep a copy of the OAuth1 token material in `raw_token_json`
         until the 30-day dual window ends, then drop it).
      4. **Pace ≤ 200/min** (partner limit). Stay well under (e.g. 100/min
         or 1.5s spacing) and honor 429 / `Retry-After` like
         `request_backfill`.
      5. Per-row try/except; one failure must not abort the batch. Record
         account id + error.
      6. Idempotent: already-OAuth2 rows are no-ops.
- [ ] Admin trigger: `POST /admin/garmin/oauth2/exchange` (superuser,
      dry-run flag that only counts). Optional scheduler one-shot once
      support has converted the app.
- [ ] Tests with a fake `exchange_oauth1_token` and a clock/limiter.

### Phase 6 — Docs after the code lands

- [ ] This file: tick the checklists; paste live `expires_in` /
      token-host confirmation.
- [ ] [garmin-portal-registration.md](garmin-portal-registration.md):
      OAuth2 callback wording (URL itself should not change).
- [ ] [garmin-integration-plan.md](garmin-integration-plan.md): OAuth1
      section becomes historical.
- [ ] [CLAUDE.md](../CLAUDE.md) Garmin bullet: OAuth2 + PKCE + rotating
      refresh; column meanings; callback is `code`+`state`.
- [ ] [README.md](../README.md) providers table still says OAuth 1.0a —
      update when code ships.
- [ ] [frontend/CHANGELOG.md](../frontend/CHANGELOG.md) unreleased notes.

### Phase 7 — Deploy

Code is baked into images. After merge on lnpitask:
`sudo -E podman build -t localhost/wearable-backend:latest ./backend` then
restart `wearable-backend` and `wearable-scheduler`. Frontend unchanged
unless we add a console "OAuth2 exchange" button (optional; admin POST is
enough).

---

## 6. Data migration

Two independent jobs. **User IDs first**, while OAuth1 still works.

### 6.1 Backfill null `provider_user_id`

Partner email: *User access token is no longer the primary user identifier
and will not be present in PING/PUSH after migration. Retrieve the user ID
for all existing users before migration.*

For each registered Garmin row with `provider_user_id IS NULL` and a stored
UAT+secret: `garmin.fetch_user_id` (OAuth1) and persist. Collision
(two rows, same `userId`): stop and inspect — do not silently merge.

If `GET /user/id` fails, the one-unlinked-account fallback in
`resolve_account` can still bind a push, but that is unsafe once more than
one subject is unlinked. Do not rely on it for cutover.

A row with no tokens and no `userId` cannot be exchanged or matched; staff
must issue a new entry code and have the subject re-consent (OAuth2).

### 6.2 Batch token-exchange

Once the app is OAuth2-enabled:

```
POST https://apis.garmin.com/partner-gateway/rest/user/token-exchange
```

- Sign with **OAuth 1 credentials** (consumer key/secret + that user's UAT
  and token secret — this is the only reading consistent with "exchange an
  OAuth 1 token"). Confirm the exact signing recipe and body from the
  portal doc.
- **200 requests/minute** max.
- Response: OAuth2 access + refresh (field names **unconfirmed**).
- **Original OAuth1 token remains valid 30 days after that exchange.**
  After it expires, only Bearer + the new PUSH structure apply.

Order: dry-run count → one volunteer/device subject → rest of the table.
Keep the 30-day dual window **inside** December if possible so a bad
exchange can still use OAuth1 to re-try or to call `/user/id`.

### 6.3 Failure / re-consent

| Failure | What to do |
|---|---|
| Token-exchange 4xx/5xx | Leave OAuth1 tokens in place; log; retry with backoff. Do not `mark_revoked`. |
| Persistent exchange failure | New `entry_code` (or reuse after `registered=False` — enroll_start rejects already-registered codes). Subject completes OAuth2. Push matching uses the same `userId` once `GET /user/id` (Bearer) returns. Daily rows stay; they key on `provider_account_id`. |
| Refresh `invalid_grant` after cutover | `mark_revoked` (tokens are dead). Staff create a new registration; subject re-enrolls. Do not invent a silent re-refresh. |
| Null `userId` after both OAuth1 and Bearer `/user/id` fail | Re-consent; we cannot attach pushes. |
| Subject refuses re-consent | Account stays unregistered after 12/31; historical `daily_health` / `health_data` remain (revoke already keeps data). |

Do not delete `health_data` / `daily_health` as part of this migration.

---

## 7. Testing plan (after ~Dec 9, device available)

Unit tests (Phase 2–5) can land before the watch. Live tests below need a
real Garmin Connect login and a watch that will sync.

Use the existing enroll page
(`https://lnpitask.umn.edu/wearable/enroll`) and a staff-minted
`provider_accounts.entry_code` on a throwaway subject.

| # | Scenario | Pass |
|---|---|---|
| 1 | **New OAuth2 enroll** | Start → Garmin consent (`oauth2Confirm`) → callback `code`+`state` only → row `registered`, `token_expires_at` set, `refresh_token` present, `provider_user_id` set, `raw_token_json` has `expires_in`. |
| 2 | **Wrong / reused code** | Existing enroll errors unchanged (invalid code, already registered, archived). |
| 3 | **Refresh** | Force `token_expires_at` into the skew window (or wait). Next backfill/revoke/scheduler tick stores a **new** refresh token and a later expiry. Confirm the previous refresh token is not reused. |
| 4 | **PUSH after enroll** | Sync the watch. `POST /webhooks/garmin/dailies` (and sleeps if offered) returns 200; `health_data` lands; `daily_health` updates; `resolve_account` hits `userId`. Compare one payload to today's fixtures — note if the wrapper dropped any UAT field. |
| 5 | **Disconnect inbound** | Revoke the app in Garmin Connect → `deregistrations` push → `registered=False`, tokens cleared, `provider_user_id` kept (`mark_revoked`). |
| 6 | **Disconnect outbound** | Staff `POST /admin/subjects/{id}/revoke` → Bearer `DELETE /user/registration` → local revoke. Confirm Garmin Connect no longer lists the app (or 404 on a second delete). |
| 7 | **Permissions** | `GET /user/permissions` after enroll; if you can toggle a permission in Connect, a `userPermissionsChange` push should land. |
| 8 | **Backfill (Bearer)** | `POST /admin/subjects/{id}/backfill` for a short range → 202s → later PUSH of those types. Same 429 pacing as today. |
| 9 | **Token-exchange** | If any OAuth1 subject remains (or a row you deliberately left on OAuth1): dry-run count → exchange one → row becomes OAuth2, `userId` unchanged, pushes still match. Re-exchange is a no-op or a documented error. |
| 10 | **Regression: Fitbit + Oura enroll** | One Fitbit and one Oura callback (`code`+`state` on those providers) still dispatch correctly after the Garmin branch is added. |
| 11 | **Idle refresh job** | With a near-expiry Garmin row and no backfill, the scheduler refreshes without waiting for a push. |

There is no Garmin sandbox equivalent of `OURA_USE_SANDBOX`. Fixtures from
`test_garmin_ingest.py` stay valid for ingest; they do not exercise OAuth.

---

## 8. Risks and open questions

Mark each **resolved** in this file when device-tested. Do not fill them
with guesses in code.

| Item | What we know | What we do not |
|---|---|---|
| **Token host** | Jul 2025 PDF: `https://diauth.garmin.com/di-oauth2-service/oauth/token`. Jun 2025 PDF used `connectapi.garmin.com`. | Which host answers for our converted app. Prefer diauth; keep `garmin_token_url` configurable. |
| **Access-token lifetime** | Example `expires_in=86400`; other prose says ~3 months. | Live `expires_in`. Always persist and honor it; 600s skew. |
| **Refresh rotation / 90 days** | Example `refresh_token_expires_in ≈ 7775998`. Tokens rotate. | Whether every refresh returns a new refresh token; behavior if we send a stale one. Commit immediately; keep latest only. |
| **`client_id` vs consumer key** | Support creates a **new OAuth2 secret** on the Apps tab. Existing OAuth1 users keep working. | Whether `client_id` is the old consumer key or a new id. Read the portal; put both in env if they differ. |
| **Token-exchange body** | URL, 200/min, OAuth1-signed, returns access + refresh; OAuth1 valid 30 days more. | JSON/form fields, response keys, error codes, whether 409 means "already exchanged". |
| **"New PING/PUSH structure"** | UAT will not be the identifier; use `userId`. We already do. | Whether summary field names change. Log one live payload after exchange expiry. |
| **Starter vs Enterprise / backfill** | Live (OAuth1) backfill: ~30 days before connect; 90-day window cap; some types webhook-only (`pulseox`, `bodyComps`, `skinTemp`). | Whether OAuth2 or a program tier change alters history depth. Re-run one backfill after Bearer cutover; do not advertise deeper history without a live result. |
| **Gated PDFs** | PKCE authorize/token details are on **developerportal.garmin.com** (login), not the public FAQ. Public FAQ now says Developer Program APIs use OAuth 2.0. | Sections we cannot see here (error catalog, PING-only notes, exact permissions JSON). Re-download the Jul 2025 (and any newer) PDF the week of implementation. |
| **In-flight OAuth1 enrolls** | Callback today requires `oauth_token`+`oauth_verifier`. | A subject mid-handshake when we deploy OAuth2 start. Keep the old callback branch until 12/31; do not start new OAuth1 handshakes once Phase 3 ships. |
| **`config.py` redirect default** | Default lacks `/wearable/`; sample + portal have it. | Prod `.env` value — verify explicitly. |
| **How many prod Garmin subjects** | Code and CHANGELOG show the provider is live. | Counts. Phase 0 SQL. Zero rows still need new-enroll + refresh + push tests. |
| **`userPermissionsChange`** | Named in the PKCE docs as the webhook for permission ticks. | Payload shape and whether it can mean full disconnect (vs `deregistrations`). |

---

## 9. Sources and links

### Verified (this repo + partner email)

- Partner email, 2026-07-27, Garmin Connect Partner Services
  `<connect-support@developer.garmin.com>`, subject *Garmin Connect Developer
  APIs OAuth 1 to OAuth 2 Migration*. Saved as
  [`docs/20260806_garmin_oauth1_to_oauth2.pdf`](20260806_garmin_oauth1_to_oauth2.pdf).
  Support contact for the conversion: the same address.
- Current implementation: files in §2.1.
- Portal URL checklist:
  [garmin-portal-registration.md](garmin-portal-registration.md).
- Original OAuth1 design (now historical):
  [garmin-integration-plan.md](garmin-integration-plan.md).

### Verified (OAuth2 PKCE PDFs on developerportal.garmin.com)

Gated; not copied into this repo. Re-open the latest copies before coding.

- Authorize: `GET https://connect.garmin.com/oauth2Confirm` with
  `response_type=code`, `client_id`, `code_challenge`,
  `code_challenge_method=S256`, `redirect_uri`, `state`.
- Token: prefer
  `POST https://diauth.garmin.com/di-oauth2-service/oauth/token`
  (Jul 2025 PDF); older Jun 2025 PDF used `connectapi.garmin.com`.
- `grant_type=authorization_code` with `client_id`, `client_secret`,
  `code`, `code_verifier`, `redirect_uri`.
- Refresh: same token URL, `grant_type=refresh_token`; refresh tokens
  rotate; example `refresh_token_expires_in ≈ 7775998`.
- Identity: `GET https://apis.garmin.com/wellness-api/rest/user/id` with
  Bearer.
- Permissions: `GET …/user/permissions`; webhook `userPermissionsChange`.
- Deregister: `DELETE …/user/registration` with Bearer (today this path is
  OAuth1-signed in our code).
- API calls: `Authorization: Bearer <access_token>` on wellness-api.

### Public Garmin pages (program context; not a substitute for the PDFs)

- [Connect Developer Program FAQ](https://developer.garmin.com/gc-developer-program/program-faq/)
  — public FAQ now states Developer Program APIs use OAuth 2.0.
- [Enterprise program FAQ](https://developer.garmin.com/gc-developer-program/enterprise/program-faq/)
- [Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api/)
  and [Personal FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq/)
  — **excluded** (ApiKey, no refresh, single user). See §10.

---

## 10. Non-goals (this PR and this migration)

- **No application code** in the PR that first lands this document — only
  this plan and optional cross-links from existing Garmin docs.
- **No Personal API path.** It cannot represent research subjects and has
  no refresh token.
- **No PING/PULL rewrite.** Stay on PUSH. The extra callback token param
  from the partner email applies to PING/PULL partners.
- **No ingest/mapping rewrite** unless a live post-migration payload
  proves the wrapper changed.
- **No new provider** and no Garmin-specific schema. Column *meanings*
  change; the table does not.
- **No Apple/Samsung work** and no other vendor (see
  [wearable-provider-landscape.md](wearable-provider-landscape.md)).
- **Do not** drop OAuth1 consumer credentials or the `oauth_token`
  callback branch until token-exchange is done and/or OAuth1 is retired.

---

## Appendix — column and call remap (cheat sheet)

| Today (OAuth1) | After (OAuth2) |
|---|---|
| `start_auth` → request token + `oauthConfirm` | PKCE + `oauth2Confirm` |
| Callback `oauth_token`+`oauth_verifier` | Callback `code`+`state` (shared with Oura/Google; branch on `provider`) |
| `state` / `code_verifier` = request token/secret | `state` / `code_verifier` = OAuth state / PKCE verifier |
| `access_token` = UAT, `refresh_token` = HMAC secret, `expires_at` null | Bearer access, rotating refresh, `expires_at` from `expires_in` |
| `refresh()` raises | `refresh()` + scheduler sweep + `_fresh_token` (commit-on-rotate) |
| `_user_session` HMAC for `/user/id`, `/user/registration`, `/backfill/*` | Bearer on the same paths (+ `/user/permissions`) |
| Token-exchange N/A | OAuth1-signed `POST …/user/token-exchange`, ≤200/min, 30-day dual validity |
| Push match `userId` | Unchanged — **must** be populated before exchange |
