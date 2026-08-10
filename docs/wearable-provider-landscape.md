# Wearable provider landscape — validation + API survey

Which commercial wearables are (a) validated well enough to carry a research endpoint and
(b) expose an API this hub can actually receive data from. Written 2026-08-04, after Oura
shipped as the third provider. Vendor terms and APIs move fast — re-check before committing
to one in a protocol (the legacy Fitbit Web API sunset in Sept 2026 is the cautionary case).

**Currently integrated:** Fitbit (via Google Health), Garmin, Oura. See
[CLAUDE.md](../CLAUDE.md) for how each provider module works.

## The shortlist at a glance

| Device | Server API | Auth | Push | Fits this hub? |
|---|---|---|---|---|
| **Whoop** | yes | OAuth2 + refresh (`offline` scope) | webhooks (v2; v1 removed) | Drop-in — closest analogue to Oura |
| **Withings** | yes (+ raw-data Research API) | OAuth2 + refresh | webhook subscription | Drop-in — shape resembles Oura |
| **Polar** | yes (AccessLink) | OAuth2 | webhooks | Drop-in |
| **Empatica EmbracePlus** | yes (cloud-to-cloud) | vendor-issued | — | Yes, but priced for pharma trials |
| **ActiGraph CentrePoint** | yes (V3, raw sub-second) | vendor-issued | — | Yes; research-grade criterion device |
| **Apple Watch** | **no** | — | — | **No** — needs a participant iOS app |
| **Samsung** | **no** (on-device SDK) | — | — | **No** — needs a participant Android app |

## Drop-in candidates (cloud API, OAuth2, webhooks)

These are genuine siblings of the Fitbit/Oura modules: a server-side API callable with a user
token, so the entry-code → OAuth → webhook → pull flow works unchanged.

### Whoop
OAuth2 with refresh tokens (request the `offline` scope), webhooks for new-data notification,
published rate limits with `X-RateLimit-*` headers. Covers sleep, recovery, strain, HRV; common
in sleep and training-load research.

- **Caution:** the headline accuracy numbers (99.7% HR, 99% HRV) are **vendor-run**, not
  independent replication.
- **Recruitment cost:** participants need an active Whoop membership.

### Withings — strongest clinical fit
OAuth2 plus a webhook subscription model close to Oura's. Different device family: cleared
blood-pressure monitors, smart scales, a **contactless under-mattress sleep mat** (passive
adherence — nothing to wear or charge), and watches.

- Most clinical validation record of the consumer vendors: AF detection, automated QT
  intervals, BP accuracy.
- Publishes an **Advanced Research API** for research institutions exposing **raw sensor data**
  — 25 Hz accelerometry (up to 100 Hz) and multi-LED PPG. Unusual for a consumer vendor; closes
  most of the gap to research-grade hardware.
- One independent lab study found only adequate HR at low activity and adequate steps at higher
  activity — i.e. the wrist devices are ordinary; the cleared BP/scale/sleep-mat products are
  the draw.

### Polar
AccessLink API with an explicit research-tools program. The chest straps and arm bands (H10,
Verity Sense, OH1) are about as close to criterion-grade HR as consumer hardware gets and are
frequently used *as* the comparison device in validation studies. The accuracy pick when the
science is exercise physiology or HR/HRV rather than free-living behavior.

## Research- and clinical-grade (cloud API, higher cost)

### Empatica EmbracePlus
FDA-cleared and CE MDR certified, cloud-to-cloud API, 21 CFR Part 11 / HIPAA / GDPR compliance,
audit trails, prepared IRB submission packages. Measures **EDA and skin temperature** alongside
PPG, reaching autonomic arousal, stress, and seizure detection — which none of the consumer
devices touch. Six measures carry direct FDA clearance within a 300+ measure library. Scoped and
priced for pharma trials rather than investigator-initiated studies.

### ActiGraph CentrePoint
The actigraphy reference standard. V3 API serves **raw sub-second acceleration** from the cloud,
uploaded via a cellular home hub or participant app; 30+ day battery. Worth knowing about as the
**criterion device** if we ever need to validate consumer devices within our own cohort.

## The gap: Apple and Samsung

Neither can be integrated the way this hub works. Worth knowing before either is promised in a
grant.

