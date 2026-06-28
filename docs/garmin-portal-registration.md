# Garmin Connect Developer portal — registration reference

One-stop list of the URLs to enter in the **Garmin Connect Developer** app registration, plus their
implementation status in this app. Host: **`https://lnpitask.umn.edu`**.

> The host-nginx routing that makes these public lives in
> [`deploy/nginx/wearable-hub.conf`](../deploy/nginx/wearable-hub.conf) (the version-controlled
> source of truth — the live host file is merged from it). After editing it:
> `sudo nginx -t && sudo nginx -s reload`. The backend routes are confirmed served; external
> reachability should be spot-checked with `curl -I` from off-host.

## 1. App-registration fields

| Portal field | URL | Notes |
|---|---|---|
| **OAuth callback** | `https://lnpitask.umn.edu/wearable/enroll/callback` | One `/enroll/callback` handles both providers, dispatched by params. Set as `GARMIN_OAUTH_REDIRECT_URI`. |
| **Privacy policy** | `https://lnpitask.umn.edu/privacy` | Root; also reachable at `…/wearable/privacy`. Same copy Google's OAuth review uses. |
| **Brand image** | `https://lnpitask.umn.edu/wearable/branding.png` | 300×300. Also served as **`…/wearable/branding.jpg`** and **`…/wearable/icon`** — use whichever the validator accepts. |

## 2. Data endpoints (push URLs)

All follow `https://lnpitask.umn.edu/wearable/webhooks/garmin/<type>`. Configure each as a **PUSH**
(see [gotchas](#3-gotchas)). The handler always returns 200.

| Garmin summary type | Path segment | Implementation |
|---|---|---|
| Dailies | `dailies` | ✅ aggregated → `daily_health` (steps/distance/cal/floors/HR + intraday HR) |
| Sleeps | `sleeps` | ✅ aggregated → `daily_health` (sleep minutes + stages) |
| HRV | `hrv` (also `hrvSummary`) | ✅ aggregated → `daily_health` (`hrv_ms`) |
| Stress Details | `stressDetails` (also `stress`) | ✅ aggregated → `daily_health` (avg/max + bands) |
| Pulse Ox | `pulseox` (also `pulseOx`) | ✅ aggregated → `daily_health` (`spo2_avg`) |
| Respiration | `respiration` | ✅ aggregated → `daily_health` (avg/min/max) |
| Body Composition | `bodyComps` | ✅ aggregated → `daily_health.metrics` |
| User Metrics | `userMetrics` | ✅ aggregated → `daily_health.metrics` (VO2max, fitness age) |
| Skin Temperature | `skinTemp` (also `skinTemperature`) | ✅ aggregated → `daily_health.metrics` (overnight deviation °C) |
| Epochs | `epochs` | ▫️ raw-landed in `health_data` (no daily mapping yet) |
| Health Snapshot, Activities, Activity Details, Blood Pressures, MoveIQ, … | `<type>` | ▫️ raw-landed in `health_data` |
| **Deregistration** | `deregistrations` | ✅ **required** — marks the account unregistered (revocation) |

✅ = mapped into `daily_health`; ▫️ = accepted + stored raw (still safe to register — it just isn't
rolled up yet). Every datatype is accepted regardless of whether it's mapped.

## 3. Gotchas

- **Use PUSH, not Ping.** The app expects the full data in the POST body. A Ping/notification carries
  no values, so it would land an empty `health_data` row and aggregate nothing.
- **Don't skip `deregistrations`** — without it, a subject who revokes in Garmin Connect won't be
  marked unregistered here.
- **Path segment is for routing only.** Aggregation keys off the JSON body's top-level type, not the
  URL, so a single shared URL would also work — per-type paths are just tidier for logs.
- **`PUBLIC_PATH_PREFIX=/wearable`** (set in `.env`) keeps the enroll page's own links/redirects
  inside the prefix.
- **Sync the host nginx.** The `/wearable/...` blocks must be live on the host nginx, then reloaded.

### Brand image formats

All three are served by the backend and proxied by the host nginx (verified live, `nginx -t` OK), so
pick whichever Garmin's branding-image validator accepts:

- `https://lnpitask.umn.edu/wearable/branding.png` (300×300 PNG)
- `https://lnpitask.umn.edu/wearable/branding.jpg` (JPEG variant — some validators reject PNG)
- `https://lnpitask.umn.edu/wearable/icon` (extension-less)

## 4. Implementation status (where this lives in code)

- Webhook route: `POST /webhooks/garmin/{datatype}` — `app/routers/webhooks.py` (`garmin_push`).
  Always returns 200; lands raw; dispatches `deregistrations` → `_garmin_deregister` → `mark_revoked`.
- Aggregation: `app/garmin_ingest.py` `_APPLIERS` (the ✅ types) + `ingest_push`.
- OAuth 1.0a + identity/deregister: `app/providers/garmin.py`.
- Branding/privacy/home pages: `app/routers/public.py`.

## 5. Google (Fitbit) equivalents — for reference

These coexist and stay at **root** (the verified Google Cloud Console app points there):

| Purpose | URL |
|---|---|
| Home | `https://lnpitask.umn.edu/` |
| Privacy | `https://lnpitask.umn.edu/privacy` |
| OAuth callback | `https://lnpitask.umn.edu/enroll/callback` |
| Webhook | `https://lnpitask.umn.edu/webhooks/google-health` |
