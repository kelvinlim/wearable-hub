/** Participant coverage calendar (researcher console).

Filters persist with the same localStorage style as Hide PHI and the Subjects
list: `wh-*` keys, booleans as `"1"` / `"0"`. The date-range mode is the
string `7d` | `all` | `custom` (default `7d`). Active-only is the default.

The calendar payload itself is not stored. One `range=full` response is kept
in an in-memory map (per study and include-archived flag) and last-7 / custom
windows are sliced from it. Opened intraday days are cached the same way.
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

/**
 * Units we can justify from stored values.
 *
 * Distance intraday points are Google Health millimeter sums (the daily column
 * divides `millimetersSum` by 1000 into `distance_m`). The chart and table show
 * meters. Datatypes with no documented unit are labeled and left unitless.
 */
const METRIC_META = {
  heart_rate: { label: "Heart rate", unit: "bpm" },
  steps: { label: "Steps", unit: "steps" },
  sleep: { label: "Sleep", unit: "min" },
  heart_rate_variability: { label: "Heart rate variability", unit: "ms" },
  oxygen_saturation: { label: "SpO₂", unit: "%" },
  distance: { label: "Distance", unit: "m", scale: 0.001 },
  calories: { label: "Calories", unit: "kcal" },
  floors: { label: "Floors", unit: "floors" },
  respiration: { label: "Respiration", unit: "brpm" },
  stress: { label: "Stress" },
  body_battery: { label: "Body battery" },
  altitude: { label: "Altitude" },
  exercise: { label: "Exercise" },
  weight: { label: "Weight" },
  height: { label: "Height" },
};

export const MAX_COVERAGE_DAYS = 800;

const EMPTY_HR = { status: "missing", basis: "none", minutes: null, fraction: null, hr_avg: null };
const EMPTY_STEPS = { status: "missing", basis: "none", total: null, minutes: null, fraction: null };
const EMPTY_SLEEP = { status: "missing", basis: "none", minutes: null };

const coverageCache = new Map();
const dayPointsCache = new Map();

export function metricMeta(datatype) {
  if (METRIC_META[datatype]) return METRIC_META[datatype];
  const raw = String(datatype || "series").replaceAll("_", " ");
  return { label: raw.charAt(0).toUpperCase() + raw.slice(1) };
}

export function scaleValue(datatype, value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (Number.isNaN(n)) return null;
  const scale = metricMeta(datatype).scale ?? 1;
  return Math.round(n * scale * 10) / 10;
}

export function formatMeasure(datatype, value) {
  const shown = scaleValue(datatype, value);
  if (shown == null) return "—";
  const unit = metricMeta(datatype).unit;
  return unit ? `${shown} ${unit}` : String(shown);
}

/** Local clock, with a previous-evening prefix when the minute is before midnight. */
export function formatClock(minute) {
  if (minute == null || Number.isNaN(Number(minute))) return "";
  const n = Number(minute);
  const dayMark = n < 0 ? "−1d " : n >= 1440 ? "+1d " : "";
  const wrapped = ((Math.round(n) % 1440) + 1440) % 1440;
  const h = String(Math.floor(wrapped / 60)).padStart(2, "0");
  const m = String(wrapped % 60).padStart(2, "0");
  return `${dayMark}${h}:${m}`;
}

export function metricChoices(points) {
  const extras = [];
  const known = new Set(PRIMARY_METRICS.map((m) => m.id));
  for (const point of points || []) {
    if (point.datatype && !known.has(point.datatype) && !extras.includes(point.datatype)) {
      extras.push(point.datatype);
    }
  }
  return [
    ...PRIMARY_METRICS.map((m) => ({ id: m.id, label: metricMeta(m.id).label })),
    ...extras.map((id) => ({ id, label: metricMeta(id).label })),
  ];
}

/**
 * Heart rate, steps, and sleep always, then any other datatype that has a
 * point on this local day. Sleep from the previous evening is included when
 * it wakes on `day` (see seriesFor).
 */
export function dayPanels(points, day) {
  const extras = [];
  const known = new Set(PRIMARY_METRICS.map((m) => m.id));
  const scoped = (points || []).filter((point) => {
    if (!day || point.datatype === "sleep") return true;
    const local = localIsoDate(point.start_time || point.end_time, point.tz_offset_seconds);
    return !local || local === day;
  });
  for (const point of scoped) {
    if (!point.datatype || known.has(point.datatype) || extras.includes(point.datatype)) continue;
    if (seriesFor(scoped, point.datatype, day).length) extras.push(point.datatype);
  }
  return [...PRIMARY_METRICS.map((m) => m.id), ...extras].map((id) => {
    const meta = metricMeta(id);
    const series = seriesFor(scoped, id, day);
    return { id, label: meta.label, unit: meta.unit || "", series, empty: series.length === 0 };
  });
}

