# Reduce intraday data volume: 5-min buckets for steps, distance, SpO2

## Context

The per-subject export `lim.kelvino@gmail.com-8EXMY6.json` carries **~1,452 intraday points
per day** (20,619 over 18 days). Measured per-day breakdown and current sampling interval:

| datatype | pts/day | interval | how stored today |
|---|---|---|---|
| `oxygen_saturation` | ~389 | **1 min** (sleep) | raw, **full dataPoint JSON in `payload`** |
| `steps` | ~349 | **1 min** | raw 1-min points |
| `distance` | ~349 | **1 min** | raw 1-min points |
| `heart_rate` | 288 | 5 min avg | already downsampled ✓ (the model to copy) |
| `heart_rate_variability` | ~75 | 5 min | raw (already coarse — leave as-is) |
| sleep / exercise | ~2 | — | — |

`heart_rate` is already aggregated to 5-min average buckets via
`pull_intraday_hr` + `_upsert_hr_bucket`, gated by `Settings.hr_downsample_minutes` (default 5).
The three heavy datatypes are still at 1-minute granularity. Goal: integrate `steps` (and
`distance`) into 5-min **sum** buckets, collapse intraday `oxygen_saturation` into 5-min
**average + min** buckets, and clean up the already-stored 1-min rows.

**Expected effect:** steps ~349→~70, distance ~349→~70, SpO2 ~389→~78 per day →
**~1,452 → ~580 points/day (~60% fewer rows)**, plus elimination of the large per-row raw
`payload` JSON currently stored on every SpO2 sample.

Decisions confirmed with the user:
- SpO2 bucket value = **average**, with the bucket **minimum** preserved (desaturation nadir).
- **Both** steps and distance get 5-min sum buckets *when intraday is wanted*.
- **Re-consolidate existing days and delete the orphaned 1-min rows** so history isn't mixed.
- **Tiered storage** (see below): intraday steps/distance points become **opt-in per study**;
  daily totals always come from rollup regardless.

## Rollup finding (live-verified 2026-06-18) — why the tier matters

Tested against the live `dataPoints:dailyRollUp` endpoint (see CHANGELOG):
- It is **daily-granularity only** — no `bucketByTime`/`period` field (both `400`); a multi-day
  range returns one aggregate per civil day. **It cannot produce 5-min/hourly buckets in one
  call**, so intraday curves still need raw pulls + client-side downsampling (this plan).
