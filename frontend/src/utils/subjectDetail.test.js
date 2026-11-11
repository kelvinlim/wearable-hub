import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readStoredFlag, writeStoredFlag } from "./subjects.js";
import {
  DATA_MANAGEMENT_OPEN_KEY,
  PAIRED_DEVICES_OPEN_KEY,
  dataManagementHint,
  formatIsoDateMdY,
  pairedDevicesHint,
} from "./subjectDetail.js";

function memoryStore(seed = {}) {
  const data = { ...seed };
  return {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
  };
}

const detailSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../views/SubjectDetail.jsx"),
  "utf8",
);

describe("subject detail section structure", () => {
  it("keeps the subject header (id, chips, collection window) above Data management", () => {
    const header = detailSrc.indexOf("subjectDisplayName");
    const collect = detailSrc.indexOf("collect {subject.collection_start");
    const dataMgmt = detailSrc.indexOf('title="Data management"');
    assert.ok(header > 0 && collect > header && dataMgmt > collect);
  });

  it("wraps Export and Backfill in Data management, with Paired devices outside it", () => {
    const dataMgmt = detailSrc.indexOf('title="Data management"');
    const dataMgmtEnd = detailSrc.indexOf("</CollapsibleSection>", dataMgmt);
    const block = detailSrc.slice(dataMgmt, dataMgmtEnd);
    assert.match(block, />Export</);
    assert.match(block, />Backfill</);
    assert.doesNotMatch(block, /Paired devices/);

    const paired = detailSrc.indexOf('title="Paired devices"');
    assert.ok(paired > dataMgmtEnd);
  });

  it("drops the inner Export-row toggle from 0.9.3", () => {
    assert.equal(detailSrc.includes("EXPORT_OPEN_KEY"), false);
    assert.equal(detailSrc.includes("wh-export-open"), false);
    assert.equal(detailSrc.includes("exportOpen"), false);
  });

  it("defaults both new sections closed and persists with dedicated keys", () => {
    assert.match(detailSrc, /readStoredFlag\(DATA_MANAGEMENT_OPEN_KEY, false\)/);
    assert.match(detailSrc, /readStoredFlag\(PAIRED_DEVICES_OPEN_KEY, false\)/);
    assert.match(detailSrc, /writeStoredFlag\(DATA_MANAGEMENT_OPEN_KEY/);
    assert.match(detailSrc, /writeStoredFlag\(PAIRED_DEVICES_OPEN_KEY/);
  });
});

describe("subject detail localStorage prefs", () => {
  it("uses dedicated wh-* keys", () => {
    assert.equal(DATA_MANAGEMENT_OPEN_KEY, "wh-data-management-open");
    assert.equal(PAIRED_DEVICES_OPEN_KEY, "wh-paired-devices-open");
  });

  it("defaults both sections closed when unset", () => {
    const store = memoryStore();
    assert.equal(readStoredFlag(DATA_MANAGEMENT_OPEN_KEY, false, store), false);
    assert.equal(readStoredFlag(PAIRED_DEVICES_OPEN_KEY, false, store), false);
  });

  it("round-trips open and closed", () => {
    const store = memoryStore();
    writeStoredFlag(DATA_MANAGEMENT_OPEN_KEY, true, store);
    writeStoredFlag(PAIRED_DEVICES_OPEN_KEY, true, store);
    assert.equal(readStoredFlag(DATA_MANAGEMENT_OPEN_KEY, false, store), true);
    assert.equal(readStoredFlag(PAIRED_DEVICES_OPEN_KEY, false, store), true);
    writeStoredFlag(DATA_MANAGEMENT_OPEN_KEY, false, store);
    writeStoredFlag(PAIRED_DEVICES_OPEN_KEY, false, store);
    assert.equal(readStoredFlag(DATA_MANAGEMENT_OPEN_KEY, true, store), false);
    assert.equal(readStoredFlag(PAIRED_DEVICES_OPEN_KEY, true, store), false);
    assert.equal(store.getItem(DATA_MANAGEMENT_OPEN_KEY), "0");
    assert.equal(store.getItem(PAIRED_DEVICES_OPEN_KEY), "0");
  });
});

describe("dataManagementHint", () => {
  it("formats ISO dates as mm/dd/yyyy", () => {
    assert.equal(formatIsoDateMdY("2026-05-01"), "05/01/2026");
    assert.equal(formatIsoDateMdY("2026-11-11"), "11/11/2026");
    assert.equal(formatIsoDateMdY(""), "");
    assert.equal(formatIsoDateMdY(null), "");
    assert.equal(formatIsoDateMdY("not-a-date"), "");
  });

  it("prefers the backfill window when that row is shown", () => {
    assert.equal(
      dataManagementHint({
        start: "2026-05-01",
        end: "2026-11-11",
        exFrom: "2026-01-01",
        exTo: "2026-01-31",
        showBackfill: true,
      }),
      "Backfill 05/01/2026 → 11/11/2026",
    );
  });

  it("falls back to export dates when backfill is hidden", () => {
    assert.equal(
      dataManagementHint({
        start: "2026-05-01",
        end: "2026-11-11",
        exFrom: "2026-01-15",
        exTo: "2026-02-01",
        showBackfill: false,
      }),
      "Export 01/15/2026 → 02/01/2026",
    );
  });

  it("handles a single bound and omits the hint when nothing useful is set", () => {
    assert.equal(
      dataManagementHint({ start: "2026-05-01", showBackfill: true }),
      "Backfill 05/01/2026 → …",
    );
    assert.equal(
      dataManagementHint({ exTo: "2026-02-01", showBackfill: false }),
      "Export … → 02/01/2026",
    );
    assert.equal(dataManagementHint({ showBackfill: false }), "");
    assert.equal(dataManagementHint({}), "");
  });
});

describe("pairedDevicesHint", () => {
  it("uses the device name for a single pairing and a count otherwise", () => {
    assert.equal(pairedDevicesHint([]), "");
    assert.equal(pairedDevicesHint([{ device_version: "Charge 6" }]), "Charge 6");
    assert.equal(pairedDevicesHint([{ device_type: "TRACKER" }]), "TRACKER");
    assert.equal(
      pairedDevicesHint([{ device_version: "Charge 6" }, { device_version: "Aria Air" }]),
      "2 devices",
    );
  });
});
