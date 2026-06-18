# Scope Justifications (paste-ready for Cloud Console)

Google requires a **specific, least-privilege** justification per scope, demonstrating that each
requested scope is necessary and that no narrower scope suffices. Vague or duplicated justifications
cause delays. Paste the "Justification" text into the Cloud Console OAuth Verification Center for the
matching scope.

The current scope list lives in `GOOGLE_HEALTH_SCOPES` (`.env`). Each scope below is mapped to the
exact backend feature that consumes it (see `backend/app/consolidation.py` `DATATYPE_SPEC` and
`backend/app/providers/fitbit_gh.py`).

> **Context to include in every justification:** "Wearable Hub is a University of Minnesota research
> application. Enrolled study participants explicitly consent to share the data below with their
> research team. All scopes are read-only and used solely for the research study."

---

## 1. `.../auth/googlehealth.activity_and_fitness.readonly`

**Feature:** Daily and intraday activity consolidation — steps, distance, calories, floors, and
exercise sessions — shown to researchers and exported per subject/study.

**Justification:** "Read-only access to the participant's activity and fitness data (steps,
distance, calories, floors, exercise). The research study analyzes participants' daily activity
patterns; the app reads daily totals and intraday detail and stores them per participant for the
study team. No narrower scope provides these activity metrics."

## 2. `.../auth/googlehealth.sleep.readonly`

**Feature:** Sleep duration and per-stage (awake/light/deep/REM) breakdown in the daily view.

**Justification:** "Read-only access to the participant's sleep data. The study analyzes sleep
duration and sleep-stage composition; the app reads each night's sleep record and aggregates stage
durations for the research team. No narrower scope provides sleep data."

## 3. `.../auth/googlehealth.health_metrics_and_measurements.readonly`

**Feature:** Resting heart rate, heart-rate variability (HRV), and blood-oxygen saturation (SpO2) —
pulled during daily consolidation (these are not webhook-subscribable).

**Justification:** "Read-only access to the participant's health metrics — resting heart rate,
heart-rate variability, and blood-oxygen saturation (SpO2). These physiological measures are core
study outcomes; the app reads the daily values for the research team. No narrower scope provides
these metrics."

> Heart-rate average/min/max is read via the activity/fitness consolidation; the resting HR / HRV /
> SpO2 values specifically require this metrics scope.

## 4. `.../auth/googlehealth.profile.readonly`

**Feature:** Reading the participant's Health profile, including the paired-device list, to record
which wearable is generating the data.

**Justification:** "Read-only access to the participant's Health profile to identify the paired
wearable device associated with the shared data. The study needs to know the device model providing
each participant's measurements. No narrower scope exposes the paired-device profile."

## 5. `.../auth/googlehealth.settings.readonly`

**Feature:** Paired-device details — model, battery level, and last sync time — surfaced in the
console so staff can spot devices that have stopped syncing or are low on battery.

**Justification:** "Read-only access to wearable device settings/status (model, battery level, last
sync time). Study staff use this to confirm each participant's device is still active and syncing so
data collection isn't silently interrupted. No narrower scope provides device battery/sync status."

---

## Scopes to REMOVE before submission (least privilege)

These are present in `GOOGLE_HEALTH_SCOPES` but **no code reads them today**. Google rejects scopes
without a demonstrated in-product use, so drop them from `.env` unless/until the feature ships:

- `.../auth/googlehealth.ecg.readonly` — no ECG read path in the codebase.
- `.../auth/googlehealth.irn.readonly` — no irregular-rhythm-notification read path.

**Action:** remove both from `.env`, rebuild the backend, and re-enroll test users **before**
submitting. If ECG / IRN become study requirements later, implement + demo them, then add the scopes
back with their own justifications.

## `openid` / `email`

Standard sign-in scopes for completing the OAuth flow and identifying the authorizing account — not
restricted, no special justification needed beyond the consent-flow demo.
