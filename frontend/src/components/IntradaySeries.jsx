import React, { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, X } from "lucide-react";
import { cn, fmtNum, localTime, stageMinutes, STAGE_ORDER } from "../lib";
import {
  dayPanels,
  formatClock,
  formatHit,
  formatHours,
  formatMeasure,
  hitAt,
  metricMeta,
  readoutAt,
  scaleValue,
  SLEEP_STAGE_LANES,
  sleepPieces,
  sleepStageLane,
} from "../utils/coverage";

const PLOT_W = 1440;
const PLOT_H = 96;
const STAGE_FILL = {
  DEEP: "#4338ca",
  REM: "#7c3aed",
  LIGHT: "#0284c7",
  AWAKE: "#ea580c",
  SLEEP: "#0f766e",
};
const SERIES_COLOR = {
  heart_rate: "#7a0019",
  steps: "#b45309",
  distance: "#0369a1",
  heart_rate_variability: "#7c3aed",
  oxygen_saturation: "#0f766e",
  calories: "#b45309",
  floors: "#0f766e",
};
const BAR_METRICS = new Set(["steps", "distance", "floors", "calories"]);

export default function IntradaySeries({
  name,
  day,
  points,
  loading,
  error,
  onPrev,
  onNext,
  prevDisabled,
  nextDisabled,
  onClose,
}) {
  const panels = dayPanels(points, day?.date);
  const [hover, setHover] = useState(null);
  const [open, setOpen] = useState({});
  const readout = hover ? readoutAt(panels, hover.minute, day?.date) : [];

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
        <button type="button" onClick={onClose} aria-label="Close day" className="ml-auto text-gray-400 hover:text-gray-600">
          <X className="h-4 w-4" />
        </button>
      </div>

      {error && <p className="mt-2 text-xs text-red-700 dark:text-red-300">{error}</p>}
      {loading && !error && <p className="mt-2 text-xs text-gray-400">Loading intraday series…</p>}

      {!loading && !error && (
        <div className="mt-3 flex flex-col gap-3" onMouseLeave={() => setHover(null)}>
          {panels.map((panel) => (
            <Panel
              key={panel.id}
              panel={panel}
              day={day}
              points={points}
              hover={hover}
              open={!!open[panel.id]}
              onToggle={() => setOpen((cur) => ({ ...cur, [panel.id]: !cur[panel.id] }))}
              onHover={setHover}
            />
          ))}
        </div>
      )}

      {hover && readout.length > 0 && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 w-64 rounded-lg bg-neutral-900 px-3 py-2 text-xs text-white shadow-lg"
          style={tipStyle(hover)}
        >
          <div className="font-medium">{formatClock(hover.minute)}</div>
          <ul className="mt-1 space-y-0.5">
            {readout.map((row) => (
              <li key={row.id} className="flex justify-between gap-3">
                <span className="text-neutral-300">{row.label}</span>
                <span className="text-right">{row.text || "—"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function tipStyle(hover) {
  const left = Math.max(8, Math.min(hover.x + 14, window.innerWidth - 272));
  const top = Math.max(8, Math.min(hover.y + 16, window.innerHeight - 220));
  return { left, top };
}

function Panel({ panel, day, points, hover, open, onToggle, onHover }) {
  const summary = summaryLine(panel.id, day);
  return (
    <section className="rounded-lg border border-gray-100 p-2 dark:border-neutral-800">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm font-semibold text-gray-800 dark:text-neutral-100">
          {panel.label}
          {panel.unit ? <span className="ml-1 text-xs font-normal text-gray-400">({panel.unit})</span> : null}
        </h3>
        {summary && <p className="text-xs text-gray-500 dark:text-neutral-400">{summary}</p>}
        {!panel.empty && (
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 dark:hover:text-neutral-200"
            aria-expanded={open}
            onClick={onToggle}
          >
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
            {open ? "Hide table" : "Show table"}
          </button>
        )}
      </div>
      {panel.empty ? (
        <p className="mt-2 text-xs text-gray-400">{emptyCopy(panel)}</p>
      ) : panel.id === "sleep" ? (
        <SleepChart panel={panel} day={day?.date} hoverMinute={hover?.minute} onHover={onHover} />
      ) : (
        <MidnightChart panel={panel} hoverMinute={hover?.minute} onHover={onHover} />
      )}
      {open && !panel.empty && <PointTable metric={panel.id} points={points} day={day?.date} />}
    </section>
  );
}

function emptyCopy(panel) {
  if (panel.id === "heart_rate") return "No intraday heart rate for this day.";
  if (panel.id === "steps") return "No intraday steps for this day.";
  if (panel.id === "sleep") return "No sleep stages stored for this wake-up date.";
  return `No ${panel.label.toLowerCase()} for this day.`;
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

function MidnightChart({ panel, hoverMinute, onHover }) {
  const color = SERIES_COLOR[panel.id] || "#0369a1";
  const values = panel.series.map((s) => scaleValue(panel.id, s.value)).filter((v) => v != null);
  const fromZero = BAR_METRICS.has(panel.id);
  const scale = yScale(values, fromZero);
  const hoverX = hoverMinute != null && hoverMinute >= 0 && hoverMinute <= 1440
    ? (hoverMinute / 1440) * PLOT_W
    : null;
  return (
    <div className="mt-2 flex gap-2">
      <div className="flex h-28 w-12 shrink-0 flex-col justify-between self-start py-1 text-right text-[10px] leading-none text-gray-400">
        <span>{tickLabel(scale.hi, panel.unit)}</span>
        <span>{tickLabel(scale.lo, panel.unit)}</span>
      </div>
      <div className="min-w-0 flex-1">
        <svg
          viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
          preserveAspectRatio="none"
          className="h-28 w-full rounded-lg bg-gray-50 dark:bg-neutral-800/60"
          role="img"
          aria-label={`${panel.label} from midnight to midnight`}
          onMouseMove={(e) => onHover(hoverFromEvent(e, 0, 1440))}
        >
          <rect width={PLOT_W} height={PLOT_H} fill="transparent" />
          {[0, 360, 720, 1080, 1440].map((m) => (
            <line key={m} x1={(m / 1440) * PLOT_W} x2={(m / 1440) * PLOT_W} y1="0" y2={PLOT_H} stroke="currentColor" strokeOpacity="0.12" />
          ))}
          {panel.series.map((segment, i) => {
            const value = scaleValue(panel.id, segment.value);
            const label = formatHit(hitAt(panel, segment.startMin)) || "";
            const x = (segment.startMin / 1440) * PLOT_W;
            const w = Math.max(2, ((segment.endMin - segment.startMin) / 1440) * PLOT_W);
            if (fromZero) {
              const h = Math.max(2, ((value || 0) - scale.lo) / (scale.hi - scale.lo) * (PLOT_H - 16));
              return (
                <rect key={i} x={x} y={PLOT_H - 8 - h} width={w} height={h} fill={color} opacity="0.85">
                  <title>{label}</title>
                </rect>
              );
            }
            const y = scale.y(value || 0);
            return (
              <line
                key={i}
                x1={x}
                x2={x + w}
                y1={y}
                y2={y}
                stroke={color}
                strokeWidth="8"
                strokeLinecap="butt"
              >
                <title>{label}</title>
              </line>
            );
          })}
          {hoverX != null && (
            <line x1={hoverX} x2={hoverX} y1="0" y2={PLOT_H} stroke="#7a0019" strokeOpacity="0.55" strokeDasharray="5 4" />
          )}
        </svg>
        <Axis />
      </div>
    </div>
  );
}

function SleepChart({ panel, day, hoverMinute, onHover }) {
  const pieces = panel.series.flatMap((segment) => sleepPieces(segment, day));
  if (!pieces.length) {
    return <p className="mt-2 text-xs text-gray-400">No sleep stages stored for this wake-up date.</p>;
  }
  const min = Math.min(...pieces.map((p) => p.start));
  const max = Math.max(...pieces.map((p) => p.end));
  const span = Math.max(1, max - min);
  const x = (m) => ((m - min) / span) * PLOT_W;
  const laneH = PLOT_H / SLEEP_STAGE_LANES.length;
  const present = new Set(pieces.map((p) => p.type));
  const staged = pieces.some((piece) => sleepStageLane(piece.type) != null);
  const hoverX = hoverMinute != null && hoverMinute >= min && hoverMinute <= max ? x(hoverMinute) : null;
  return (
    <div className="mt-2 flex gap-2">
      <div className="flex h-24 w-12 shrink-0 flex-col justify-between self-start py-0.5 text-right text-[10px] leading-none text-gray-400">
        {staged ? SLEEP_STAGE_LANES.map((lane) => (
          <span key={lane}>{lane.toLowerCase()}</span>
        )) : (
          <span className="m-auto">sleep</span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <svg
          viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
          preserveAspectRatio="none"
          className="h-24 w-full rounded-lg bg-gray-50 dark:bg-neutral-800/60"
          role="img"
          aria-label="Sleep stages from bedtime to wake"
          onMouseMove={(e) => onHover(hoverFromEvent(e, min, max))}
        >
          <rect width={PLOT_W} height={PLOT_H} fill="transparent" />
          {pieces.map((piece, i) => {
            const lane = sleepStageLane(piece.type);
            // Unstaged sleep (the SLEEP fallback) spans the plot. It is not REM.
            const y = lane == null ? 4 : lane * laneH + 2;
            const height = lane == null ? PLOT_H - 8 : laneH - 4;
            const minutes = Math.max(1, Math.round(piece.end - piece.start));
            const label = `${formatClock(piece.start)}–${formatClock(piece.end)} · ${piece.type.toLowerCase()} · ${minutes} min`;
            return (
              <rect
                key={i}
                x={x(piece.start)}
                y={y}
                width={Math.max(2, x(piece.end) - x(piece.start))}
                height={height}
                fill={STAGE_FILL[piece.type] || "#64748b"}
                rx="3"
              >
                <title>{label}</title>
              </rect>
            );
          })}
          {hoverX != null && (
            <line x1={hoverX} x2={hoverX} y1="0" y2={PLOT_H} stroke="#7a0019" strokeOpacity="0.55" strokeDasharray="5 4" />
          )}
        </svg>
        <div className="mt-1 flex justify-between text-[10px] text-gray-400">
          <span>{formatClock(min)}</span>
          <span>{formatClock(max)}</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-gray-500">
          {Object.entries(STAGE_FILL).filter(([type]) => present.has(type)).map(([type, color]) => (
            <span key={type} className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
              {type.toLowerCase()}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function hoverFromEvent(event, domainMin, domainMax) {
  const rect = event.currentTarget.getBoundingClientRect();
  const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0;
  const minute = domainMin + Math.min(1, Math.max(0, ratio)) * (domainMax - domainMin);
  return { minute, x: event.clientX, y: event.clientY };
}

function yScale(values, fromZero) {
  let lo = values.length ? Math.min(...values) : 0;
  let hi = values.length ? Math.max(...values) : 1;
  if (fromZero) lo = Math.min(0, lo);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const y = (v) => 8 + (1 - (v - lo) / (hi - lo)) * (PLOT_H - 16);
  return { lo, hi, y };
}

function tickLabel(value, unit) {
  const n = Math.round(value * 10) / 10;
  return unit ? `${n}` : `${n}`;
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
    const wake = new Date(String(end).endsWith("Z") || /[+-]\d\d:?\d\d$/.test(end) ? end : `${end}Z`);
    if (Number.isNaN(wake.getTime())) return false;
    const shifted = new Date(wake.getTime() + (Number(p.tz_offset_seconds) || 0) * 1000);
    return shifted.toISOString().slice(0, 10) === day;
  }) : rows;
  if (!shown.length) return null;
  const unit = metricMeta(metric).unit;
  if (metric === "sleep") {
    return (
      <div className="mt-2 flex flex-col gap-1.5">
        {shown.map((session, i) => (
          <div key={i} className="rounded-lg border border-gray-200 p-2 text-xs dark:border-neutral-700">
            <div className="text-gray-400">
              {localTime(session.start_time, session.tz_offset_seconds)}–{localTime(session.end_time, session.tz_offset_seconds)}
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {STAGE_ORDER.filter((k) => stageMinutes(session.stages)[k]).map((k) => (
                <span key={k} className="rounded-full bg-gray-100 px-2 py-0.5 dark:bg-neutral-800">
                  {k.toLowerCase()} · {stageMinutes(session.stages)[k]} min
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-gray-200 dark:border-neutral-700">
      <table className="w-full text-xs">
        <tbody>
          {shown.map((p, i) => (
            <tr key={i} className="border-b border-gray-50 last:border-0 dark:border-neutral-800">
              <td className="px-2 py-1 text-gray-400">
                {localTime(p.start_time, p.tz_offset_seconds)}–{localTime(p.end_time, p.tz_offset_seconds)}
              </td>
              <td className="px-2 py-1 text-right">
                {metric === "distance" || unit
                  ? formatMeasure(metric, p.value)
                  : (fmtNum(p.value) ?? "—")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