- **Apple Watch** has arguably the best independent validation of any consumer device (a *living*
  systematic review and meta-analysis in npj Digital Medicine tracks it continuously). But Apple
  runs **no cloud service aggregating HealthKit data** — there is no server to call with a user
  token. Data sits on the participant's phone and only leaves if an iOS app we build reads and
  uploads it. Supporting it means building and maintaining a participant-facing iOS app
  (typically ResearchKit) plus App Store review — a separate project, not another provider module.
  Raw ECG is not exposed via HealthKit at all.
- **Samsung** is nearly the same: the Health Data SDK is an **on-device Android SDK** (plus a
  Research Stack for study logistics). There's an auth server, but no general third-party server
  API for pulling a participant's data, and approval for research/clinical use cases moves more
  slowly than for consumer apps. Also needs a companion mobile app.

## Alternative strategy: aggregators

Terra, Rook, Vital, Validic, Thryve, Junction/Spike sell **one integration** fanning out to
hundreds of devices with a normalized schema and webhook delivery, handling token refresh and
vendor quirks.

Trade-offs that matter here:

- Recurring cost.
- Normalized data is usually **coarser than the vendor's raw feed** — we'd lose things like
  Oura's 5-minute HRV series.
- A **third party in the path of identifiable health data** → BAA or DUA, plus an IRB amendment.

Given three provider modules already exist and a fourth is now cheap, an aggregator is only
worth it if we need broad device choice across many studies at once.

## On the word "validated"

The umbrella reviews are more sober than vendor marketing. Carry these into protocol design:

| Metric | Independent finding |
|---|---|
| **Heart rate** | Strong across devices — ~±3% mean bias |
| **Steps** | Decent; ~−9% to +12% error, underestimation the norm |
| **Energy expenditure** | **Insufficient validity** (−21% to +15%) — do not build an endpoint on it |
| **Sleep duration** | Systematically **overestimated** by >10% |
| **Sleep staging** | Only fair→moderate (see below) |

Sleep-staging agreement with polysomnography: Pixel Watch, Galaxy Watch 5, and Fitbit Sense 2
reach **moderate** (κ 0.4–0.6); Apple Watch 8 and **Oura Ring 3** reach only **fair** (κ 0.2–0.4).
That last point applies to the provider we just shipped — Oura's staging is fair, not moderate.

The reviews also note pervasive heterogeneity in validation methodology, so cross-study accuracy
comparisons should be treated cautiously.

## Recommendation

- **Cardiovascular / BP / sleep with adherence concerns → Withings.** The research API and
  passive sleep mat are unmatched, and its OAuth2 + webhook shape means the module would closely
  resemble `app/providers/oura.py`.
- **Recovery / training load / HRV in a younger cohort → Whoop.**

Either is a smaller lift than Oura was: enrollment dispatch, the per-provider consolidation
queue, and the console wiring are now generic. Check each vendor's API terms first — several
restrict research or commercial use in ways the landing page doesn't advertise.

## Sources

- WHOOP: [developer platform](https://developer.whoop.com/docs/introduction/) ·
  [OAuth 2.0](https://developer.whoop.com/docs/developing/oauth/) ·
  [rate limiting](https://developer.whoop.com/docs/developing/rate-limiting/)
- Withings: [Advanced Research API](https://developer.withings.com/developer-guide/v3/withings-solutions/research-apis/) ·
  [OAuth web flow](https://developer.withings.com/developer-guide/v3/integration-guide/public-health-data-api/get-access/oauth-web-flow/) ·
  [research publications](https://www.withings.com/us/en/research)
- Polar: [research tools](https://www.polar.com/en/science/research-tools/) ·
  [OH1 HR validation](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8088863/)
- Empatica: [Cloud API](https://www.empatica.com/cloud-api/) ·
  [FDA clearance](https://www.empatica.com/blog/the-empatica-health-monitoring-platform-receives-fda-clearance) ·
  [EmbracePlus pulse-oximeter validation](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10726006/)
- ActiGraph: [CentrePoint V3 API docs](https://github.com/actigraph/CentrePoint3APIDocumentation)
- Apple: [ResearchKit & CareKit FAQ](https://www.researchandcare.org/faq/) ·
  [Apple Watch accuracy — living systematic review](https://www.nature.com/articles/s41746-025-02238-1)
- Samsung: [Health Data SDK](https://developer.samsung.com/health/data)
- Validation overview: [Keeping Pace with Wearables — living umbrella review](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11560992/)
- Aggregators: [The Wearables Interoperability Stack](https://healthapiguy.substack.com/p/the-wearables-interoperability-stack)
