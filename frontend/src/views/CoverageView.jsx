import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { cn, today } from "../lib";
import { usePhiPrivacy } from "../phiPrivacy";
import { subjectDisplayName } from "../utils/phi";
import { Badge, Empty } from "../ui";
import IntradaySeries from "../components/IntradaySeries";
import { filterSubjectList } from "../utils/subjects";
import {
  COVERAGE_END_KEY,
  COVERAGE_START_KEY,
  MAX_COVERAGE_DAYS,
  addIsoDays,
  adjacentInRange,
  bandStatus,
  daysByDate,
  dayTooltip,
  formatHours,
  formatLastPull,
  isoSpanDays,
  loadCachedCoverage,
  loadCachedDayPoints,
  mergeDayPoints,
  readCoverageCache,
  readCoverageRange,
  readDayPointsCache,
  readIsoPref,
  sliceCoverage,
  totalsTitle,
  weekdayLetter,
  weekLabel,
  writeCoverageRange,
  writeIsoPref,
} from "../utils/coverage";

const BAND_CLASS = {
  sufficient: "coverage-band-sufficient",
  partial: "coverage-band-partial",
  missing: "coverage-band-missing",
  not_expected: "coverage-band-not-expected",
};

export default function CoverageView({ studyId, guard, showRegistered = false, showArchived = false }) {
  const { hidePhi } = usePhiPrivacy();
  const [range, setRange] = useState(() => readCoverageRange());
  const [start, setStart] = useState(() => readIsoPref(COVERAGE_START_KEY));
  const [end, setEnd] = useState(() => readIsoPref(COVERAGE_END_KEY));
  const [full, setFull] = useState(() => (
    studyId == null ? null : readCoverageCache(studyId, showArchived)
  ));
  const [loading, setLoading] = useState(() => (
    studyId != null && !readCoverageCache(studyId, showArchived)
  ));
  const [selected, setSelected] = useState(null);
  const [points, setPoints] = useState([]);
  const [pointsLoading, setPointsLoading] = useState(false);
  const [pointsError, setPointsError] = useState("");
  const [tip, setTip] = useState(null);
  const [shownKey, setShownKey] = useState("");

  useEffect(() => { writeCoverageRange(range); }, [range]);
  useEffect(() => { writeIsoPref(COVERAGE_START_KEY, start); }, [start]);
  useEffect(() => { writeIsoPref(COVERAGE_END_KEY, end); }, [end]);

  const customInvalid = range === "custom" && (!start || !end || end < start);
  const customTooLong = range === "custom" && !!start && !!end && isoSpanDays(start, end) > MAX_COVERAGE_DAYS;
  const visible = useMemo(() => {
    if (!full) return null;
    return { ...full, subjects: filterSubjectList(full.subjects || [], { showRegistered }) };
  }, [full, showRegistered]);
  const data = useMemo(() => {
    if (!visible || customInvalid || customTooLong) return null;
    return sliceCoverage(visible, {
      range,
      start: range === "custom" ? start : undefined,
      end: range === "custom" ? end : undefined,
    });
  }, [visible, range, start, end, customInvalid, customTooLong]);

  useEffect(() => {
    setSelected(null);
  }, [studyId]);

  // One full calendar per study and Show archived. Show registered only filters.
  useEffect(() => {
    if (studyId == null) return undefined;
    const cached = readCoverageCache(studyId, showArchived);
    if (cached) {
      setFull(cached);
      setLoading(false);
      return undefined;
    }
    let alive = true;
    setLoading(true);
    guard(async () => {
      const body = await loadCachedCoverage(studyId, showArchived, () =>
        api.coverage(studyId, { range: "full", includeArchived: showArchived }));
      if (alive) setFull(body);
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [studyId, showArchived, guard]);

  const selectedSubject = data?.subjects?.find((s) => s.id === selected?.subjectId) || null;
  const selectedDay = selectedSubject?.days?.find((d) => d.date === selected?.date) || null;

  const selectionKey = selected ? `${selected.subjectId}|${selected.date}` : "";
  if (selectionKey !== shownKey) {
    setShownKey(selectionKey);
    if (!selected) {
      setPoints([]);
      setPointsLoading(false);
      setPointsError("");
    } else {
      const prevDay = addIsoDays(selected.date, -1);
      const todayHit = readDayPointsCache(selected.subjectId, selected.date);
      const prevHit = readDayPointsCache(selected.subjectId, prevDay);
      if (todayHit && prevHit) {
        setPoints(mergeDayPoints(todayHit, prevHit));
        setPointsLoading(false);
        setPointsError("");
      } else {
        setPoints([]);
        setPointsLoading(true);
        setPointsError("");
      }
    }
  }

  useEffect(() => {
    if (!selected) return undefined;
    const prevDay = addIsoDays(selected.date, -1);
    if (readDayPointsCache(selected.subjectId, selected.date) && readDayPointsCache(selected.subjectId, prevDay)) {
      return undefined;
    }
    let alive = true;
    Promise.all([
      loadCachedDayPoints(selected.subjectId, selected.date, (id, day) => api.dayPoints(id, day)),
      loadCachedDayPoints(selected.subjectId, prevDay, (id, day) => api.dayPoints(id, day)).catch(() => []),
    ]).then(([todayPts, prevPts]) => {
      if (!alive) return;
      setPoints(mergeDayPoints(todayPts, prevPts));
    }).catch((e) => {
      if (alive) setPointsError(e.message || "Could not load this day");
    }).finally(() => { if (alive) setPointsLoading(false); });
    return () => { alive = false; };
  }, [selected]);

  function chooseRange(next) {
    setRange(next);
    if (next === "custom" && (!start || !end)) {
      const endDay = today();
      setStart(addIsoDays(endDay, -6));
      setEnd(endDay);
    }
  }

  function selectDay(subject, day) {
    setTip(null);
    setSelected((cur) => (
      cur && cur.subjectId === subject.id && cur.date === day.date ? null : { subjectId: subject.id, date: day.date }
    ));
  }

  const prevDate = selectedSubject ? adjacentInRange(selectedSubject.days, selected?.date, -1) : null;
  const nextDate = selectedSubject ? adjacentInRange(selectedSubject.days, selected?.date, 1) : null;

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 px-4 py-3 dark:border-neutral-800">
        <Segmented
          label="Date range"
          value={range}
          onChange={chooseRange}
          options={[
            { id: "7d", label: "Last 7 days" },
            { id: "all", label: "All data" },
            { id: "custom", label: "Custom" },
          ]}
        />
        {range === "custom" && (
          <div className="flex items-center gap-2 text-sm">
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} aria-label="Custom start" className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
            <span className="text-gray-400">→</span>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="Custom end" className="rounded-lg border border-gray-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-800" />
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-gray-100 px-4 py-2 text-[11px] text-gray-500 dark:border-neutral-800 dark:text-neutral-400">
        <span>Bands, top to bottom: heart rate, steps, sleep. Each column is that participant&apos;s local day.</span>
        <Legend swatch="coverage-band-sufficient" label="Sufficient" />
        <Legend swatch="coverage-band-partial" label="Partial" />
        <Legend swatch="coverage-band-missing" label="Missing" />
        <Legend swatch="coverage-band-not-expected" label="Not expected" />
        <span className="text-gray-400">Dimmed days are outside the selected range. Totals count heart-rate days.</span>
      </div>
      <p className="border-b border-gray-100 px-4 py-1.5 text-[11px] text-gray-400 dark:border-neutral-800">
        Heart rate is sufficient at {hoursOf(data, "hr_sufficient_minutes", 600)} or more of intraday coverage
        (a daily average counts when intraday heart rate is not stored). Steps are sufficient at the same
        recording length, and a day total of 0 still counts. Sleep is sufficient at {hoursOf(data, "sleep_sufficient_minutes", 240)} asleep
        on the wake-up date.
      </p>

      {loading && full && (
        <p className="px-4 pt-2 text-[11px] text-gray-400">Updating coverage…</p>
      )}
      {customInvalid && <Empty>Pick a start date on or before the end date.</Empty>}
      {customTooLong && <Empty>That range is longer than {MAX_COVERAGE_DAYS} days.</Empty>}
      {!customInvalid && !customTooLong && loading && !data && <Empty>Loading coverage…</Empty>}
      {!customInvalid && !customTooLong && data && data.subjects.length === 0 && <Empty>No participants in this view.</Empty>}

      {!customInvalid && !customTooLong && data && data.subjects.length > 0 && (
        <div className={cn("overflow-x-auto", loading && full && "opacity-70")}>
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-gray-100 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400 dark:border-neutral-800">
                <th className="sticky left-0 z-10 bg-white px-4 py-2 dark:bg-neutral-900">Participant</th>
                <th className="px-3 py-2">Study weeks</th>
                <th className="px-3 py-2 text-center">On screen</th>
                <th className="px-3 py-2 text-center">To date</th>
                <th className="px-3 py-2">Last pull</th>
              </tr>
            </thead>
            <tbody>
              {data.subjects.map((subject) => (
                <SubjectRow
                  key={subject.id}
                  subject={subject}
                  weeks={data.weeks}
                  hidePhi={hidePhi}
                  selected={selected}
                  onSelect={selectDay}
                  onTip={setTip}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tip && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 max-w-xs whitespace-pre-line rounded-lg bg-neutral-900 px-3 py-2 text-xs text-white shadow-lg"
          style={{ left: Math.max(8, Math.min(tip.x, window.innerWidth - 280)), top: tip.y }}
        >
          {tip.text}
        </div>
      )}

      {selectedSubject && selectedDay && (
        <IntradaySeries
          name={subjectDisplayName(selectedSubject, hidePhi)}
          day={selectedDay}
          points={points}
          loading={pointsLoading}
          error={pointsError}
          onPrev={() => prevDate && setSelected({ subjectId: selectedSubject.id, date: prevDate })}
          onNext={() => nextDate && setSelected({ subjectId: selectedSubject.id, date: nextDate })}
          prevDisabled={!prevDate}
          nextDisabled={!nextDate}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

function hoursOf(data, key, fallback) {
  const minutes = data?.thresholds?.[key] ?? fallback;
  return formatHours(minutes);
}

function Segmented({ label, value, onChange, options }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-gray-200 p-0.5 text-xs dark:border-neutral-700">
      {options.map((opt) => (
        <button
          key={opt.id}
          type="button"
          aria-pressed={value === opt.id}
          onClick={() => onChange(opt.id)}
          className={cn(
            "rounded-md px-2.5 py-1 font-medium",
            value === opt.id
              ? "bg-maroon text-white"
              : "text-gray-600 hover:bg-gray-50 dark:text-neutral-300 dark:hover:bg-neutral-800",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Legend({ swatch, label }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={cn("h-2.5 w-4 rounded-sm", swatch)} />
      {label}
    </span>
  );
}

function SubjectRow({ subject, weeks, hidePhi, selected, onSelect, onTip }) {
  const byDate = useMemo(() => daysByDate(subject), [subject]);
  const name = subjectDisplayName(subject, hidePhi);
  return (
    <tr className="border-b border-gray-50 align-top dark:border-neutral-800/70">
      <td className={cn("sticky left-0 z-10 bg-white px-4 py-3 dark:bg-neutral-900", subject.archived && "opacity-70")}>
        <div className="max-w-[11rem] truncate text-sm font-medium">{name}</div>
        {!hidePhi && subject.participant_id && subject.subject_label && (
          <div className="max-w-[11rem] truncate text-[11px] text-gray-400">{subject.subject_label}</div>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {subject.archived && <Badge tone="maroon">Archived</Badge>}
          <span className="text-[11px] text-gray-400">{subject.status}</span>
        </div>
      </td>
      <td className="px-3 py-2">
        {weeks.map((week) => (
          <div key={week.start} className="mb-1.5">
            <div className="mb-0.5 flex items-baseline gap-2">
              <span className="text-[10px] text-gray-400">{weekLabel(week.dates)}</span>
            </div>
            <div className="flex gap-0.5">
              {week.dates.map((iso) => (
                <span key={`${iso}-h`} className="w-8 text-center text-[9px] font-medium uppercase text-gray-400">
                  {weekdayLetter(iso)}
                </span>
              ))}
            </div>
            <div className="mt-0.5 flex gap-0.5">
              {week.dates.map((iso) => (
                <DayCell
                  key={iso}
                  day={byDate[iso]}
                  today={subject.local_today}
                  selected={selected?.subjectId === subject.id && selected?.date === iso}
                  onSelect={() => byDate[iso] && onSelect(subject, byDate[iso])}
                  onTip={onTip}
                />
              ))}
            </div>
          </div>
        ))}
      </td>
      <Total tally={subject.on_screen} />
      <Total tally={subject.to_date} />
      <td className="whitespace-nowrap px-3 py-3 text-xs text-gray-500">{formatLastPull(subject.last_pull_at)}</td>
    </tr>
  );
}

function Total({ tally }) {
  return (
    <td className="px-3 py-3 text-center" title={totalsTitle(tally)}>
      <div className="text-sm font-semibold tabular-nums text-gray-800 dark:text-neutral-100">
        {tally?.hr_sufficient ?? 0}/{tally?.expected ?? 0}
      </div>
      <div className="text-[10px] text-gray-400">
        steps {tally?.steps_sufficient ?? 0} · sleep {tally?.sleep_sufficient ?? 0}
      </div>
    </td>
  );
}

function DayCell({ day, today, selected, onSelect, onTip }) {
  if (!day) return <span className="inline-block w-8" />;
  const bands = ["hr", "steps", "sleep"].map((key) => bandStatus(day, key));
  const label = dayTooltip(day).replaceAll("\n", ", ");
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={selected}
      onClick={onSelect}
      onMouseDown={() => onTip(null)}
      onMouseEnter={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        onTip({ text: dayTooltip(day), x: rect.left, y: rect.bottom + 6 });
      }}
      onMouseLeave={() => onTip(null)}
      className={cn(
        "flex w-8 flex-col items-stretch gap-px rounded-sm p-0.5 hover:bg-gray-100 dark:hover:bg-neutral-800",
        day.dimmed && "opacity-35",
        selected && "ring-2 ring-maroon dark:ring-gold",
        day.date === today && "outline outline-1 outline-offset-1 outline-maroon/40",
      )}
    >
      <span className="text-center text-[9px] leading-none text-gray-500">{Number(day.date.slice(8))}</span>
      {bands.map((status, i) => (
        <span key={i} className={cn("h-1 rounded-[1px]", BAND_CLASS[status] || BAND_CLASS.missing)} />
      ))}
    </button>
  );
}
