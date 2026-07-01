# Google Verification — Status Tracker

Living checklist for taking GCP project `fitbitdata-499001` from **Testing** → verified
**Production**. Mirrors the step order in
[00-runbook-testing-to-production.md](00-runbook-testing-to-production.md); update the boxes here
as you go.

- **Study:** UMN IRB **STUDY00026668** · PI **Kelvin O. Lim** · contact **kolim@umn.edu**
- **GCP project:** `fitbitdata-499001` · **Domain:** `lnpitask.umn.edu`
- **Last reviewed:** 2026-06-30
- **Legend:** ✅ done · 🔜 next / actionable now · ⏳ blocked on an external party · ⬜ not started

---

## ⚠️ Decision gate — do we even need full verification? (read first)

Full production verification **+ CASA is only forced by crossing 100 users.** For a bounded IRB
study there may be a much cheaper path — settle this **before** spending time/money on Steps 5–9.
There is **no** academic-researcher waiver ([Google Health app-verification](https://developers.google.com/health/app-verification)
confirms none); the 100-user allowance below is the real lever.

**The ≤100-user allowance.** The 100-user cap is **per GCP project** (counts over the project's
lifetime, non-resettable). Google requires the third-party security review (CASA) only for
**>100 users**; at ≤100 you can operate **unverified** and skip CASA entirely.
- Use **Production + unverified**, *not* plain *Testing*: in Testing, restricted-scope refresh
  tokens expire after **7 days** (fatal for passive collection); once the app is **In Production**
  refresh tokens don't expire. So: publish to production, stay unverified, keep ≤100 users.
- Trade-off: subjects see an **"unverified app"** warning on the consent screen; Limited-Use +
  a live privacy policy are still required (already done).

**Per-study projects (multiplying the cap).** Because the cap is per project, each discrete study
can have its **own GCP project + OAuth client + consent screen + subscriber + service account**,
each with an independent ≤100 allowance. Genuinely separate studies (distinct IRB protocol / PI /
consent / data governance) are a defensible basis for separate projects. **Caveat:** Google tracks
**brand identity across projects**, so you cannot clone one app across projects purely to dodge the
>100 threshold — the studies must be truly distinct. Needs app changes (per-study credentials — the
app currently uses one global credential set; see [README architecture](../../CLAUDE.md)).

**Action — get target enrollment N _per study_:**
- **Every study ≤100** → run unverified-production per study and **skip Steps 6–9 (incl. CASA)**;
  only Steps 0, 3, 4, and a per-project consent screen apply.
- **Any study >100** → that project needs full restricted-scope verification **and** CASA (below).

**Per-subject enrollment — no email allowlisting in Production.** In **Testing** mode you must
manually add each subject's Google email to the project's test-user list — Console-only, see
[07-test-user-management.md](07-test-user-management.md). In **Production + unverified** you do
**not**: any subject self-authenticates (past the unverified-app warning) up to the 100 cap. The
app never needs the subject's email — enrollment is by **entry code**: a **study-admin (the PI)**
creates the subject + code in the researcher console, the subject enters it at `/enroll` and
authorizes (linked by `healthUserId`, not email). So each PI's per-subject work is *create subject
+ hand out code*, entirely in-app. Only the **one-time per-study GCP project setup** (consent
screen, scopes, subscriber, service account, publish-to-production) is a central/admin task — not
per-subject and not the PI's.

> Confirm the unverified-production + ≤100 behavior directly with Google before committing — the
> token/consent nuances matter for a longitudinal study.

---

## At a glance

Roughly **4 of 10** steps complete. The live-site prerequisites (homepage, privacy, disclosure,
least-privilege scopes) are done. **Immediate next actions:** confirm GCP org ownership (Step 0),
verify the domain in Search Console (Step 5), and configure the consent screen (Step 6). Longest
lead time is the **CASA Tier-2 assessment** (Step 9) — line up the assessor early.

**Plan 4–8 weeks end to end** (brand review ~2–3 business days; restricted-scope review several
weeks; CASA ~2–3 weeks).

---

## Checklist

### Step 0 — Ownership & branding contacts ⏳ (UMN OIT)
- [ ] Confirm `fitbitdata-499001` is under the **UMN Google Cloud org** (not a personal account).
- [ ] OAuth **Branding** page: app name, **support email**, **developer contact email** — both
      monitored `umn.edu` addresses (Google sends verification + recert notices there).
- [ ] Confirm Owner/Editor roles for whoever submits and responds to the assessor.

### Step 1 — Study contact ✅
- [x] PI / support / IRB filled across `backend/app/routers/public.py` and these docs.

### Step 2 — Least-privilege scope set ✅
- [x] `ecg.readonly` + `irn.readonly` removed. Verified `.env` `GOOGLE_HEALTH_SCOPES` = 5 scopes
      (activity_and_fitness, health_metrics_and_measurements, sleep, profile, settings).
- [x] Justifications drafted → [02-scope-justifications.md](02-scope-justifications.md).

### Step 3 — Live homepage + privacy policy ✅
- [x] Served by `backend/app/routers/public.py` (`GET /`, `GET /privacy`).
- [x] Host nginx `location = /` and `location = /privacy` proxy blocks in place
      (`/etc/nginx/nginx.conf`; source [deploy/nginx/wearable-hub.conf](../../deploy/nginx/wearable-hub.conf)).
- [x] Both load publicly (incognito), same domain — verified `200` on
      `https://lnpitask.umn.edu/` and `/privacy` (2026-06-30).

### Step 4 — In-app disclosure ✅
- [x] Prominent disclosure on the `/enroll` form (see [06-in-app-disclosure.md](06-in-app-disclosure.md)),
      backend deployed.
- [ ] Re-spot-check `/enroll` shows the disclosure block + working `/privacy` link before submitting.

### Step 5 — Verify domain ownership 🔜 (may need UMN DNS)
- [ ] In **Google Search Console**, verify `lnpitask.umn.edu` using an account with Owner/Editor
      on the project (may need a UMN DNS TXT record or web-admin help).

### Step 6 — Consent screen + scopes in Cloud Console 🔜
- [ ] User type = **External**.
- [ ] App name, logo, support email, home page, privacy policy, authorized domain (`umn.edu`).
- [ ] Add each scope + paste its justification from
      [02-scope-justifications.md](02-scope-justifications.md) (be specific — vague ones stall review).

### Step 7 — Demo video ⬜
- [ ] Record per [05-demo-video-script.md](05-demo-video-script.md): app name on consent screen,
      client ID visible in URL, each restricted scope exercised, in-app disclosure shown.
- [ ] Upload to YouTube **Unlisted**; keep the link for the submission.

### Step 8 — Submit for verification ⏳ (Google Trust & Safety)
- [ ] OAuth Verification Center → **In production** → submit brand + restricted-scope review.
- [ ] Respond promptly to any follow-ups.

### Step 9 — CASA Tier-2 security assessment ⏳ (third-party assessor, paid by UMN)
See [01-casa-tier-assessment.md](01-casa-tier-assessment.md).
- [ ] Engage a Google-approved assessor (**start early — longest lead time**).
- [ ] Ask UMN security if an existing **SOC 2 / ISO 27001** attestation qualifies for the CASA
      **Accelerator** (expedite/discount).
- [ ] Pass Tier-2: **DAST** scan against production + **ASVS** self-assessment questionnaire.
      Budget **~$500–$1,000**, ~2–3 weeks.
- [ ] Remediate findings → receive **Letter of Validation (LOV)** → submit to Google.

### Step 10 — Post-approval ⬜
- [ ] 100-test-user cap lifts → onboard real subjects (API can't manage test users;
      Console-only — see [07-test-user-management.md](07-test-user-management.md)).
- [ ] **Diarize annual recertification** (new CASA within 12 months of the LOV date).
- [ ] Keep privacy policy / homepage / disclosure in sync with any scope or data-handling change.

---

## External dependencies (own these early)

| Party | For | Steps |
|-------|-----|-------|
| **UMN OIT / central IT** | GCP org ownership, project roles | 0 |
| **UMN DNS / web admin** | Search Console domain verification | 5 |
| **Google Trust & Safety** | Brand + restricted-scope approval | 8 |
| **CASA assessor (paid by UMN)** | Tier-2 security assessment + LOV | 9 |

## Notes / decisions log
- 2026-06-30 — Verified Steps 2–4 complete against the live host (5 scopes; `/` + `/privacy`
  return 200; nginx root/privacy proxy blocks present). Steps 0, 5–9 outstanding.
