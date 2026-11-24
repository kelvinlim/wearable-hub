import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  COVERAGE_ARCHIVED_KEY,
  COVERAGE_RANGE_KEY,
  SUBJECTS_MODE_KEY,
  adjacentInRange,
  bandStatus,
  dayTooltip,
  metricChoices,
  readCoverageRange,
  readIncludeArchived,
  readSubjectsMode,
  seriesFor,
  sleepPieces,
  wakeDate,
  weekdayLetter,
  weekLabel,
  writeCoverageRange,
  writeIncludeArchived,
  writeSubjectsMode,
} from "./coverage.js";

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
  });
});
