# Test: can restricted health scopes run in Production **unverified** (≤100 users)?

**Goal.** Settle the open question in [STATUS.md](STATUS.md#-decision-gate--do-we-even-need-full-verification-read-first):
does Google let a **non-test user** complete the health-data consent when the app is **In
production** but **not verified**? If yes, a study with ≤100 subjects can skip verification + CASA.
If Google blocks it, restricted-scope production requires full verification.

**Time:** ~5–10 minutes. **Who:** anyone with **Owner/Editor** on the GCP project.

---

## ⚠️ Read first — the cost of the test
The 100-user cap **counts over the project's lifetime and cannot be reset**. Any real grant the
test account makes **permanently consumes one of the 100 slots** on that project.

- **Recommended:** run this on a **throwaway GCP project** (new project → enable the Google Health
  API → configure the consent screen with **one** restricted health scope → one OAuth client) so the
  real study project's budget is untouched. More setup, zero risk to production.
- **Quicker but costs a slot:** run it on the real project `fitbitdata-499001` and accept spending
  1 of 100 (99 would remain). Fine if enrollment will be well under 100.

You only need to reach/pass the **consent grant** to get the answer — the account does **not** need a
paired Fitbit or any health data.

---

## Steps

Console UI note: OAuth settings now live under **Google Auth Platform** (left nav in
`console.cloud.google.com`). Older projects may still show **APIs & Services → OAuth consent
screen**; the same controls (publishing status, test users, scopes) are there.

1. **Pick the project.** Open [console.cloud.google.com](https://console.cloud.google.com) and select
   the target project (throwaway, or `fitbitdata-499001`).
2. **Confirm the scope is restricted.** *Google Auth Platform → Data Access* (old UI: OAuth consent
   screen → scopes). Confirm at least one `…/auth/googlehealth.*.readonly` scope is present — these
   are **Restricted**.
3. **Confirm you're starting in Testing.** *Google Auth Platform → Audience.* Publishing status
   should read **Testing**.
4. **Publish to production (do NOT verify).** On the **Audience** page click **Publish app** →
   confirm. Status becomes **In production**.
   - You may see a prompt to "prepare for verification" — **ignore it. Do not open the Verification
     Center and do not submit.** The app is now *In production, unverified* — exactly the state to
     test.
5. **Use a NON-test-user account.** Open an **incognito** window and sign into a Google account that
   is **not** on the project's test-user list (a personal/secondary account).
6. **Run the enroll flow.** Go to the app's enrollment page (prod: `https://lnpitask.umn.edu/enroll`),
   enter a valid **entry code**, and proceed until Google's OAuth consent appears.
7. **Read the result** (this is the answer):
   - ✅ **Allowed** — you see *"Google hasn't verified this app"*, can click **Advanced → Go to … (unsafe)**,
     then reach the **health-scope grant** screen and complete it (redirects back with a code).
     → **≤100 unverified-production works for restricted health scopes.**
   - ❌ **Blocked** — you see *"Access blocked: … has not completed the Google verification process"*
     (or similar) with **no way to proceed**.
     → **Restricted-scope production requires full verification + CASA;** the only no-verification
     option is Testing mode (manual email allowlist, 7-day tokens).

## Record & revert
- Screenshot the exact screen and copy the **verbatim** message (esp. any "Access blocked" text).
- Optional: on the **Audience** page, **Back to testing** to restore Testing status.
- Note whether a user slot was consumed (Audience page user count) if you used the real project.

## Corroborate
Whatever the screen shows, also confirm in writing with **Google Health API support / the OAuth
verification team** before committing the study to that path — this test reflects current Console
behavior, not a policy guarantee.
