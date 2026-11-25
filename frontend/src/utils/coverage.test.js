import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  COVERAGE_ARCHIVED_KEY,
  COVERAGE_RANGE_KEY,
  SUBJECTS_MODE_KEY,
  addIsoDays,
  adjacentInRange,
  bandStatus,
  dayPanels,
  dayTooltip,
  formatHit,
  formatMeasure,
  hitAt,
  loadCachedCoverage,
  loadCachedDayPoints,
  metricChoices,
  readoutAt,
  readCoverageRange,
  readDayPointsCache,
  readIncludeArchived,
  readSubjectsMode,
  seriesFor,
  sliceCoverage,
  sleepPieces,
  sleepStageLane,
  wakeDate,
  weekdayLetter,
  weekLabel,
  writeCoverageCache,
  writeCoverageRange,
  writeIncludeArchived,
  writeSubjectsMode,
} from "./coverage.js";
import { filterSubjectList, SHOW_ARCHIVED_KEY, SHOW_REGISTERED_KEY } from "./subjects.js";

function memoryStore(seed = {}) {
  const data = { ...seed };
  return {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: (k) => { delete data[k]; },
  };
}

describe("coverage localStorage prefs", () => {
  it("defaults to active participants, last 7 days, and the list view", () => {
    const store = memoryStore();
    assert.equal(COVERAGE_ARCHIVED_KEY, "wh-coverage-include-archived");
    assert.equal(COVERAGE_RANGE_KEY, "wh-coverage-range");
    assert.equal(SUBJECTS_MODE_KEY, "wh-subjects-mode");
    assert.equal(readIncludeArchived(store), false);
    assert.equal(readCoverageRange(store), "7d");
    assert.equal(readSubjectsMode(store), "list");
  });

  it("round-trips the status filter, date range, and subjects mode", () => {
    const store = memoryStore();
    writeIncludeArchived(true, store);
    writeCoverageRange("all", store);
    writeSubjectsMode("coverage", store);
    assert.equal(readIncludeArchived(store), true);
    assert.equal(store.getItem(COVERAGE_ARCHIVED_KEY), "1");
    assert.equal(readCoverageRange(store), "all");
    assert.equal(readSubjectsMode(store), "coverage");
  });

  it("ignores an unknown range and an unknown mode", () => {
    const store = memoryStore({ [COVERAGE_RANGE_KEY]: "forever", [SUBJECTS_MODE_KEY]: "grid" });
    assert.equal(readCoverageRange(store), "7d");
    assert.equal(readSubjectsMode(store), "list");
  });
});

describe("coverage day presentation", () => {
  const day = {
    date: "2026-11-20",
    dimmed: false,
    expected: true,
    reason: null,
    hr: { status: "partial", basis: "intraday", minutes: 120, hr_avg: 70 },
    steps: { status: "sufficient", basis: "daily_total", total: 0, minutes: null },
    sleep: { status: "sufficient", basis: "wake_date", minutes: 360 },
  };

  it("keeps Monday–Sunday letters and a week caption", () => {
    assert.equal(weekdayLetter("2026-11-16"), "M");
    assert.equal(weekdayLetter("2026-11-22"), "S");
    assert.equal(weekLabel(["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"]), "Nov 16–22");
    assert.equal(weekLabel(["2026-11-30", "2026-12-06"]), "Nov 30–Dec 6");
  });

  it("hatches every band when the day is not expected", () => {
    const outside = { ...day, expected: false, reason: "collection_window" };
    assert.equal(bandStatus(outside, "hr"), "not_expected");
    assert.equal(bandStatus(outside, "steps"), "not_expected");
    assert.equal(bandStatus(outside, "sleep"), "not_expected");
    assert.equal(bandStatus(day, "hr"), "partial");
    assert.match(dayTooltip(outside), /outside the collection window/);
  });

  it("shows a zero step total as recorded data, plus HR coverage and sleep", () => {
    const tip = dayTooltip(day);
    assert.match(tip, /Heart rate: 2 h coverage — partial/);
    assert.match(tip, /Steps: 0 steps — sufficient/);
    assert.match(tip, /Sleep: 6 h asleep — sufficient/);
  });

  it("steps to the next in-range day and skips dimmed padding", () => {
    const days = [
      { date: "2026-11-16", dimmed: true },
      { date: "2026-11-17", dimmed: false },
      { date: "2026-11-18", dimmed: false },
    ];
    assert.equal(adjacentInRange(days, "2026-11-17", 1), "2026-11-18");
    assert.equal(adjacentInRange(days, "2026-11-17", -1), null);
    assert.equal(adjacentInRange(days, "2026-11-18", 1), null);
  });
});

