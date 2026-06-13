# UI redesign — UMN-branded CRMS-style console

Redo the researcher console's look & feel to match the **chan_cras CRMS** app
(`style/cras_study_screenshot.jpeg`) but with **University of Minnesota branding**
(Description.md items 9–10).

## Decisions (confirmed)

- **Stack:** add **Tailwind CSS v4** (`@theme` tokens) + **lucide-react** icons + `clsx`/`tailwind-merge`
  to the existing React (JS) frontend. Stay in JS (no TypeScript). Backend untouched.
- **Structure:** multi-section **sidebar nav** (Studies / Subjects / Researchers / About) with the
  selected study in the **header dropdown** — like the reference screenshot.
- **Typography:** **Open Sans** body + **Poppins** display/headings (≈ UMN's Neutraface), headings in maroon.
- **Dark mode:** header Moon/Sun toggle, `dark:` variants, persisted in `localStorage`.

## Branding

- UMN **Maroon `#7A0019`** (primary: sidebar, headings, primary buttons), a darker maroon for
  sidebar depth; **Gold `#FFCC33`** (accent: avatar, highlights, "linked" badge). Source:
  umarcomm.umn.edu/resources/colors-and-type.
- Logo: maroon block "M" + *Wearable Hub* wordmark placeholder (no trademarked UMN asset fabricated;
  drop an official SVG/PNG into `src/assets/` to swap later).

## Layout (`src/components/Layout.jsx`)

- `flex h-screen`. **Collapsible maroon sidebar** (w-64 / w-20): logo block, lucide icon nav
  (active = `bg-white/15 font-bold`, hover `bg-white/10`), footer = collapse toggle + gold avatar +
  email + role + logout.
- **Header** (white / `dark:`): page title (Poppins, maroon) + study-selector dropdown (shown for
  Subjects/Members/Export) + dark-mode toggle.
- **Content**: `bg-gray-50 dark:bg-neutral-950`, white rounded cards.

## Views (driven by `currentView` state in `App.jsx`; no router)

- **Studies** — list + create (superuser); for the selected study: settings (intraday-HR opt-in),
  **members** (study-admin), **whole-study export** (From/To + JSON/CSV).
- **Subjects** — study picked in the header; CRMS-style table (label · entry code · status · linked
  badge · actions) + "Add subject" → row click → **detail** (daily table, day-expansion HR/sleep,
  per-subject export, consolidate/revoke; admin-gated actions).
- **Researchers** (superuser) — users table + add/delete.
- **About / Enroll ↗**.
- **Login** — reskinned maroon card ("Sign in with Google").

## Files

- `package.json` (+ tailwindcss, @tailwindcss/vite, lucide-react, clsx, tailwind-merge);
  `vite.config.js` (+ Tailwind plugin, keep `base:/wearable/`); `index.html` (+ Google Fonts).
- New: `src/index.css` (Tailwind + `@theme` + dark base), `src/components/Layout.jsx`,
  `src/views/{StudiesView,SubjectsView,ResearchersView,LoginView}.jsx`, `src/ui/` (Card, Table,
  Button, Badge, Field). Refactor `App.jsx` (auth + currentView + selected study + theme).
- Retire `src/styles.css`. `api.js` unchanged.

## Preserve (re-themed, not removed)

studies/subjects CRUD · members · daily table · day-expansion (sleep stages + HR buckets) ·
per-subject + whole-study export (JSON / CSV daily / CSV points) · per-study intraday-HR opt-in ·
RBAC-gated UI (superuser / study-admin / member) · login + logout.

## Verify

Tailwind build compiles in the Docker image; SPA serves at `/wearable/`; sidebar switches views;
header study selector scopes Subjects; dark mode toggles + persists; existing API flows return data
(studies, subjects, daily, points, export, members, users, study PATCH). Final visual check is
in-browser by the user (agent can't render). Then commit + push.