function segmentEnd(segment) {
  if (segment.endMin == null) return segment.startMin;
  return segment.endMin <= segment.startMin ? segment.startMin + 1 : segment.endMin;
}

/** The mark under `minute`, or null when the series has a gap there. */
export function hitAt(panel, minute, day) {
  if (minute == null || Number.isNaN(Number(minute))) return null;
  const t = Number(minute);
  if (panel.id === "sleep") {
    const pieces = (panel.series || []).flatMap((segment) => sleepPieces(segment, day));
    const piece = pieces.find((p) => t >= p.start && t < p.end);
    if (!piece) return null;
    const minutes = Math.max(1, Math.round(piece.end - piece.start));
    return {
      start: piece.start,
      end: piece.end,
      range: `${formatClock(piece.start)}–${formatClock(piece.end)}`,
      stage: piece.type,
      minutes,
      value: piece.type,
      unit: "min",
    };
  }
  const matches = (panel.series || []).filter((segment) => {
    if (segment.startMin == null) return false;
    return t >= segment.startMin && t < segmentEnd(segment);
  });
  if (!matches.length) return null;
  matches.sort((a, b) => b.startMin - a.startMin);
  const segment = matches[0];
  return {
    start: segment.startMin,
    end: segmentEnd(segment),
    range: `${formatClock(segment.startMin)}–${formatClock(segmentEnd(segment))}`,
    value: scaleValue(panel.id, segment.value),
    unit: panel.unit || "",
  };
}

/** Time range, value, and unit for one mark. Sleep is stage plus minutes. */
export function formatHit(hit) {
  if (!hit) return null;
  if (hit.stage) {
    return `${hit.range} · ${String(hit.stage).toLowerCase()} · ${hit.minutes} min`;
  }
  if (hit.value == null) return hit.range || null;
  const unit = hit.unit ? ` ${hit.unit}` : "";
  return `${hit.range} · ${hit.value}${unit}`;
}

/** Every panel's value at one local minute, for the shared crosshair. */
export function readoutAt(panels, minute, day) {
  return (panels || []).map((panel) => {
    const hit = hitAt(panel, minute, day);
    return {
      id: panel.id,
      label: panel.label,
      unit: panel.unit || "",
      hit,
      text: formatHit(hit),
    };
  });
}

export function coverageCacheKey(studyId, includeArchived) {
  return `${studyId}|${includeArchived ? "1" : "0"}`;
}

export function dayPointsCacheKey(subjectId, day) {
  return `${subjectId}|${day}`;
}

export function readCoverageCache(studyId, includeArchived, cache = coverageCache) {
  return cache.get(coverageCacheKey(studyId, includeArchived)) ?? null;
}

export function writeCoverageCache(studyId, includeArchived, body, cache = coverageCache) {
  cache.set(coverageCacheKey(studyId, includeArchived), body);
  return body;
}

/** Fetches the full calendar once per study and include-archived flag. */
export async function loadCachedCoverage(studyId, includeArchived, fetcher, cache = coverageCache) {
  const key = coverageCacheKey(studyId, includeArchived);
  if (cache.has(key)) return cache.get(key);
  const body = await fetcher();
  cache.set(key, body);
  return body;
}

export function readDayPointsCache(subjectId, day, cache = dayPointsCache) {
  const key = dayPointsCacheKey(subjectId, day);
  return cache.has(key) ? cache.get(key) : null;
}

export function writeDayPointsCache(subjectId, day, points, cache = dayPointsCache) {
  cache.set(dayPointsCacheKey(subjectId, day), points || []);
  return points || [];
}

/** Fetches one local day's points once. A thrown fetch is not cached. */
export async function loadCachedDayPoints(subjectId, day, fetcher, cache = dayPointsCache) {
  const key = dayPointsCacheKey(subjectId, day);
  if (cache.has(key)) return cache.get(key);
  const list = (await fetcher(subjectId, day)) || [];
  cache.set(key, list);
  return list;
}

/** Today's non-sleep points, plus sleep from today and the previous bedtime. */
export function mergeDayPoints(todayPts, prevPts) {
  const other = (todayPts || []).filter((p) => p.datatype !== "sleep");
  const sleep = [...(todayPts || []), ...(prevPts || [])].filter((p) => p.datatype === "sleep");
  return [...other, ...sleep];
}

export function isoSpanDays(start, end) {
  const a = Date.parse(`${start}T00:00:00Z`);
  const b = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return NaN;
  return Math.round((b - a) / 86400000);
}

