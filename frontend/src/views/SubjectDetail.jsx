import React, { useEffect, useState, useCallback } from "react";
import { ChevronRight, ChevronDown, Download, Ban } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Select, Th, Td, Empty, SectionTitle } from "../ui";
import {
  cn, today, fmtNum, localTime, download, dailyCsv, pointsCsv,
  STAGE_ORDER, stageMinutes,
} from "../lib";

export default function SubjectDetail({ subject, canAdmin, guard, onChanged }) {
  const [daily, setDaily] = useState([]);
  const [openDay, setOpenDay] = useState(null);
  const [dayPts, setDayPts] = useState([]);
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(today());
  const [busy, setBusy] = useState(false);
  const [exFrom, setExFrom] = useState("");
  const [exTo, setExTo] = useState("");
  const [exFmt, setExFmt] = useState("json");

  const load = useCallback(() => guard(async () => setDaily(await api.daily(subject.id))), [guard, subject.id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setOpenDay(null); setDayPts([]); }, [subject.id]);

  const toggleDay = (date) =>
    guard(async () => {
      if (openDay === date) { setOpenDay(null); return; }
      setOpenDay(date);
      setDayPts(await api.dayPoints(subject.id, date));
    });

  const doExport = () =>
    guard(async () => {
      const data = await api.exportSubject(subject.id, exFrom || undefined, exTo || undefined);
      const base = `${(subject.subject_label || "subject").replace(/\s+/g, "_")}-${subject.entry_code}`;
      if (exFmt === "json") download(`${base}.json`, "application/json", JSON.stringify(data, null, 2));
      else if (exFmt === "csv-daily") download(`${base}-daily.csv`, "text/csv", dailyCsv(data));
      else download(`${base}-points.csv`, "text/csv", pointsCsv(data));
    });

  const HEAD = ["Date", "Steps", "Dist (m)", "Cal", "Floors", "Sleep", "HR avg", "Rest HR", "HRV", "Pts"];

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 p-4 dark:border-neutral-800">
        <SectionTitle>{subject.subject_label || "Subject"}</SectionTitle>
        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">{subject.entry_code}</code>
        {subject.registered ? <Badge tone="green">linked</Badge> : <Badge>not linked</Badge>}
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
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">Consolidate</span>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
            <span className="text-gray-400">→</span>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
            <Button
              disabled={busy}
              onClick={() => guard(async () => { setBusy(true); try { await api.consolidate(subject.id, start, end); await load(); } finally { setBusy(false); } })}
            >
              {busy ? "Pulling…" : "Pull + consolidate"}
            </Button>
            <Button
              variant="danger"
              onClick={() => { if (confirm("Revoke this subject's wearable authorization?")) guard(async () => { await api.revoke(subject.id); onChanged(); }); }}
            >
              <Ban className="h-4 w-4" /> Revoke
            </Button>
          </div>
        )}
      </div>

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
                  <Td>{cell(d.steps)}</Td>
                  <Td>{cell(d.distance_m)}</Td>
                  <Td>{cell(d.calories)}</Td>
                  <Td>{cell(d.floors)}</Td>
                  <Td>{cell(d.sleep_minutes)}</Td>
                  <Td>{cell(d.hr_avg)}</Td>
                  <Td>{cell(d.resting_hr)}</Td>
                  <Td>{cell(d.hrv_ms)}</Td>
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

function PointsView({ points, daily }) {
  if (!points.length)
    return <div className="text-sm text-gray-400">No intraday points (floors &amp; calories are rollup-only).</div>;
  const groups = {};
  for (const p of points) (groups[p.datatype] ||= []).push(p);
  return (
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
