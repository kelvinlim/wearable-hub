import React, { useEffect, useState, useCallback } from "react";
import { ChevronRight, ChevronDown, Download, Ban, BatteryFull } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Select, Th, Td, Empty, SectionTitle } from "../ui";
import {
  cn, today, fmtNum, localTime, download, dailyCsv, pointsCsv,
  STAGE_ORDER, stageMinutes, providerLabel,
} from "../lib";

export default function SubjectDetail({ subject, canAdmin, guard, onChanged }) {
  const [daily, setDaily] = useState([]);
  const [devices, setDevices] = useState([]);
  const [openDay, setOpenDay] = useState(null);
  const [dayPts, setDayPts] = useState([]);
  const [start, setStart] = useState(subject.collection_start || today());
  const [end, setEnd] = useState(subject.collection_end || today());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [exFrom, setExFrom] = useState("");
  const [exTo, setExTo] = useState("");
  const [exFmt, setExFmt] = useState("json");

  const load = useCallback(() => guard(async () => setDaily(await api.daily(subject.id))), [guard, subject.id]);
  useEffect(() => { load(); }, [load]);
  // Paired-device snapshots are best-effort (needs the settings scope on the grant); never block.
  // A consolidate of a recent day refreshes them server-side, so re-fetch after a pull too.
  const loadDevices = useCallback(
    () => api.devices(subject.id).then(setDevices).catch(() => setDevices([])),
    [subject.id],
  );
  useEffect(() => {
    let alive = true;
    api.devices(subject.id).then((d) => alive && setDevices(d)).catch(() => alive && setDevices([]));
    return () => { alive = false; };
  }, [subject.id]);
  // Reset per-subject UI state when the selection changes (the component instance is reused),
  // re-seeding the consolidate range from the subject's collection window (or today).
  useEffect(() => {
    setOpenDay(null);
    setDayPts([]);
    setNotice("");
    setStart(subject.collection_start || today());
    setEnd(subject.collection_end || today());
  }, [subject.id, subject.collection_start, subject.collection_end]);

  const toggleDay = (date) =>
    guard(async () => {
      if (openDay === date) { setOpenDay(null); return; }
      setOpenDay(date);
      setDayPts(await api.dayPoints(subject.id, date));
    });

  const doExport = () =>
    guard(async () => {
      const data = await api.exportSubject(subject.id, exFrom || undefined, exTo || undefined);
      const who = subject.participant_id || subject.subject_label || `subject-${subject.id}`;
      const base = `${String(who).replace(/\s+/g, "_")}`;
      if (exFmt === "json") download(`${base}.json`, "application/json", JSON.stringify(data, null, 2));
      else if (exFmt === "csv-daily") download(`${base}-daily.csv`, "text/csv", dailyCsv(data));
      else download(`${base}-points.csv`, "text/csv", pointsCsv(data));
    });

  // Per-provider data backfill differs: Fitbit/Google is a synchronous server-side *pull*
  // (consolidate); Garmin has no pull — it re-pushes asynchronously via the backfill API.
  const providers = new Set((subject.registrations || []).map((r) => r.provider));
  const hasFitbit = providers.has("fitbit_gh");
  const hasGarmin = providers.has("garmin");

  const datesValid = () => {
    if (!start || !end) throw new Error("Pick both a start and end date.");
    if (end < start) throw new Error("End date must be on or after the start date.");
  };
  const doConsolidate = () =>
    guard(async () => {
      datesValid();
      setBusy(true);
      try { await api.consolidate(subject.id, start, end); await load(); await loadDevices(); }
      finally { setBusy(false); }
    });
  const doBackfill = () =>
    guard(async () => {
      datesValid();
      setBusy(true);
      setNotice("");
      try {
        const res = await api.backfill(subject.id, start, end);
        const types = res.types?.length ?? 0;
        const reqs = res.requests ?? 0;
        setNotice(`Backfill queued: ${reqs} request${reqs === 1 ? "" : "s"} (${types} data type${types === 1 ? "" : "s"} × ${res.windows} window${res.windows === 1 ? "" : "s"}). Garmin is rate-limited, so requests are spaced out and data re-pushes via webhook over the next several minutes — refresh later to see it.`);
      } finally { setBusy(false); }
    });

  const multiDevice = new Set(daily.map((d) => d.provider).filter(Boolean)).size > 1;
  const HEAD = ["Date", ...(multiDevice ? ["Device"] : []), "Steps", "Dist (m)", "Cal", "Floors", "Sleep", "HR avg", "Rest HR", "HRV", "SpO₂", "AZM", "MVPA", "Pts"];

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 p-4 dark:border-neutral-800">
        <SectionTitle>{subject.participant_id || subject.subject_label || "Subject"}</SectionTitle>
        {(subject.registrations || []).map((r) => (
          <Badge key={r.id} tone={r.registered ? "green" : "gray"} className="gap-1">
            <span className="font-semibold">{providerLabel(r.provider)}</span>
            <code className="rounded bg-black/5 px-1 text-[11px] dark:bg-white/10">{r.entry_code}</code>
            {r.registered ? "✓ linked" : "not linked"}
            {r.registered && canAdmin && (
              <button
                title={`Revoke ${providerLabel(r.provider)} authorization`}
                onClick={() => {
                  if (!confirm(`Revoke this subject's ${providerLabel(r.provider)} authorization?`)) return;
                  guard(async () => { await api.revoke(subject.id, r.provider); onChanged(); });
                }}
                className="ml-0.5 inline-flex text-red-600 hover:text-red-700"
              >
                <Ban className="h-3.5 w-3.5" />
              </button>
            )}
          </Badge>
        ))}
        {(subject.collection_start || subject.collection_end) && (
          <Badge tone="gold">
            collect {subject.collection_start || "…"} → {subject.collection_end || "…"}
          </Badge>
        )}
      </div>

      {/* Export + admin actions */}
      <div className="flex flex-col gap-3 border-b border-gray-100 p-4 dark:border-neutral-800">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Export</span>
          <input type="date" value={exFrom} onChange={(e) => setExFrom(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
          <span className="text-gray-400">→</span>
          <input type="date" value={exTo} onChange={(e) => setExTo(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
          <Select value={exFmt} onChange={(e) => setExFmt(e.target.value)} className="py-1">
            <option value="json">JSON</option>
            <option value="csv-daily">CSV — daily</option>
            <option value="csv-points">CSV — points</option>
          </Select>
          <Button variant="ghost" onClick={doExport}><Download className="h-4 w-4" /> Download</Button>
          <span className="text-xs text-gray-400">(blank = all)</span>
        </div>
        {canAdmin && (
          <div className="flex w-full flex-wrap items-center gap-2 text-sm">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Backfill</span>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
            <span className="text-gray-400">→</span>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
            {hasFitbit && (
              <Button
                disabled={busy || !start || !end}
                title={!start || !end ? "Pick both a start and end date" : "Fitbit/Google: pull + consolidate"}
                onClick={doConsolidate}
              >
                {busy ? "Pulling…" : "Pull + consolidate"}
              </Button>
            )}
            {hasGarmin && (
              <Button
                variant={hasFitbit ? "ghost" : undefined}
                disabled={busy || !start || !end}
                title={!start || !end ? "Pick both a start and end date" : "Garmin: request a re-push (async)"}
                onClick={doBackfill}
              >
                {busy ? "Requesting…" : "Request backfill"}
              </Button>
            )}
            <span className="text-xs text-gray-400">(both required)</span>
            <span className="text-xs text-gray-400">· revoke a device from its chip above</span>
            {notice && (
              <p className="basis-full text-xs text-emerald-600 dark:text-emerald-400">{notice}</p>
            )}
          </div>
        )}
      </div>

      {devices.length > 0 && <DevicesPanel devices={devices} />}

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="border-b border-gray-100 dark:border-neutral-800">
            <tr>{HEAD.map((h) => <Th key={h}>{h}</Th>)}</tr>
          </thead>
          <tbody>
            {daily.map((d) => (
              <React.Fragment key={d.date}>
                <tr
                  onClick={() => toggleDay(d.date)}
                  className="cursor-pointer border-b border-gray-50 hover:bg-gray-50 dark:border-neutral-800/60 dark:hover:bg-neutral-800/50"
                >
                  <Td className="font-medium">
                    <span className="mr-1 inline-flex align-middle text-gray-400">
                      {openDay === d.date ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </span>
                    {d.date}
                  </Td>
                  {multiDevice && <Td className="text-xs text-gray-500">{providerLabel(d.provider)}</Td>}
                  <Td>{cell(d.steps)}</Td>
                  <Td>{cell(d.distance_m)}</Td>
                  <Td>{cell(d.calories)}</Td>
                  <Td>{cell(d.floors)}</Td>
                  <Td>{cell(d.sleep_minutes)}</Td>
                  <Td>{cell(d.hr_avg)}</Td>
                  <Td>{cell(d.resting_hr)}</Td>
                  <Td>{cell(d.hrv_ms)}</Td>
                  <Td>{cell(d.spo2_avg)}</Td>
                  <Td>{cell(d.azm_total)}</Td>
                  <Td>{cell(d.mvpa_minutes)}</Td>
                  <Td className="text-gray-400">{d.point_count}</Td>
                </tr>
                {openDay === d.date && (
                  <tr className="bg-gray-50/70 dark:bg-neutral-800/30">
                    <td colSpan={HEAD.length} className="px-4 py-3">
                      <PointsView points={dayPts} daily={d} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
            {daily.length === 0 && (
              <tr><td colSpan={HEAD.length}><Empty>No consolidated days yet.</Empty></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function cell(v) {
  const f = fmtNum(v);
  return f == null ? <span className="text-gray-300 dark:text-neutral-600">—</span> : f;
}

// Battery status → tone for the level pill. Google returns High|Medium|Low|Empty.
const BATT_TONE = { High: "green", Medium: "gold", Low: "red", Empty: "red" };

function DevicesPanel({ devices }) {
  return (
    <div className="border-b border-gray-100 p-4 dark:border-neutral-800">
      <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Paired devices</span>
      <div className="mt-2 flex flex-wrap gap-3">
        {devices.map((d) => (
          <div key={d.device_name} className="min-w-[180px] rounded-lg border border-gray-200 p-3 text-sm dark:border-neutral-700">
            <div className="flex items-center gap-2 font-medium">
              <BatteryFull className="h-4 w-4 text-gray-400" />
              {d.device_version || d.device_type || "Device"}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
              {d.battery_level != null && (
                <Badge tone={BATT_TONE[d.battery_status] || "gray"}>{d.battery_level}%</Badge>
              )}
              {d.battery_status && <span className="text-gray-400">{d.battery_status}</span>}
              {d.device_type && <span className="text-gray-400">· {d.device_type}</span>}
            </div>
            {d.last_sync_time && (
              <div className="mt-1 text-xs text-gray-400">
                synced {new Date(d.last_sync_time).toLocaleString()}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function PointsView({ points, daily }) {
  const groups = {};
  for (const p of points) (groups[p.datatype] ||= []).push(p);
  return (
    <div className="space-y-3">
      <MeasuresSummary metrics={daily?.metrics} hasSleepPoints={!!groups.sleep} />
      {points.length === 0 ? (
        <div className="text-sm text-gray-400">
          No intraday point series for this day (sleep, stress &amp; other daily measures, when present,
          are summarized above; floors &amp; calories are rollup-only).
        </div>
      ) : (
        <div className="flex flex-wrap gap-4">
          {Object.entries(groups).map(([dt, list]) =>
        dt === "sleep" ? (
          <SleepGroup key="sleep" sessions={list} summary={daily?.metrics?.sleep} />
        ) : (
          <div key={dt} className="min-w-[150px]">
            <div className="mb-1 text-sm">
              <span className="font-semibold capitalize text-maroon dark:text-gold">{dt.replace(/_/g, " ")}</span>{" "}
              <span className="text-xs text-gray-400">· {list.length} pts</span>
            </div>
            <div className="max-h-56 overflow-y-auto rounded-lg border border-gray-200 bg-white dark:border-neutral-700 dark:bg-neutral-900">
              <table className="w-full text-xs">
                <tbody>
                  {list.map((p, i) => (
                    <tr key={i} className="border-b border-gray-50 last:border-0 dark:border-neutral-800">
                      <td className="px-2 py-1 text-gray-400">{localTime(p.start_time, p.tz_offset_seconds)}–{localTime(p.end_time, p.tz_offset_seconds)}</td>
                      <td className="px-2 py-1 text-right">{fmtNum(p.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
          )}
        </div>
      )}
    </div>
  );
}

// Daily measures that aren't intraday point series — sleep stages (Garmin), stress, respiration,
// SpO2, user metrics, skin temp, body composition — rendered from the day's `metrics` JSON so the
// backfilled/pushed summaries are visible. Sleep is shown here only when there are no intraday sleep
// points (Garmin); Fitbit's session-level sleep is rendered by SleepGroup instead.
function garminSleepStages(s) {
  return { DEEP: s?.deep_minutes, REM: s?.rem_minutes, LIGHT: s?.light_minutes, AWAKE: s?.awake_minutes };
}

const STRESS_BANDS = [
  ["rest", "rest_seconds"], ["low", "low_seconds"], ["medium", "medium_seconds"], ["high", "high_seconds"],
];

function MeasuresSummary({ metrics, hasSleepPoints }) {
  if (!metrics) return null;
  const m = metrics;
  const cards = [];

  if (!hasSleepPoints && m.sleep?.stages) {
    const st = garminSleepStages(m.sleep.stages);
    if (STAGE_ORDER.some((k) => st[k])) {
      const asleep = (m.sleep.stages.deep_minutes || 0) + (m.sleep.stages.light_minutes || 0) + (m.sleep.stages.rem_minutes || 0);
      cards.push(
        <MeasureCard key="sleep" title="Sleep" sub={asleep ? `${asleep}m asleep` : null}>
          <div className="basis-full"><StageChips stages={st} /></div>
        </MeasureCard>
      );
    }
  }

  const s = m.stress;
  if (s && (s.avg != null || s.max != null)) {
    cards.push(
      <MeasureCard key="stress" title="Stress">
        <Stat label="avg" value={s.avg} />
        <Stat label="max" value={s.max} />
        {STRESS_BANDS.map(([lab, key]) =>
          s[key] != null ? <Stat key={key} label={lab} value={Math.round(s[key] / 60)} unit="m" /> : null
        )}
      </MeasureCard>
    );
  }

  const r = m.respiration;
  if (r && (r.avg != null || r.min != null || r.max != null)) {
    cards.push(
      <MeasureCard key="resp" title="Respiration" sub="brpm">
        <Stat label="avg" value={r.avg} />
        <Stat label="min" value={r.min} />
        <Stat label="max" value={r.max} />
      </MeasureCard>
    );
  }

  const o = m.spo2;
  if (o && (o.avg != null || o.min != null || o.max != null)) {
    cards.push(
      <MeasureCard key="spo2" title="SpO₂" sub="%">
        <Stat label="avg" value={o.avg} />
        <Stat label="min" value={o.min} />
        <Stat label="max" value={o.max} />
      </MeasureCard>
    );
  }

  const u = m.user_metrics;
  if (u && (u.vo2_max != null || u.vo2_max_cycling != null || u.fitness_age != null)) {
    cards.push(
      <MeasureCard key="um" title="User metrics">
        <Stat label="VO₂max" value={u.vo2_max} />
        <Stat label="VO₂max cyc" value={u.vo2_max_cycling} />
        <Stat label="fitness age" value={u.fitness_age} />
      </MeasureCard>
    );
  }

  const t = m.skin_temp;
  if (t && t.deviation_c != null) {
    cards.push(
      <MeasureCard key="skin" title="Skin temp" sub="vs baseline">
        <Stat label="dev" value={t.deviation_c} unit="°C" />
        <Stat label="min" value={t.min_deviation_c} unit="°C" />
        <Stat label="max" value={t.max_deviation_c} unit="°C" />
      </MeasureCard>
    );
  }

  const b = m.body_composition;
  if (b && (b.weight_kg != null || b.bmi != null || b.body_fat_percent != null)) {
    cards.push(
      <MeasureCard key="body" title="Body composition">
        <Stat label="weight" value={b.weight_kg} unit="kg" />
        <Stat label="BMI" value={b.bmi} />
        <Stat label="body fat" value={b.body_fat_percent} unit="%" />
      </MeasureCard>
    );
  }

  if (!cards.length) return null;
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">Daily measures</div>
      <div className="flex flex-wrap gap-2.5">{cards}</div>
    </div>
  );
}

function MeasureCard({ title, sub, children }) {
  return (
    <div className="min-w-[140px] rounded-lg border border-gray-200 bg-white p-2.5 dark:border-neutral-700 dark:bg-neutral-900">
      <div className="mb-1 text-sm">
        <span className="font-semibold text-maroon dark:text-gold">{title}</span>
        {sub && <span className="text-xs text-gray-400"> · {sub}</span>}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5">{children}</div>
    </div>
  );
}

function Stat({ label, value, unit }) {
  if (value == null) return null;
  return (
    <span className="whitespace-nowrap text-xs text-gray-700 dark:text-neutral-200">
      <span className="text-gray-400">{label}</span> {fmtNum(value)}{unit || ""}
    </span>
  );
}

const STAGE_CLR = {
  DEEP: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-200",
  REM: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
  LIGHT: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
  AWAKE: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-200",
};

function StageChips({ stages }) {
  const keys = STAGE_ORDER.filter((k) => stages?.[k]);
  if (!keys.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {keys.map((k) => (
        <span key={k} className={cn("whitespace-nowrap rounded-full px-2 py-0.5 text-[11px]", STAGE_CLR[k])}>
          {k.toLowerCase()} {stages[k]}m
        </span>
      ))}
    </span>
  );
}

function SleepGroup({ sessions, summary }) {
  return (
    <div className="min-w-[260px]">
      <div className="mb-1 text-sm">
        <span className="font-semibold text-maroon dark:text-gold">Sleep</span>
        {summary && (
          <span className="text-xs text-gray-400">
            {" "}· {summary.asleep_min}m asleep / {summary.total_min}m in bed · {summary.segments} session{summary.segments === 1 ? "" : "s"}
          </span>
        )}
      </div>
      {summary?.stages && <div className="mb-2"><StageChips stages={summary.stages} /></div>}
      <div className="flex flex-col gap-1.5">
        {sessions.map((s, i) => {
          const a = new Date(s.start_time + "Z");
          const b = new Date(s.end_time + "Z");
          const dur = !isNaN(a) && !isNaN(b) ? Math.round((b - a) / 60000) : null;
          return (
            <div key={i} className="rounded-lg border border-gray-200 bg-white p-2 dark:border-neutral-700 dark:bg-neutral-900">
              <div className="mb-1 text-xs text-gray-400">
                {localTime(s.start_time, s.tz_offset_seconds)}–{localTime(s.end_time, s.tz_offset_seconds)}{dur != null ? ` · ${dur}m` : ""}
              </div>
              <StageChips stages={stageMinutes(s.stages)} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
