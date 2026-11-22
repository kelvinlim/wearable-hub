/** Subject-detail panel helpers (researcher console).

Data management (Export + Backfill) and Paired devices are separate collapsible
sections. Open/closed uses the same "1"/"0" localStorage encoding as Hide PHI
and the Subjects-list filters. Both default closed when the key is unset.
*/

export const DATA_MANAGEMENT_OPEN_KEY = "wh-data-management-open";
export const PAIRED_DEVICES_OPEN_KEY = "wh-paired-devices-open";

/** Pull + consolidate is a synchronous server-side pull; a long range can exceed the
 * gateway timeout, so the console sends it in windows of this many days each. */
export const CHUNK_DAYS = 10;

/** Add `n` days to a "yyyy-mm-dd" string in UTC (avoids local-timezone off-by-one). */
export function addDays(iso, n) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Inclusive [start, end] split into ≤ `chunkDays`-day windows, in order. */
export function chunkDateRange(start, end, chunkDays = CHUNK_DAYS) {
  const windows = [];
  if (!start || !end || end < start) return windows;
  let a = start;
  while (a <= end) {
    let b = addDays(a, chunkDays - 1);
    if (b > end) b = end;
    windows.push({ start: a, end: b });
    a = addDays(b, 1);
  }
  return windows;
}

export function pullProgressNotice(window, index, total) {
  if (!window || total <= 1) return "";
  return `Pulling ${window.start}…${window.end} (${index + 1}/${total})`;
}

/**
 * In-panel status after a pull window fails. Must replace any "Pulling…" text so
 * progress does not look active. `error` is the already-formatted API message.
 */
export function pullFailedNotice({
  window, index, total, completedWindows = [], error = "",
} = {}) {
  if (!window) return error || "Pull failed.";
  const chunk = `${window.start}…${window.end} (${index + 1}/${total})`;
  const n = completedWindows.length;
  let saved;
  if (n === 0) {
    saved = "No windows finished.";
  } else if (n === 1) {
    const w = completedWindows[0];
    saved = `1 of ${total} windows finished (${w.start}…${w.end}).`;
  } else {
    saved = `${n} of ${total} windows finished.`;
  }
  return `Stopped at ${chunk}. ${saved}${error ? ` ${error}` : ""}`;
}

/** `yyyy-mm-dd` → `mm/dd/yyyy` for compact header hints. Empty / non-ISO → "". */
export function formatIsoDateMdY(iso) {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso).trim());
  if (!m) return "";
  return `${m[2]}/${m[3]}/${m[1]}`;
}

function dateRangeHint(from, to) {
  const left = formatIsoDateMdY(from);
  const right = formatIsoDateMdY(to);
  if (left && right) return `${left} → ${right}`;
  if (left) return `${left} → …`;
  if (right) return `… → ${right}`;
  return "";
}

/**
 * One-line reminder on the collapsed Data management header.
 *
 * Prefer the backfill window when that row is actually shown (admin, not archived).
 * Otherwise use export dates if the researcher has set them. Empty string = omit.
 */
export function dataManagementHint({
  start, end, exFrom, exTo, showBackfill = true,
} = {}) {
  if (showBackfill) {
    const backfill = dateRangeHint(start, end);
    if (backfill) return `Backfill ${backfill}`;
  }
  const exported = dateRangeHint(exFrom, exTo);
  if (exported) return `Export ${exported}`;
  return "";
}

/** Quiet collapsed hint: device name if one, otherwise a count. */
export function pairedDevicesHint(devices = []) {
  if (!devices.length) return "";
  if (devices.length === 1) {
    const d = devices[0];
    return d.device_version || d.device_type || "Device";
  }
  return `${devices.length} devices`;
}
