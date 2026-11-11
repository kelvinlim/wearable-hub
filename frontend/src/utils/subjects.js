/** Subjects-list filters that compose with the server-side archive flag.

Show archived is applied by `GET /admin/studies/{id}/subjects?include_archived=…`.
Show registered is client-side on the `registered` (linked) flag already on each row.
Both on is an intersection of the two.
*/

// Console UI prefs: same "1"/"0" localStorage encoding as Hide PHI (`wearable-hide-phi`)
// and dark mode (`wh-dark`). `wh-*` matches the other researcher-console layout keys
// (`wh-view`, `wh-study`, `wh-dark`).
export const SHOW_REGISTERED_KEY = "wh-show-registered";
export const SHOW_ARCHIVED_KEY = "wh-show-archived";
export const EXPORT_OPEN_KEY = "wh-export-open";

/** Read a "1"/"0" flag. Missing key → `defaultOn` (Show registered/archived off; Export open). */
export function readStoredFlag(key, defaultOn = false, store = globalThis.localStorage) {
  if (!store) return defaultOn;
  const v = store.getItem(key);
  if (v == null) return defaultOn;
  return v === "1";
}

export function writeStoredFlag(key, on, store = globalThis.localStorage) {
  if (!store) return;
  store.setItem(key, on ? "1" : "0");
}

export function filterSubjectList(subjects, { showRegistered = false } = {}) {
  if (!showRegistered) return subjects;
  return subjects.filter((s) => s.registered);
}