- Its real storage lever is that the **daily total already comes from rollup**, independent of any
  stored points (verified: steps `countSum 9264` == the day's `daily_health.steps`). So intraday
  step/distance points are pure redundancy unless a study analyzes within-day activity shape.

**Tier:** keep rollup for daily totals (1 row/day, already running); make intraday steps/distance
points **opt-in** (off by default → 0 intraday rows; on → 5-min sum buckets). This beats always
storing buckets and costs nothing in daily accuracy.

## Changes

### 0. Per-study opt-in for intraday steps/distance — `backend/app/models.py` + Alembic
Add a `studies.ingest_intraday_activity` boolean (default **False**), mirroring the existing
`ingest_intraday_hr` / `ingest_intraday_hrv` / `ingest_intraday_spo2` flags
([models.py:69-73](backend/app/models.py#L69-L73)) with a new migration like
[`0007_study_intraday_hr.py`](backend/alembic/versions/0007_study_intraday_hr.py). Surface it in the
console study toggles / `PATCH /admin/studies/{id}` alongside the other intraday flags. When off
(default), **no** intraday step/distance points are stored — daily totals still come from rollup.

### 1. Config — `backend/app/config.py` (next to `hr_downsample_minutes`, ~line 56)
Add two settings (env-overridable, default 5; `0` = keep raw):
- `steps_bucket_minutes: int = 5` — bucket size for intraday `steps`/`distance` when enabled.
- `spo2_downsample_minutes: int = 5` — applies to intraday SpO2.

### 2. New aggregation helpers — `backend/app/consolidation.py`

- **`bucket_sum_points(points, read_id, bucket_min) -> list[dict]`** — for summable 1-min list
  points (steps/distance). Floor each point's `interval.startTime` to the bucket boundary, **sum**
  values, count samples, capture the tz offset from the points. Return
  `[{start, end, sum, n, off}]`; `bucket_min <= 0` → passthrough. Mirror the bucketing math in
  `pull_intraday_hr` ([consolidation.py:256-265](backend/app/consolidation.py#L256-L265)).
- **`bucket_samples_avg_min(pts, value_key, scalar_key, bucket_min) -> list[dict]`** — for SpO2
  samples (parse `sampleTime.physicalTime` like
  [`_upsert_sample_point`](backend/app/consolidation.py#L467)). Per bucket compute **avg** and
  **min**. Return `[{start, end, avg, min, n, off}]`; `bucket_min <= 0` → fall back to raw.
- **`_upsert_value_bucket(db, account_id, datatype, d, bkt, bucket_min, extra=None)`** — generic
  bucket upsert mirroring [`_upsert_hr_bucket`](backend/app/consolidation.py#L446-L465):
  `point_key = f"{datatype}|{bkt['start'].isoformat()}"`, `value` = sum/avg, `payload` carries the
  bucket metadata (`samples`, `bucket_minutes`, and for SpO2 `spo2_avg`/`spo2_min`). Keep the
  `db.add()` → `db.flush()` ordering (autoflush is off; required for the
  `uq_hdp_acct_dt_key` find-or-create — see CLAUDE.md).
- **`_replace_points_for_day(db, account_id, datatype, d)`** — `DELETE` existing
  `HealthDataPoint` rows for `(provider_account_id, datatype, local_date)` before inserting buckets.
  Makes `consolidate_day` self-cleaning across granularity changes (covers the "clean old rows"
  requirement) and idempotent on re-runs.

### 3. Wire into `consolidate_day` — `backend/app/consolidation.py`

- **Steps/distance** in the `spec.list_` loop
  ([consolidation.py:608-627](backend/app/consolidation.py#L608-L627)): for
  `name in ("steps","distance")`, gate intraday storage on `study.ingest_intraday_activity`.
  - **Off (default):** skip the `list` pull entirely for these two types — daily totals still come
    from the rollup branch above. Also `_replace_points_for_day` so any previously stored 1-min
    rows are cleaned on the next consolidation.
  - **On:** after `pull_points`, `_replace_points_for_day`, then (when `steps_bucket_minutes > 0`)
    `bucket_sum_points` + `_upsert_value_bucket` instead of the raw `_upsert_point` loop; derive
    `tz_off` from the bucket offsets.

  Note `tz_off` is currently discovered from steps/distance raw points
  ([consolidation.py:616-618](backend/app/consolidation.py#L616-L618)) — when the `list` pull is
  skipped, ensure `tz_off` still resolves (it's also derivable from the rollup civil bounds or the
  intraday HR/sample offsets). Other list types (sleep/exercise/altitude/height) keep the existing
  raw path unchanged.
- **SpO2** in the intraday-sample block
  ([consolidation.py:691-706](backend/app/consolidation.py#L691-L706)): for
  `oxygen_saturation`, when `spo2_downsample_minutes > 0`, call `_replace_points_for_day`, then
  `bucket_samples_avg_min` + `_upsert_value_bucket`. **HRV stays on the existing raw
  `_upsert_sample_point` path** (already 5-min). Update the `metrics["intraday"]` counts to the
  bucket count.

### 4. Surface the SpO2 nadir in exports — `backend/app/routers/admin.py`
[`_point_to_dict`](backend/app/routers/admin.py#L492-L508) currently emits only
`value` (plus sleep stages). Add, when `payload` is a dict, the bucket extras for these datatypes
(`samples`, and for `oxygen_saturation` the `spo2_min`/`spo2_avg`) so the per-bucket minimum shows
up in the JSON/CSV export and day-expansion views.

### 5. Apply to existing data
Re-run consolidation across the stored range so old 1-min rows are deleted (and replaced with
buckets where intraday is enabled), via the existing on-demand endpoint
[`consolidate_subject`](backend/app/routers/admin.py#L430) (`POST /admin/subjects/{id}/consolidate`
over the date span, e.g. 2026-06-01..2026-06-18). One Alembic migration for the new
`ingest_intraday_activity` column (§0); no other schema change.

## Other data-reduction options (noted, not in scope unless you want them)
- Raise `hr_downsample_minutes` / `steps_bucket_minutes` to 10–15 min for further halving.
- Skip zero-value step/distance buckets when intraday activity is enabled.
- The biggest *byte* win is already captured: bucketed SpO2 stops storing the full raw dataPoint
  JSON in `payload` that every 1-min sample currently holds.
- Note: server-side hourly/5-min rollup is **not** an option — verified that `dailyRollUp` is
  daily-only (see Rollup finding above).

## Verification
1. `cd backend && podman build -t localhost/wearable-backend:latest ./backend` then restart the
   backend (prod) or `docker-compose down/up` (dev) — code is baked into the image (CLAUDE.md).
2. Trigger `POST /admin/subjects/1/consolidate` for 2026-06-01..2026-06-18.
3. Re-export the subject JSON and re-run the analysis used here, for each tier:
   - **Default (activity off):** no `steps`/`distance` intraday points; `oxygen_saturation`
     ~78/day at 300 s spacing → **~370 points/day** (down from ~1,452). Daily `steps`/`distance_m`
     unchanged (from rollup).
   - **Activity on:** `steps`/`distance` ~70/day each at 300 s spacing → ~510 points/day.
   - SpO2 export points carry `spo2_min` alongside `value` in both cases.
4. Confirm no `uq_hdp_acct_dt_key` 500s on re-consolidation (idempotent re-run) and that
   `daily_health` headline columns (`steps`, `distance_m`, `spo2_avg`) are unchanged (they come
   from `dailyRollUp` / `daily-oxygen-saturation`, independent of the intraday buckets).