/** Monday–Sunday weeks covering start..end inclusive. */
export function weekDates(start, end) {
  if (!start || !end || end < start) return [];
  let cur = addIsoDays(start, -weekdayIndex(start));
  const last = addIsoDays(end, -weekdayIndex(end));
  const weeks = [];
  while (cur && cur <= last) {
    weeks.push(Array.from({ length: 7 }, (_, i) => addIsoDays(cur, i)));
    cur = addIsoDays(cur, 7);
  }
  return weeks;
}

function eachIso(start, end, visit) {
  for (let iso = start; iso && iso <= end; iso = addIsoDays(iso, 1)) visit(iso);
}

function expectedOf(subject, iso) {
  const today = subject.local_today;
  if (today && iso > today) return [false, "future"];
  const start = subject.collection_start || null;
  const end = subject.collection_end || null;
  if ((start && iso < start) || (end && iso > end)) return [false, "collection_window"];
  if (!start && subject.enrolled_on && iso < subject.enrolled_on) return [false, "before_enrollment"];
  return [true, null];
}

/** A day the full payload does not contain: no stored scores, same expected rules. */
export function synthesizeDay(subject, iso) {
  const [expected, reason] = expectedOf(subject, iso);
  return {
    date: iso,
    dimmed: false,
    expected,
    reason,
    hr: { ...EMPTY_HR },
    steps: { ...EMPTY_STEPS },
    sleep: { ...EMPTY_SLEEP },
  };
}

function selectionFor(subject, range, start, end) {
  if (range === "7d") {
    const today = subject.local_today;
    return { selStart: addIsoDays(today, -6), selEnd: today };
  }
  if (range === "custom") return { selStart: start, selEnd: end };
  return {
    selStart: subject.all_start || subject.local_today,
    selEnd: subject.all_end || subject.local_today,
  };
}

function tallySpan(subject, start, end) {
  const tally = { hr_sufficient: 0, steps_sufficient: 0, sleep_sufficient: 0, expected: 0 };
  if (!start || !end || end < start) return tally;
  const byDate = daysByDate(subject);
  eachIso(start, end, (iso) => {
    const cell = byDate[iso] || synthesizeDay(subject, iso);
    if (cell.expected === false) return;
    tally.expected += 1;
    if (cell.hr?.status === "sufficient") tally.hr_sufficient += 1;
    if (cell.steps?.status === "sufficient") tally.steps_sufficient += 1;
    if (cell.sleep?.status === "sufficient") tally.sleep_sufficient += 1;
  });
  return tally;
}

/**
 * Last-7, all-data, or a custom window from one `range=full` payload.
 * Copies day cells before setting `dimmed`, so the cached payload stays intact.
 * `to_date` is the server tally and is not recomputed.
 */
export function sliceCoverage(full, { range = "7d", start, end } = {}) {
  if (!full) return null;
  if (range === "custom") {
    if (!start || !end) throw new Error("custom range requires start and end");
    if (end < start) throw new Error("end must be >= start");
    if (isoSpanDays(start, end) > MAX_COVERAGE_DAYS) {
      throw new Error(`range too large (max ${MAX_COVERAGE_DAYS} days)`);
    }
  }
  const subjects = full.subjects || [];
  const selected = subjects.map((subject) => ({ subject, ...selectionFor(subject, range, start, end) }));
  let gridStart;
  let gridEnd;
  if (!selected.length) {
    const anchor = (full.end || "").slice(0, 10);
    if (range === "custom") {
      gridStart = start;
      gridEnd = end;
    } else if (range === "7d" && anchor) {
      gridStart = addIsoDays(anchor, -6);
      gridEnd = anchor;
    } else {
      gridStart = full.start;
      gridEnd = full.end;
    }
  } else {
    gridStart = selected.map((s) => s.selStart).sort()[0];
    gridEnd = selected.map((s) => s.selEnd).sort().at(-1);
  }
  const weeks = weekDates(gridStart, gridEnd);
  const grid = weeks.flat();
  return {
    range,
    start: gridStart,
    end: gridEnd,
    thresholds: full.thresholds,
    weeks: weeks.map((dates) => ({ start: dates[0], dates })),
    subjects: selected.map(({ subject, selStart, selEnd }) => {
      const byDate = daysByDate(subject);
      return {
        ...subject,
        on_screen: tallySpan(subject, selStart, selEnd),
        to_date: subject.to_date,
        days: grid.map((iso) => {
          const base = byDate[iso];
          const cell = base ? { ...base } : synthesizeDay(subject, iso);
          cell.dimmed = iso < selStart || iso > selEnd;
          return cell;
        }),
      };
    }),
  };
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
