/** Participant coverage calendar (researcher console).

Filters persist with the same localStorage style as Hide PHI and the Subjects
list: `wh-*` keys, booleans as `"1"` / `"0"`. The date-range mode is the
string `7d` | `all` | `custom` (default `7d`). Active-only is the default.
*/

import { readStoredFlag, writeStoredFlag } from "./subjects.js";

export const COVERAGE_ARCHIVED_KEY = "wh-coverage-include-archived";
export const COVERAGE_RANGE_KEY = "wh-coverage-range";
export const COVERAGE_START_KEY = "wh-coverage-start";
export const COVERAGE_END_KEY = "wh-coverage-end";
export const SUBJECTS_MODE_KEY = "wh-subjects-mode";

const RANGES = new Set(["7d", "all", "custom"]);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = "MTWTFSS";

export function readCoverageRange(store = globalThis.localStorage) {
  if (!store) return "7d";
  const v = store.getItem(COVERAGE_RANGE_KEY);
  return RANGES.has(v) ? v : "7d";
}

export function writeCoverageRange(range, store = globalThis.localStorage) {
  if (!store || !RANGES.has(range)) return;
  store.setItem(COVERAGE_RANGE_KEY, range);
}

export function readIsoPref(key, store = globalThis.localStorage) {
  if (!store) return "";
  const v = store.getItem(key);
  return v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : "";
}

export function writeIsoPref(key, iso, store = globalThis.localStorage) {
  if (!store) return;
  if (!iso) store.removeItem(key);
  else store.setItem(key, iso);
}

export function readIncludeArchived(store = globalThis.localStorage) {
  return readStoredFlag(COVERAGE_ARCHIVED_KEY, false, store);
}

export function writeIncludeArchived(on, store = globalThis.localStorage) {
  writeStoredFlag(COVERAGE_ARCHIVED_KEY, on, store);
}

/** List stays the default so the existing subjects table is unchanged until chosen. */
export function readSubjectsMode(store = globalThis.localStorage) {
  if (!store) return "list";
  return store.getItem(SUBJECTS_MODE_KEY) === "coverage" ? "coverage" : "list";
}

export function writeSubjectsMode(mode, store = globalThis.localStorage) {
  if (!store) return;
  store.setItem(SUBJECTS_MODE_KEY, mode === "coverage" ? "coverage" : "list");
}

export function addIsoDays(iso, n) {
  const [y, m, d] = String(iso).split("-").map(Number);
  if (!y || !m || !d) return "";
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + n);
  return dt.toISOString().slice(0, 10);
}

export function weekdayIndex(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  if (!y) return 0;
  const utc = new Date(Date.UTC(y, m - 1, d));
  return (utc.getUTCDay() + 6) % 7; // Monday = 0
}

export function weekdayLetter(iso) {
  return WEEKDAYS[weekdayIndex(iso)] || "";
}

export function weekLabel(dates) {
  if (!dates?.length) return "";
  const a = dates[0].split("-").map(Number);
  const b = dates[dates.length - 1].split("-").map(Number);
  const left = `${MONTHS[a[1] - 1]} ${a[2]}`;
  const right = a[1] === b[1] ? String(b[2]) : `${MONTHS[b[1] - 1]} ${b[2]}`;
  return `${left}–${right}`;
}

export function daysByDate(subject) {
  const map = {};
  for (const day of subject?.days || []) map[day.date] = day;
  return map;
}

/** Hatched when the day is not expected, regardless of the underlying score. */
export function bandStatus(day, key) {
  if (!day?.expected) return "not_expected";
  return day[key]?.status || "missing";
}

export function formatHours(minutes) {
  if (minutes == null || Number.isNaN(Number(minutes))) return "";
  const hours = Math.round((Number(minutes) / 60) * 10) / 10;
  return `${hours} h`;
}

function reasonText(reason) {
  if (reason === "collection_window") return "Not expected — outside the collection window";
  if (reason === "future") return "Not expected — future day";
  if (reason === "before_enrollment") return "Not expected — before this participant was added";
  return "Not expected";
}

function hrLine(hr) {
  if (!hr) return "Heart rate: —";
  if (hr.basis === "daily_summary") {
    const avg = hr.hr_avg == null ? "recorded" : `${hr.hr_avg} bpm`;
    return `Heart rate: daily average ${avg} (intraday not stored) — ${hr.status}`;
  }
  if (hr.basis === "resting_only") return "Heart rate: resting only — partial";
  if (hr.minutes == null) return `Heart rate: ${hr.status}`;
  return `Heart rate: ${formatHours(hr.minutes)} coverage — ${hr.status}`;
}

function stepsLine(steps) {
  if (!steps) return "Steps: —";
  const total = steps.total == null ? "no total" : `${steps.total} steps`;
  const recording = steps.minutes == null ? "" : `, ${formatHours(steps.minutes)} recording`;
  return `Steps: ${total}${recording} — ${steps.status}`;
}

function sleepLine(sleep) {
  if (!sleep || sleep.minutes == null) return `Sleep: none — ${sleep?.status || "missing"}`;
  return `Sleep: ${formatHours(sleep.minutes)} asleep — ${sleep.status}`;
}

/** Multi-line hover. Zero steps stays visible as "0 steps", not as missing. */
export function dayTooltip(day) {
  if (!day) return "";
  const lines = [day.date];
  if (day.dimmed) lines.push("Outside the selected range");
  if (!day.expected) lines.push(reasonText(day.reason));
  lines.push(hrLine(day.hr), stepsLine(day.steps), sleepLine(day.sleep));
  return lines.join("\n");
}

