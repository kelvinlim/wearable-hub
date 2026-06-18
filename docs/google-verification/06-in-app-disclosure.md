# In-App Disclosure

Google's Health/restricted-scope policy requires a **prominent in-app disclosure** of data access
that:

- appears **within the app during normal use** (not only in the privacy policy, terms, or app
  description);
- **describes what data is accessed and how it's used or shared**;
- is **not grouped** with unrelated disclosures;
- is shown **before or at the point** the user authorizes data access.

Recommended format from Google: *"{App name} collects health and fitness data to enable {feature},
{feature}, and {feature}."*

## Where it lives

On the `/enroll` page, immediately above the data-sharing consent flow — shown before the participant
is redirected to Google. Implemented in `backend/app/routers/enroll.py` (the `enroll_form` body, in a
`.disclosure` styled block). It links to the live `/privacy` page.

## The disclosure text (as shipped)

> University of Minnesota Wearable Hub collects your activity, sleep, heart-rate, blood-oxygen
> (SpO2), heart-rate-variability, and wearable-device information (such as battery level and last
> sync) from your connected Google/Fitbit account to support the research study you enrolled in. Your
> data is used only by the research team for this study and is never sold or used for advertising.
> See our Privacy Policy for details.

## Why it's worded this way

- **Names the specific data categories** (activity, sleep, heart rate, SpO2, HRV, device info) — maps
  to the requested scopes, so a reviewer can match disclosure ↔ scopes ↔ demo.
- **States the purpose** ("to support the research study you enrolled in").
- **States non-use** ("never sold or used for advertising") — aligns with Limited Use.
- **Links to the full policy** rather than relying on it for the disclosure.

## Keep in sync

If the scope set changes (e.g. ECG/IRN added or removed), update **all three** in lockstep: this
disclosure (`enroll.py`), the privacy policy (`public.py` + `03-privacy-policy.md`), and the scope
justifications (`02-scope-justifications.md`).
