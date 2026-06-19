# Google OAuth Verification — wearable-hub

These documents are the working pack for taking the Wearable Hub app
(GCP project `fitbitdata-499001`) from Google's **Testing** mode to **production** so real
research subjects — who sign in with their own consumer Google/Fitbit accounts — can enroll.

## Why verification is required

The app requests **Restricted** Google Health scopes (`googlehealth.*.readonly`). Because subjects
are *not* `umn.edu` Workspace users, the OAuth consent screen must be **External**, so the
"Internal Workspace" exemption does not apply. Google therefore requires full verification:
brand/OAuth review, per-scope justification, a prominent in-app disclosure, a live homepage +
privacy policy on the same domain, a demo video, and an annual **CASA Tier-2** security assessment.

**Who does what:** *You / the UMN study team* own GCP project `fitbitdata-499001` and submit the
app. *Google's Trust & Safety team* approves the brand/scope review. An *independent, Google-approved
third-party assessor* (paid by UMN, not Google) performs the CASA security assessment. *UMN* owns the
project, the `lnpitask.umn.edu` domain, and pays the assessor. Google does the verifying; UMN does
not.

## Contents

| File | What it covers |
|------|----------------|
| [00-runbook-testing-to-production.md](00-runbook-testing-to-production.md) | End-to-end checklist, Testing → Production |
| [01-casa-tier-assessment.md](01-casa-tier-assessment.md) | Why Tier 2, cost, timeline, assessors, recertification |
| [02-scope-justifications.md](02-scope-justifications.md) | Paste-ready Cloud Console justification per scope |
| [03-privacy-policy.md](03-privacy-policy.md) | Privacy-policy text (mirror of the live `/privacy` page) |
| [04-homepage-content.md](04-homepage-content.md) | Homepage copy (mirror of the live `/` page) |
| [05-demo-video-script.md](05-demo-video-script.md) | Shot list for the required consent-flow demo video |
| [06-in-app-disclosure.md](06-in-app-disclosure.md) | The prominent in-app disclosure string + placement |
| [07-test-user-management.md](07-test-user-management.md) | Why test users / the audience can't be managed by API — Console-only |

## Study contact (filled in)

The drafts and the live pages use these values (update them here, in
`backend/app/routers/public.py`, and in the docs if the contact changes):

- **PI:** Kelvin O. Lim
- **Support / privacy contact:** kolim@umn.edu
- **IRB approval:** STUDY00026668

## Live URLs (already wired into the app)

- Homepage: `https://lnpitask.umn.edu/` — served by `backend/app/routers/public.py`
- Privacy policy: `https://lnpitask.umn.edu/privacy` — served by the same router
- In-app disclosure: shown on `https://lnpitask.umn.edu/enroll`

> **Host step still required:** the lnpitask host nginx must proxy `/` and `/privacy` to the
> backend. The location blocks are tracked in
> [`deploy/nginx/wearable-hub.conf`](../../deploy/nginx/wearable-hub.conf); merge them into the
> host's existing lnpitask server block and reload nginx (see
> [00-runbook step 3](00-runbook-testing-to-production.md#step-3)).
