import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { studyDailyCsv, studyPointsCsv } from "./lib.js";

const payload = {
  subjects: [
    {
      subject: {
        id: 42,
        participant_id: "P-001",
        subject_label: "alice@umn.edu",
        registrations: [{ provider: "fitbit_gh", entry_code: "abc123" }],
      },
      days: [
        {
          date: "2026-09-30",
          provider: "fitbit_gh",
          steps: 100,
          metrics: {},
          points: [{ datatype: "steps", start_time: "t0", end_time: "t1", value: 100 }],
        },
      ],
    },
  ],
};

describe("study CSV Hide PHI", () => {
  it("keeps Study ID and account label when off", () => {
    const csv = studyDailyCsv(payload, false);
    assert.match(csv, /alice@umn.edu/);
    assert.match(csv, /P-001/);
    assert.match(csv, /abc123/);
  });

  it("replaces label with su-{id} and blanks Study ID when on", () => {
    const daily = studyDailyCsv(payload, true);
    const points = studyPointsCsv(payload, true);
    for (const csv of [daily, points]) {
      assert.match(csv, /su-42/);
      assert.equal(csv.includes("alice@umn.edu"), false);
      assert.equal(csv.includes("P-001"), false);
      assert.match(csv, /abc123/); // entry codes stay (operational, not names)
    }
  });
});
