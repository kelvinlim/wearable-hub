# Hide PHI (header display switch)

Design record for a global **Hide PHI** checkbox in the researcher-console SPA
header. Mirrors [kelvinlim/grid-react `HIDE_PHI.md`](https://github.com/kelvinlim/grid-react/blob/main/HIDE_PHI.md)
(shipped there in 0.8.8), adapted to the fields Wearable Hub actually shows.

## Problem

Staff screenshare the Subjects table, walk a tablet through a clinic, or sit in
an open bay. The session API returns **identifiable** subject data — Study IDs
and Google/Fitbit/Oura account labels — and the UI paints them. There is no way
to blank those fields for the *display* without signing out.

## Decision

**Client-side display mask, v1.** A single React context + `localStorage`
(`wearable-hide-phi`, `"1"` / `"0"`, same persistence style as `wh-dark`).
Default **off** (show PHI). Every `/admin/subjects` (and export) response stays
identifiable. The UI substitutes masked strings at render time.

This is **not network-level protection**. DevTools, the HAR, a downloaded JSON
export of the raw API payload, or another tab that has not ticked the box will
still see Study IDs and account labels. Hide PHI is for shoulder-surfing and
screenshare, not for a hostile client.

Do **not**:

- Redact the session API (that is a later pass; see Out of scope).
- Hide researcher names, study names, PI / IRB fields, or study-staff emails.
- Mask subject create/edit form inputs (staff have to type the real Study ID
  and account label to save).

## UI placement

Global checkbox in the top header of
[frontend/src/components/Layout.jsx](frontend/src/components/Layout.jsx),
**to the left of the version**, on every researcher-console page (studies,
subjects, subject detail, researchers, Google projects, about — no-op on pages
with no subject identifiers).

Order:

```
[Hide PHI]   v{version}   [dark-mode moon]
```

Label: **Hide PHI**. Native checkbox, compact `text-xs` so it sits with the
version. The control is always visible; it does not follow role.

## What Wearable Hub actually shows as PHI

Unlike GRID, this console has no first/last name, date of birth, MRN, or SSN
columns. The subject-identifying fields it paints are:

| Field | What it is | When Hide PHI is on |
| --- | --- | --- |
| `participant_id` ("Study ID") | The study's own subject identifier | Blank (`—`) |
| `subject_label` ("Label") | Google / Fitbit / Oura account label | `su-{id}` (GRID-style display-id fallback) |
| Read-only titles, delete confirms, export **filenames** | Built from Study ID or label | `su-{id}` |
| Subject create/edit **form inputs** | Staff data entry | Unmasked |
| Study-wide CSV `subject_label` / `participant_id` columns | Visible identifier columns | label → `su-{id}`; Study ID blanked |
| JSON export body | Raw API payload | Unchanged |
| Entry codes, health metrics, collection-window dates | Operational / clinical measures, not names | Unchanged |
| Staff / researcher names, study names, PI, IRB # | Not subject PHI | Unchanged |

Helpers live in one module
([frontend/src/utils/phi.js](frontend/src/utils/phi.js)) so every surface
applies the same functions.

## Page inventory

| Page | What Hide PHI changes |
| --- | --- |
| Header (all views) | Checkbox; preference shared via `PhiPrivacyContext`. Version shown next to it. |
| Subjects list | Study ID → `—`; Label → `su-{id}`. |
| Subjects create form | Unmasked (staff entry). |
| Subjects edit modal | Inputs unmasked; the read-only title chip is masked. |
| Subject detail | Heading uses `su-{id}`; download filenames use `su-{id}`. JSON/CSV **bodies** of the per-subject export are the raw payload (no identifier columns). |
| Studies → study-wide CSV | Identifier columns follow the mask. JSON body unchanged. Filename is the study name (not subject PHI). |
| Researchers, Google projects, About, study settings / members | Toggle visible; nothing to mask. |

## Why not the alternatives

**Server-side session redaction:** would actually keep identifiers off the wire.
It also breaks subject create/edit (the form round-trips the row the list just
fetched). That is a different product decision. v1 is display-only on purpose.

**Reuse PAT / credential-level pseudonymization:** Wearable Hub has no PAT
`mode_ceiling`. Wrong lifetime and wrong UI even if it did.

## State

- Key: `wearable-hide-phi` (`"1"` on, `"0"` / absent off).
- Default off.
- Context: `PhiPrivacyProvider` in Layout so every child view sees one switch
  without prop-drilling. Isolated tests that do not mount Layout get
  `hidePhi: false`.
- Survives refresh and sign-out (it is a machine preference, like dark mode),
  not a per-user server setting.

## Tests

- Helpers (`frontend/src/utils/phi.test.js`, `node --test`): name fallback,
  Study ID blanking, export basename, study-CSV identifier columns.
- Study CSV writers (`frontend/src/lib.csv.test.js`): `studyDailyCsv` /
  `studyPointsCsv` keep identifiers when off and mask them when on; entry
  codes stay.
- No Layout/RTL harness in this repo yet (GRID had vitest; Wearable Hub's
  frontend CI is a Vite build + these helper files).

## Docs / version

- Version **0.8.0** (`frontend/package.json`, `backend/pyproject.toml`,
  `backend/app/config.py`).
- `frontend/CHANGELOG.md` entry (screenshare / shoulder-surf, not a new
  access-control mode).
- This file is the design record.

## Out of this pass

- API redaction for session users.
- Hiding researcher / study-staff names, study names, or PI.
- Stripping identifiers from raw JSON export bodies.
- Remembering the preference per Google account on the server, if two people
  share a browser.
