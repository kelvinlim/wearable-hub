# Test-user management (the "audience") — no API exists

While the app is in **Testing** publishing status, only **test users** added to the OAuth consent
screen can complete the OAuth flow, capped at **100**. A recurring operational question is whether
that list can be managed programmatically (script enrollment, sync from a study roster, bulk
add/remove). **It cannot.**

## Finding (researched 2026-06-18)

There is **no supported way to query, add, or delete test users / audience members
programmatically.** Test-user management on the **Google Auth Platform → Audience** page
(`https://console.developers.google.com/auth/audience`) is **Cloud Console UI only**:

- ❌ No `gcloud` command
- ❌ No REST / Admin API endpoint
- ❌ No Terraform resource
- ✅ Cloud Console UI only (manual add/remove, ≤100)

This is a long-standing gap, confirmed against the current Google Cloud docs.

### Don't be misled by the IAP OAuth commands

`gcloud … iap oauth-brands` / `iap oauth-clients` and the Terraform `google_iap_brand` /
`google_iap_client` resources look related but are **not** this — they manage **Identity-Aware
Proxy** OAuth brands/clients, not consent-screen test users. They're also **deprecated**: the IAP
OAuth Admin APIs were **shut down in March 2026**, so that path is dead regardless.

## Implications for this project

- The 100-test-user cap and the manual Console workflow are a hard constraint **for as long as we
  stay in Testing**. There is nothing to automate or build here.
- The only way off the manual list is to **reach Production** via the verification + CASA process
  in this folder — see [00-runbook-testing-to-production.md](00-runbook-testing-to-production.md).
  Once approved and published, the test-user list becomes irrelevant: any consumer Google account
  can authorize, with no per-user allow-listing (runbook Step 10).
- **"Internal" user type** would also remove the test-user list, but only works if every subject is
  a member of the UMN Google Workspace org. Research subjects sign in with personal
  Google/Fitbit accounts, so Internal does not apply (this is why the app must be **External** —
  see the [README](README.md) "Why verification is required").

## Practical guidance while in Testing

- Add/remove test users by hand on the Audience page; keep the roster well under 100.
- Remember each test user must also be **re-enrolled** if the scope set changes (runbook Step 2).
- Treat the 100 cap as a reason to prioritize the production review, not as something to engineer
  around.

## Sources

- [Manage App Audience — Cloud Console Help](https://support.google.com/cloud/answer/15549945?hl=en)
- [Configure the OAuth consent screen — Google for Developers](https://developers.google.com/workspace/guides/configure-oauth-consent)
- [Programmatically creating OAuth clients for IAP](https://cloud.google.com/iap/docs/programmatic-oauth-clients)
  (context for the deprecated IAP commands — not test-user management)