export function totalsTitle(tally) {
  if (!tally) return "";
  const n = tally.expected;
  return [
    `Heart rate ${tally.hr_sufficient}/${n}`,
    `Steps ${tally.steps_sufficient}/${n}`,
    `Sleep ${tally.sleep_sufficient}/${n}`,
  ].join(" · ");
}

/** Previous/next among days inside the selected range (skip dimmed week padding). */
export function adjacentInRange(days, date, dir) {
  const visible = (days || []).filter((d) => d && !d.dimmed);
  const i = visible.findIndex((d) => d.date === date);
  if (i < 0) return null;
  return visible[i + dir]?.date ?? null;
}

export function parseInstant(iso) {
  if (!iso) return null;
  const d = new Date(String(iso).endsWith("Z") || /[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Local civil date of a UTC instant plus the participant's offset. */
export function localIsoDate(iso, offsetSec) {
  const d = parseInstant(iso);
  if (!d) return null;
  const shifted = new Date(d.getTime() + (Number(offsetSec) || 0) * 1000);
  return shifted.toISOString().slice(0, 10);
}

/** Minutes after local midnight. */
export function localMinutes(iso, offsetSec) {
  const d = parseInstant(iso);
  if (!d) return null;
  const shifted = new Date(d.getTime() + (Number(offsetSec) || 0) * 1000);
  return shifted.getUTCHours() * 60 + shifted.getUTCMinutes() + shifted.getUTCSeconds() / 60;
}

export function wakeDate(point) {
  if (!point) return null;
  return localIsoDate(point.end_time || point.start_time, point.tz_offset_seconds);
}

/**
 * Intraday series for one metric on one local day.
 * Sleep sessions are kept when they *wake* on `day`, even if stored on the
 * previous local date. Other metrics use points already filtered to `day`.
 */
export function seriesFor(points, datatype, day) {
  const rows = (points || []).filter((p) => p.datatype === datatype);
  if (datatype === "sleep") {
    return rows.filter((p) => wakeDate(p) === day).map(sleepSegment).filter(Boolean);
  }
  return rows.map(timedSegment).filter(Boolean);
}

function timedSegment(point) {
  const startMin = localMinutes(point.start_time, point.tz_offset_seconds);
  if (startMin == null) return null;
  let endMin = localMinutes(point.end_time, point.tz_offset_seconds);
  if (endMin == null || endMin < startMin) endMin = Math.min(1440, startMin + 1);
  return {
    startMin: Math.max(0, startMin),
    endMin: Math.min(1440, endMin),
    value: point.value,
    label: point.datatype,
  };
}

function sleepSegment(point) {
  const stages = (point.stages || []).map((stage) => {
    const startMin = localMinutes(stage.start_time, point.tz_offset_seconds);
    const endMin = localMinutes(stage.end_time, point.tz_offset_seconds);
    return {
      type: String(stage.type || "").toUpperCase(),
      startMin,
      endMin,
      startDay: localIsoDate(stage.start_time, point.tz_offset_seconds),
      endDay: localIsoDate(stage.end_time, point.tz_offset_seconds),
    };
  }).filter((s) => s.startMin != null && s.endMin != null);
  const startMin = localMinutes(point.start_time, point.tz_offset_seconds);
  const endMin = localMinutes(point.end_time, point.tz_offset_seconds);
  return {
    startMin,
    endMin,
    startDay: localIsoDate(point.start_time, point.tz_offset_seconds),
    endDay: localIsoDate(point.end_time || point.start_time, point.tz_offset_seconds),
    value: point.value,
    stages,
  };
}

/** Stage intervals in minutes relative to wake-day midnight (previous evening is negative). */
export function sleepPieces(segment, wakeDay) {
  const stages = segment?.stages?.length
    ? segment.stages
    : [{
        type: "SLEEP",
        startMin: segment?.startMin,
        endMin: segment?.endMin,
        startDay: segment?.startDay,
        endDay: segment?.endDay || wakeDay,
      }];
  const pieces = [];
  for (const stage of stages) {
    if (stage.startMin == null || stage.endMin == null) continue;
    const startsPrev = stage.startDay && stage.startDay < wakeDay;
    const endsPrev = stage.endDay && stage.endDay < wakeDay;
    if (endsPrev) continue;
    if (startsPrev) {
      pieces.push({ type: stage.type, start: stage.startMin - 1440, end: stage.endMin });
    } else {
      const end = stage.endMin < stage.startMin ? stage.startMin + 1 : stage.endMin;
      pieces.push({ type: stage.type, start: stage.startMin, end });
    }
  }
  return pieces;
}

export const PRIMARY_METRICS = [
  { id: "heart_rate", label: "Heart rate" },
  { id: "steps", label: "Steps" },
  { id: "sleep", label: "Sleep" },
];

export function metricChoices(points) {
  const extras = [];
  const known = new Set(PRIMARY_METRICS.map((m) => m.id));
  for (const point of points || []) {
    if (point.datatype && !known.has(point.datatype) && !extras.includes(point.datatype)) {
      extras.push(point.datatype);
    }
  }
  return [
    ...PRIMARY_METRICS,
    ...extras.map((id) => ({ id, label: id.replaceAll("_", " ") })),
  ];
}

export function formatLastPull(iso) {
  const d = parseInstant(iso);
  if (!iso) return "No pull yet";
  if (!d) return String(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
