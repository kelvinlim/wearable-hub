import React from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { fmtNum, localTime, stageMinutes, STAGE_ORDER } from "../lib";
import {
  formatHours,
  metricChoices,
  seriesFor,
  sleepPieces,
} from "../utils/coverage";

const STAGE_FILL = {
  DEEP: "#4338ca",
  REM: "#7c3aed",
  LIGHT: "#0284c7",
  AWAKE: "#ea580c",
  SLEEP: "#0f766e",
};

export default function IntradaySeries({
  name,
  day,
  points,
  loading,
  error,
  metric,
  onMetric,
  onPrev,
  onNext,
  prevDisabled,
  nextDisabled,
  onClose,
}) {
  const choices = metricChoices(points);
  const series = seriesFor(points, metric, day?.date);
  return (
    <div className="border-t border-gray-100 p-4 dark:border-neutral-800">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={prevDisabled}
          aria-label="Previous day"
          className="rounded-lg border border-gray-200 p-1.5 text-gray-500 hover:bg-gray-50 disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={nextDisabled}
          aria-label="Next day"
          className="rounded-lg border border-gray-200 p-1.5 text-gray-500 hover:bg-gray-50 disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-maroon dark:text-gold">{name}</div>
          <div className="text-xs text-gray-400">{day?.date}</div>
        </div>
        <label className="ml-auto flex items-center gap-2 text-xs text-gray-500">
          Metric
          <select
            aria-label="Metric"
            value={metric}
            onChange={(e) => onMetric(e.target.value)}
            className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-800 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100"
          >
            {choices.map((choice) => (
              <option key={choice.id} value={choice.id}>{choice.label}</option>
            ))}
          </select>
        </label>
        <button type="button" onClick={onClose} aria-label="Close day" className="text-gray-400 hover:text-gray-600">
          <X className="h-4 w-4" />
        </button>
      </div>

      <p className="mt-2 text-xs text-gray-500 dark:text-neutral-400">{summaryLine(metric, day)}</p>

      {error && <p className="mt-2 text-xs text-red-700 dark:text-red-300">{error}</p>}
      {loading && !error && <p className="mt-2 text-xs text-gray-400">Loading intraday series…</p>}

      {!loading && !error && (
        <>
          <SeriesChart metric={metric} series={series} day={day?.date} />
          <PointTable metric={metric} points={points} day={day?.date} />
        </>
      )}
    </div>
  );
}

function summaryLine(metric, day) {
  if (!day) return "";
  if (metric === "heart_rate") {
    const hr = day.hr || {};
    if (hr.basis === "daily_summary") return `Daily average ${hr.hr_avg ?? "—"} bpm. Intraday heart rate is not stored for this day.`;
    if (hr.minutes == null) return "No heart-rate coverage recorded.";
    return `${formatHours(hr.minutes)} of heart-rate coverage${hr.hr_avg != null ? ` · average ${hr.hr_avg} bpm` : ""}.`;
  }
  if (metric === "steps") {
    const steps = day.steps || {};
    const total = steps.total == null ? "no day total" : `${steps.total} steps`;
    const recording = steps.minutes == null ? "day total only" : `${formatHours(steps.minutes)} recording`;
    return `${total} · ${recording}.`;
  }
  if (metric === "sleep") {
    const sleep = day.sleep || {};
    if (sleep.minutes == null) return "No sleep assigned to this wake-up date.";
    return `${formatHours(sleep.minutes)} asleep, assigned to this wake-up date.`;
  }
  return "";
}

function SeriesChart({ metric, series, day }) {
  if (metric === "sleep") return <SleepChart series={series} day={day} />;
  if (!series.length) {
    return <p className="mt-3 text-xs text-gray-400">No intraday {metric.replaceAll("_", " ")} points for this day.</p>;
  }
  const values = series.map((s) => Number(s.value)).filter((v) => !Number.isNaN(v));
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const lo = min === max ? min - 1 : min;
  const hi = min === max ? max + 1 : Math.max(max, 1);
  const y = (v) => 8 + (1 - (v - lo) / (hi - lo)) * 72;
  const color = metric === "steps" ? "#b45309" : "#7a0019";
  return (
    <div className="mt-3">
      <svg viewBox="0 0 1440 100" className="h-36 w-full rounded-lg bg-gray-50 dark:bg-neutral-800/60" role="img" aria-label={`${metric} across the local day`}>
        {[0, 360, 720, 1080, 1440].map((m) => (
          <line key={m} x1={m} x2={m} y1="4" y2="92" stroke="currentColor" strokeOpacity="0.12" />
        ))}
        {metric === "steps"
          ? series.map((s, i) => {
              const h = Math.max(2, ((Number(s.value) || 0) - lo) / (hi - lo) * 72);
              return (
                <rect
                  key={i}
                  x={s.startMin}
                  y={92 - h}
                  width={Math.max(2, s.endMin - s.startMin)}
                  height={h}
                  fill={color}
                  opacity="0.85"
                />
              );
            })
          : series.map((s, i) => (
              <line
                key={i}
                x1={s.startMin}
                x2={Math.max(s.endMin, s.startMin + 2)}
                y1={y(Number(s.value) || 0)}
                y2={y(Number(s.value) || 0)}
                stroke={color}
                strokeWidth="8"
                strokeLinecap="butt"
              />
            ))}
      </svg>
      <Axis />
    </div>
  );
}