describe("intraday series for the day drill-in", () => {
  it("assigns a midnight-crossing sleep session to the wake-up date", () => {
    const point = {
      datatype: "sleep",
      start_time: "2026-11-17T22:00:00",
      end_time: "2026-11-18T06:00:00",
      tz_offset_seconds: 0,
      stages: [
        { type: "LIGHT", start_time: "2026-11-17T22:00:00", end_time: "2026-11-18T02:00:00" },
        { type: "DEEP", start_time: "2026-11-18T02:00:00", end_time: "2026-11-18T06:00:00" },
      ],
    };
    assert.equal(wakeDate(point), "2026-11-18");
    const onWake = seriesFor([point], "sleep", "2026-11-18");
    assert.equal(onWake.length, 1);
    assert.equal(seriesFor([point], "sleep", "2026-11-17").length, 0);
    const pieces = sleepPieces(onWake[0], "2026-11-18");
    assert.deepEqual(pieces.map((p) => [p.type, p.start, p.end]), [
      ["LIGHT", 22 * 60 - 1440, 2 * 60],
      ["DEEP", 2 * 60, 6 * 60],
    ]);
    assert.equal(sleepStageLane("LIGHT"), 2);
    assert.equal(sleepStageLane("REM"), 1);
    assert.equal(sleepStageLane("SLEEP"), null);
    assert.equal(sleepStageLane("unknown"), null);
  });

  it("builds a heart-rate segment from the local clock and offers extra metrics", () => {
    const points = [
      {
        datatype: "heart_rate",
        start_time: "2026-11-18T14:00:00Z",
        end_time: "2026-11-18T14:05:00Z",
        tz_offset_seconds: 0,
        value: 72,
      },
      { datatype: "stress", start_time: "2026-11-18T14:00:00Z", value: 20, tz_offset_seconds: 0 },
    ];
    const series = seriesFor(points, "heart_rate", "2026-11-18");
    assert.equal(series.length, 1);
    assert.equal(series[0].startMin, 14 * 60);
    assert.equal(series[0].value, 72);
    assert.deepEqual(
      metricChoices(points).map((m) => m.id),
      ["heart_rate", "steps", "sleep", "stress"],
    );
    assert.equal(formatMeasure("heart_rate", 72), "72 bpm");
    assert.equal(formatMeasure("heart_rate_variability", 42), "42 ms");
    assert.equal(formatMeasure("steps", 120), "120 steps");
    assert.equal(formatMeasure("oxygen_saturation", 97.5), "97.5 %");
    // Google Health distance points are millimeter sums; show meters.
    assert.equal(formatMeasure("distance", 1500), "1.5 m");
    assert.equal(formatMeasure("stress", 20), "20");
    assert.equal(formatMeasure("stress", 20).includes("unit"), false);
  });

  it("stacks sleep, then heart rate and steps, then only extras present that day", () => {
    const points = [
      { datatype: "heart_rate_variability", start_time: "2026-11-18T02:00:00Z", end_time: "2026-11-18T02:05:00Z", value: 41, tz_offset_seconds: 0 },
      { datatype: "oxygen_saturation", start_time: "2026-11-18T02:10:00Z", end_time: "2026-11-18T02:15:00Z", value: 96, tz_offset_seconds: 0 },
      { datatype: "distance", start_time: "2026-11-17T02:00:00Z", end_time: "2026-11-17T02:05:00Z", value: 1000, tz_offset_seconds: 0 },
    ];
    const panels = dayPanels(points, "2026-11-18");
    assert.deepEqual(panels.map((p) => p.id), ["sleep", "heart_rate", "steps", "heart_rate_variability", "oxygen_saturation"]);
    assert.equal(panels[0].empty, true);
    assert.equal(panels[1].empty, true);
    assert.equal(panels[2].empty, true);
    assert.equal(panels[3].unit, "ms");
    assert.equal(panels[4].unit, "%");
    assert.equal(dayPanels([], "2026-11-18").map((p) => p.id).join(), "sleep,heart_rate,steps");
  });

  it("reads every series at one local time, with the mark's range and unit", () => {
    const points = [
      { datatype: "heart_rate", start_time: "2026-11-18T14:00:00Z", end_time: "2026-11-18T14:05:00Z", value: 72, tz_offset_seconds: 0 },
      { datatype: "steps", start_time: "2026-11-18T14:00:00Z", end_time: "2026-11-18T14:05:00Z", value: 40, tz_offset_seconds: 0 },
      {
        datatype: "sleep",
        start_time: "2026-11-17T22:00:00Z",
        end_time: "2026-11-18T06:00:00Z",
        tz_offset_seconds: 0,
        stages: [
          { type: "LIGHT", start_time: "2026-11-17T22:00:00Z", end_time: "2026-11-18T02:00:00Z" },
          { type: "DEEP", start_time: "2026-11-18T02:00:00Z", end_time: "2026-11-18T06:00:00Z" },
        ],
      },
    ];
    const panels = dayPanels(points, "2026-11-18");
    assert.deepEqual(panels.map((p) => p.id).slice(0, 3), ["sleep", "heart_rate", "steps"]);
    const atTwo = readoutAt(panels, 2 * 60, "2026-11-18");
    const byId = Object.fromEntries(atTwo.map((row) => [row.id, row]));
    assert.equal(atTwo[0].id, "sleep");
    assert.equal(byId.heart_rate.text, null);
    assert.equal(byId.steps.text, null);
    assert.match(byId.sleep.text, /deep · 240 min/);
    const hr = hitAt(panels.find((p) => p.id === "heart_rate"), 14 * 60, "2026-11-18");
    assert.equal(formatHit(hr), "14:00–14:05 · 72 bpm");
    const steps = hitAt(panels.find((p) => p.id === "steps"), 14 * 60, "2026-11-18");
    assert.equal(formatHit(steps), "14:00–14:05 · 40 steps");
  });
});

