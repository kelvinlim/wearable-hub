/** Subject-detail panel helpers (researcher console).

Data management (Export + Backfill) and Paired devices are separate collapsible
sections. Open/closed uses the same "1"/"0" localStorage encoding as Hide PHI
and the Subjects-list filters. Both default closed when the key is unset.
*/

export const DATA_MANAGEMENT_OPEN_KEY = "wh-data-management-open";
export const PAIRED_DEVICES_OPEN_KEY = "wh-paired-devices-open";

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