function SleepChart({ series, day }) {
  const pieces = series.flatMap((segment) => sleepPieces(segment, day));
  if (!pieces.length) {
    return <p className="mt-3 text-xs text-gray-400">No sleep stages stored for this wake-up date.</p>;
  }
  const min = Math.min(...pieces.map((p) => p.start));
  const max = Math.max(...pieces.map((p) => p.end));
  const span = Math.max(1, max - min);
  const x = (m) => ((m - min) / span) * 1440;
  return (
    <div className="mt-3">
      <svg viewBox="0 0 1440 48" className="h-16 w-full rounded-lg bg-gray-50 dark:bg-neutral-800/60" role="img" aria-label="Sleep stages">
        {pieces.map((piece, i) => (
          <rect
            key={i}
            x={x(piece.start)}
            y="10"
            width={Math.max(2, x(piece.end) - x(piece.start))}
            height="28"
            fill={STAGE_FILL[piece.type] || "#64748b"}
            rx="3"
          />
        ))}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-gray-400">
        <span>{clock(min)}</span>
        <span>{clock(max)}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-gray-500">
        {Object.entries(STAGE_FILL).filter(([type]) => pieces.some((p) => p.type === type)).map(([type, color]) => (
          <span key={type} className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
            {type.toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  );
}

function clock(minute) {
  const wrapped = ((Math.round(minute) % 1440) + 1440) % 1440;
  const h = String(Math.floor(wrapped / 60)).padStart(2, "0");
  const m = String(wrapped % 60).padStart(2, "0");
  const prev = minute < 0 ? "−1d " : "";
  return `${prev}${h}:${m}`;
}

function Axis() {
  return (
    <div className="mt-1 flex justify-between text-[10px] text-gray-400">
      <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span>
    </div>
  );
}

function PointTable({ metric, points, day }) {
  const rows = (points || []).filter((p) => p.datatype === metric);
  const shown = metric === "sleep" ? rows.filter((p) => {
    const end = p.end_time || p.start_time;
    if (!end) return false;
    const wake = new Date((String(end).endsWith("Z") ? end : `${end}Z`));
    if (Number.isNaN(wake.getTime())) return false;
    const shifted = new Date(wake.getTime() + (Number(p.tz_offset_seconds) || 0) * 1000);
    return shifted.toISOString().slice(0, 10) === day;
  }) : rows;
  if (!shown.length) return null;
  if (metric === "sleep") {
    return (
      <div className="mt-3 flex flex-col gap-1.5">
        {shown.map((session, i) => (
          <div key={i} className="rounded-lg border border-gray-200 p-2 text-xs dark:border-neutral-700">
            <div className="text-gray-400">
              {localTime(session.start_time, session.tz_offset_seconds)}–{localTime(session.end_time, session.tz_offset_seconds)}
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {STAGE_ORDER.filter((k) => stageMinutes(session.stages)[k]).map((k) => (
                <span key={k} className="rounded-full bg-gray-100 px-2 py-0.5 dark:bg-neutral-800">
                  {k.toLowerCase()} {stageMinutes(session.stages)[k]}m
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="mt-3 max-h-56 overflow-y-auto rounded-lg border border-gray-200 dark:border-neutral-700">
      <table className="w-full text-xs">
        <tbody>
          {shown.map((p, i) => (
            <tr key={i} className="border-b border-gray-50 last:border-0 dark:border-neutral-800">
              <td className="px-2 py-1 text-gray-400">
                {localTime(p.start_time, p.tz_offset_seconds)}–{localTime(p.end_time, p.tz_offset_seconds)}
              </td>
              <td className="px-2 py-1 text-right">{fmtNum(p.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