describe("coverage range slicing and memory cache", () => {
  function cell(date, extra = {}) {
    return {
      date,
      dimmed: extra.dimmed ?? false,
      expected: extra.expected ?? true,
      reason: extra.reason ?? null,
      hr: extra.hr || { status: "missing", basis: "none", minutes: null, fraction: null, hr_avg: null },
      steps: extra.steps || { status: "missing", basis: "none", total: null, minutes: null, fraction: null },
      sleep: extra.sleep || { status: "missing", basis: "none", minutes: null },
    };
  }

  function buildFull() {
    const days = [];
    for (let iso = "2026-11-09"; iso <= "2026-11-29"; iso = addIsoDays(iso, 1)) {
      const before = iso < "2026-11-22";
      const future = iso > "2026-11-24";
      const day = cell(iso, {
        expected: !before && !future,
        reason: future ? "future" : before ? "before_enrollment" : null,
        dimmed: before || future,
      });
      if (iso === "2026-11-10") {
        day.steps = { status: "sufficient", basis: "daily_total", total: 5, minutes: null, fraction: null };
        day.hr = { status: "sufficient", basis: "daily_summary", minutes: null, fraction: null, hr_avg: 60 };
      }
      if (iso === "2026-11-22") {
        day.hr = { status: "sufficient", basis: "intraday", minutes: 600, fraction: 0.4, hr_avg: 68 };
      }
      days.push(day);
    }
    const toDate = { hr_sufficient: 1, steps_sufficient: 0, sleep_sufficient: 0, expected: 3 };
    return {
      range: "full",
      thresholds: { hr_sufficient_minutes: 600, sleep_sufficient_minutes: 240 },
      subjects: [{
        id: 1,
        local_today: "2026-11-24",
        enrolled_on: "2026-11-22",
        all_start: "2026-11-22",
        all_end: "2026-11-24",
        collection_start: null,
        collection_end: null,
        to_date: toDate,
        days,
      }],
    };
  }

  it("slices last 7 days with Monday padding and keeps to-date totals", () => {
    const full = buildFull();
    const view = sliceCoverage(full, { range: "7d" });
    assert.equal(view.range, "7d");
    assert.equal(view.weeks[0].dates[0], "2026-11-16");
    assert.equal(view.weeks.at(-1).dates.at(-1), "2026-11-29");
    const days = Object.fromEntries(view.subjects[0].days.map((d) => [d.date, d]));
    assert.equal(days["2026-11-16"].dimmed, true);
    assert.equal(days["2026-11-18"].dimmed, false);
    assert.equal(days["2026-11-18"].expected, false);
    assert.equal(days["2026-11-22"].dimmed, false);
    assert.equal(days["2026-11-22"].hr.status, "sufficient");
    assert.equal(days["2026-11-24"].dimmed, false);
    assert.equal(days["2026-11-25"].dimmed, true);
    assert.equal(days["2026-11-25"].reason, "future");
    assert.equal(view.subjects[0].on_screen.expected, 3);
    assert.equal(view.subjects[0].on_screen.hr_sufficient, 1);
    assert.equal(view.subjects[0].to_date, full.subjects[0].to_date);
    assert.equal(days["2026-11-10"], undefined);
    // Slicing must not rewrite the cached full calendar.
    const cachedNov20 = full.subjects[0].days.find((d) => d.date === "2026-11-20");
    assert.equal(cachedNov20.dimmed, true);
  });

  it("keeps all-data to the all-data window and still finds earlier days in a custom range", () => {
    const full = buildFull();
    const all = sliceCoverage(full, { range: "all" });
    assert.equal(all.weeks[0].dates[0], "2026-11-16");
    assert.equal(all.subjects[0].on_screen.expected, 3);
    assert.equal(all.subjects[0].to_date, full.subjects[0].to_date);
    const custom = sliceCoverage(full, { range: "custom", start: "2026-11-09", end: "2026-11-11" });
    const nov10 = custom.subjects[0].days.find((d) => d.date === "2026-11-10");
    assert.equal(nov10.dimmed, false);
    assert.equal(nov10.steps.total, 5);
    assert.equal(nov10.expected, false);
    assert.equal(custom.subjects[0].on_screen.expected, 0);
    assert.equal(custom.weeks[0].dates[0], "2026-11-09");
    const later = sliceCoverage(full, { range: "custom", start: "2026-11-30", end: "2026-12-02" });
    const dec1 = later.subjects[0].days.find((d) => d.date === "2026-12-01");
    assert.equal(dec1.reason, "future");
    assert.equal(dec1.hr.status, "missing");
    assert.equal(dec1.dimmed, false);
  });

  it("pads a shared week from each participant's own local today", () => {
    const bare = (id, today) => ({
      id,
      local_today: today,
      enrolled_on: "2026-01-01",
      all_start: "2026-01-01",
      all_end: today,
      collection_start: null,
      collection_end: null,
      to_date: { hr_sufficient: 0, steps_sufficient: 0, sleep_sufficient: 0, expected: 1 },
      days: [],
    });
    const full = { range: "full", subjects: [bare(1, "2026-11-24"), bare(2, "2026-11-23")] };
    const view = sliceCoverage(full, { range: "7d" });
    assert.equal(view.weeks[0].dates[0], "2026-11-16");
    const a = Object.fromEntries(view.subjects[0].days.map((d) => [d.date, d]));
    const b = Object.fromEntries(view.subjects[1].days.map((d) => [d.date, d]));
    assert.equal(a["2026-11-17"].dimmed, true);
    assert.equal(a["2026-11-18"].dimmed, false);
    assert.equal(a["2026-11-24"].dimmed, false);
    assert.equal(b["2026-11-17"].dimmed, false);
    assert.equal(b["2026-11-24"].dimmed, true);
    assert.equal(view.subjects[0].to_date, full.subjects[0].to_date);
  });

  it("keeps the full calendar and opened days in memory only", async () => {
    const store = memoryStore();
    const cache = new Map();
    const dayCache = new Map();
    let coverageCalls = 0;
    let pointCalls = 0;
    const payload = { range: "full", subjects: [] };
    const first = await loadCachedCoverage(4, false, async () => {
      coverageCalls += 1;
      return payload;
    }, cache);
    const second = await loadCachedCoverage(4, false, async () => {
      coverageCalls += 1;
      return payload;
    }, cache);
    assert.equal(coverageCalls, 1);
    assert.equal(first, second);
    await loadCachedCoverage(4, true, async () => {
      coverageCalls += 1;
      return { range: "full", subjects: [{ id: 9 }] };
    }, cache);
    assert.equal(coverageCalls, 2);
    writeCoverageCache(4, false, payload, cache);
    assert.equal(store.getItem("wh-coverage-range"), null);

    const points = await loadCachedDayPoints(8, "2026-11-20", async () => {
      pointCalls += 1;
      return [{ datatype: "steps", value: 3 }];
    }, dayCache);
    const again = await loadCachedDayPoints(8, "2026-11-20", async () => {
      pointCalls += 1;
      return [{ datatype: "steps", value: 9 }];
    }, dayCache);
    assert.equal(pointCalls, 1);
    assert.equal(again, points);
    assert.equal(again[0].value, 3);
    await assert.rejects(loadCachedDayPoints(8, "2026-11-21", async () => {
      throw new Error("offline");
    }, dayCache));
    assert.equal(readDayPointsCache(8, "2026-11-21", dayCache), null);
  });

  it("applies Show registered like the subjects list and leaves the cached calendar intact", () => {
    const full = buildFull();
    full.subjects[0].registered = true;
    full.subjects.push({
      ...full.subjects[0],
      id: 2,
      registered: false,
      days: full.subjects[0].days.map((d) => ({ ...d })),
    });
    const linked = filterSubjectList(full.subjects, { showRegistered: true });
    assert.deepEqual(linked.map((s) => s.id), [1]);
    const view = sliceCoverage({ ...full, subjects: linked }, { range: "7d" });
    assert.deepEqual(view.subjects.map((s) => s.id), [1]);
    assert.equal(full.subjects.length, 2);
    assert.equal(full.subjects[1].registered, false);
    // Show registered does not change the archive cache key.
    const cache = new Map();
    writeCoverageCache(4, false, full, cache);
    writeCoverageCache(4, true, { ...full, subjects: full.subjects }, cache);
    assert.equal(cache.size, 2);
    assert.equal(SHOW_REGISTERED_KEY, "wh-show-registered");
    assert.equal(SHOW_ARCHIVED_KEY, "wh-show-archived");
  });
});
