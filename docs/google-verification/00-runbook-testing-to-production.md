# Runbook: Testing → Production

End-to-end checklist to move GCP project `fitbitdata-499001` from Google's Testing mode (≤100 test
users) to a verified production app. Order matters: get the live URLs and disclosure in place
*before* submitting, because Google's reviewer checks them.

Brand verification typically clears in ~2–3 business days; restricted-scope review plus the CASA
assessment takes several weeks. Plan for **4–8 weeks** end to end.

---

## Step 0 — Pre-work (ownership & contacts)

- [ ] Confirm `fitbitdata-499001` lives under the **UMN Google Cloud organization** (not a personal
      account). If it doesn't, involve UMN central IT / OIT to bring it under the org. This may be
      required for both branding and for any org-level OAuth allow-listing UMN enforces.
- [ ] On the **OAuth Branding** page, set the app name (e.g. "University of Minnesota Wearable Hub"),
      the **support email**, and a **developer contact email** — both should be `umn.edu` addresses
      and monitored (Google sends verification + annual-recertification notices there).
- [ ] Confirm current **Owner/Editor** roles on the project for whoever will submit and respond to
      the assessor.

## Step 1 — Study contact (done)

Filled in across `backend/app/routers/public.py` and these docs:
- PI: **Kelvin O. Lim** · Support/privacy: **kolim@umn.edu** · IRB: **STUDY00026668**

Update those values if the study contact changes.

## Step 2 — Decide the scope set (least privilege) — done

- [x] **`ecg.readonly`** and **`irn.readonly`** removed from `GOOGLE_HEALTH_SCOPES` in `.env` (no
      in-product use today; Google rejects unused restricted scopes). Re-enroll test users so their
      grants match the trimmed scope set. (See [02-scope-justifications.md](02-scope-justifications.md).)

## Step 3 — Publish the live homepage + privacy policy {#step-3}

The app already serves these (`backend/app/routers/public.py`):
- `GET /` → homepage  → consent screen **Home Page URL** `https://lnpitask.umn.edu/`
- `GET /privacy` → privacy policy → consent screen **Privacy Policy URL** `https://lnpitask.umn.edu/privacy`

- [ ] Add the `location = /` and `location = /privacy` proxy blocks to the **lnpitask host nginx**.
      The version-controlled source is [`deploy/nginx/wearable-hub.conf`](../../deploy/nginx/wearable-hub.conf)
      — merge its blocks into the existing lnpitask `server { … }` (which already terminates TLS).
      Then `sudo nginx -t && sudo nginx -s reload`.

> Note `location = /` and `location = /privacy` are exact matches, so they won't shadow `/enroll`,
> `/webhooks/…`, or `/wearable/`.

- [ ] Confirm both URLs load publicly (incognito, not behind any login) and are on the **same
      domain** as each other — a hard Google requirement.

## Step 4 — Ship the in-app disclosure + redeploy

The prominent disclosure is already on the `/enroll` form (see
[06-in-app-disclosure.md](06-in-app-disclosure.md)).

- [ ] Rebuild and restart the backend so all of Step 3/4 is live:
      `sudo -E podman build -t localhost/wearable-backend:latest ./backend` then
      `sudo systemctl restart wearable-backend.service`.
- [ ] Spot-check `/enroll` shows the disclosure block with a working link to `/privacy`.

## Step 5 — Verify domain ownership

- [ ] In **Google Search Console**, verify ownership of `lnpitask.umn.edu` using a Google account
      that has Owner/Editor on the project. (May need UMN DNS / web admin to add the verification
      record.)

## Step 6 — Configure consent screen + scopes in Cloud Console

- [ ] Set User type = **External**, publishing status work-in-progress.
- [ ] Confirm app name, logo, support email, home page, privacy policy, and authorized domains
      (`umn.edu`) are accurate.
- [ ] Add the scopes; for each restricted scope paste the justification from
      [02-scope-justifications.md](02-scope-justifications.md). Be specific — vague or duplicated
      justifications cause delays.

## Step 7 — Record the demo video

- [ ] Record per [05-demo-video-script.md](05-demo-video-script.md): app name on the consent screen,
      client ID visible in the address bar, each restricted scope exercised, in-app disclosure shown.
- [ ] Upload to YouTube as **Unlisted**; put the link in the submission.

## Step 8 — Submit for verification

- [ ] In the **OAuth Verification Center**, set the app to **In production** and submit for brand +
      restricted-scope verification. Respond promptly to any Trust & Safety follow-ups.

## Step 9 — CASA Tier-2 security assessment

See [01-casa-tier-assessment.md](01-casa-tier-assessment.md) for detail.

- [ ] Get assigned / choose a Google-approved assessor.
- [ ] Pass the **Tier-2** review: DAST scan against the production app + ASVS self-assessment
      questionnaire. Budget **$500–$4,500** and ~2–3 weeks.
- [ ] Receive the **Letter of Validation (LOV)**; submit it to Google.

## Step 10 — Post-approval

- [ ] Once approved, the 100-test-user cap no longer applies — onboard real subjects.
- [ ] **Diarize annual recertification**: a new CASA assessment is due within 12 months of the LOV
      date. Google emails the support/developer contacts when it's due.
- [ ] Keep the privacy policy, homepage, and disclosure in sync with any scope or data-handling
      changes.
