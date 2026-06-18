import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...a) => twMerge(clsx(a));

export const today = () => new Date().toISOString().slice(0, 10);

export function fmtNum(v) {
  if (v == null) return null;
  return typeof v === "number" ? Math.round(v * 10) / 10 : v;
}

// UTC ISO + offset (seconds) -> local HH:MM
export function localTime(iso, offsetSec) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (typeof offsetSec === "number") d.setTime(d.getTime() + offsetSec * 1000);
  return d.toISOString().slice(11, 16);
}

export const STAGE_ORDER = ["DEEP", "REM", "LIGHT", "AWAKE"];

export function stageMinutes(stages) {
  const m = {};
  for (const s of stages || []) {
    const a = new Date(s.start_time);
    const b = new Date(s.end_time);
    if (isNaN(a) || isNaN(b)) continue;
    m[s.type || "?"] = (m[s.type || "?"] || 0) + Math.round((b - a) / 60000);
  }
  return m;
}

// --- export helpers -------------------------------------------------------------

export function download(filename, type, text) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvRow(vals) {
  return vals
    .map((v) => {
      if (v == null) return "";
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    })
    .join(",");
}

const DAILY_COLS = [
  "date", "tz_offset_seconds", "steps", "distance_m", "calories", "floors", "sleep_minutes",
  "hr_avg", "resting_hr", "hrv_ms", "spo2_avg",
  "sleep_total_min", "sleep_asleep_min", "awake_min", "light_min", "deep_min", "rem_min", "point_count",
];

function dailyVals(d) {
  const sl = (d.metrics && d.metrics.sleep) || {};
  const st = sl.stages || {};
  return [
    d.date, d.tz_offset_seconds, d.steps, d.distance_m, d.calories, d.floors, d.sleep_minutes,
    d.hr_avg, d.resting_hr, d.hrv_ms, d.spo2_avg,
    sl.total_min, sl.asleep_min, st.AWAKE, st.LIGHT, st.DEEP, st.REM, d.point_count,
  ];
}

export function dailyCsv(data) {
  const rows = [csvRow(DAILY_COLS)];
  for (const d of data.days) rows.push(csvRow(dailyVals(d)));
  return rows.join("\n");
}

export function pointsCsv(data) {
  const rows = [csvRow(["date", "datatype", "start_time", "end_time", "value", "tz_offset_seconds"])];
  for (const d of data.days)
    for (const p of d.points || [])
      rows.push(csvRow([d.date, p.datatype, p.start_time, p.end_time, p.value, p.tz_offset_seconds]));
  return rows.join("\n");
}

export function studyDailyCsv(data) {
  const rows = [csvRow(["subject_label", "entry_code", ...DAILY_COLS])];
  for (const s of data.subjects || [])
    for (const d of s.days)
      rows.push(csvRow([s.subject.subject_label, s.subject.entry_code, ...dailyVals(d)]));
  return rows.join("\n");
}

export function studyPointsCsv(data) {
  const rows = [
    csvRow(["subject_label", "entry_code", "date", "datatype", "start_time", "end_time", "value", "tz_offset_seconds"]),
  ];
  for (const s of data.subjects || [])
    for (const d of s.days)
      for (const p of d.points || [])
        rows.push(
          csvRow([s.subject.subject_label, s.subject.entry_code, d.date, p.datatype, p.start_time, p.end_time, p.value, p.tz_offset_seconds])
        );
  return rows.join("\n");
}
