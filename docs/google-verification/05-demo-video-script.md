# Demo Video Script

Google's restricted-scope review requires a demonstration video showing the full OAuth grant/consent
flow and how each restricted scope is used. Record in **English**, upload to **YouTube as Unlisted**,
and include the link in the submission.

## Hard requirements (Google checks for these)

- The **OAuth consent screen** is shown, displaying the **correct app name** ("University of
  Minnesota Wearable Hub").
- The **OAuth client ID** is visible in the **browser address bar** during the grant flow (don't crop
  the URL bar; the `client_id=569496656627-…` parameter must be readable on the
  `accounts.google.com` consent URL).
- Each **restricted scope** is shown being used functionally in the app.
- The flow is recorded against the **production** app on `https://lnpitask.umn.edu`.

## Suggested shot list

1. **Homepage (00:00)** — Open `https://lnpitask.umn.edu/`. Show the app name and the description of
   what it does and who it's for. Narrate: "This is the University of Minnesota Wearable Hub research
   app."

2. **Privacy policy (00:15)** — Click through to `/privacy`. Show it's on the same domain and covers
   data use, Limited Use, storage, and deletion.

3. **In-app disclosure (00:30)** — Go to `/enroll`. Read the prominent disclosure block aloud — it
   names the data collected (activity, sleep, heart rate, SpO2, HRV, device info) and that it's used
   only for the research study. (Satisfies the in-app-disclosure requirement.)

4. **Start the grant (00:45)** — Enter a test study code and click Continue. The browser redirects to
   Google. **Pause so the address bar is clearly visible** — show the `accounts.google.com` URL with
   the `client_id`.

5. **Consent screen (01:00)** — Show the consent screen with the app name "University of Minnesota
   Wearable Hub" and the list of permissions being requested. Approve.

6. **Per-scope usage (01:15)** — Back in the researcher console (`/wearable/`), show data that
   demonstrates each restricted scope is actually used:
   - **activity_and_fitness** → daily steps / distance / calories / floors / exercise.
   - **sleep** → sleep duration and the sleep-stage breakdown.
   - **health_metrics_and_measurements** → resting HR, HRV, and SpO2 values.
   - **profile** + **settings** → the paired-device panel (model, battery, last sync).

7. **Withdrawal (02:00)** — Briefly show how a participant's access is revoked (console revoke button
   or Google Account "remove access"), demonstrating data-deletion-on-request.

## Tips

- Use a **test subject** in a test study; don't show real participant data.
- Keep it tight (2–3 minutes) but don't sacrifice the two non-negotiables: **app name on the consent
  screen** and **client ID in the address bar**.
- If scopes were trimmed (ECG/IRN removed), make sure the consent screen in the video matches the
  scopes you submitted.
