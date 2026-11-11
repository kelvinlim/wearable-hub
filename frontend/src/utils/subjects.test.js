import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  EXPORT_OPEN_KEY,
  SHOW_ARCHIVED_KEY,
  SHOW_REGISTERED_KEY,
  filterSubjectList,
  readStoredFlag,
  writeStoredFlag,
} from "./subjects.js";

function memoryStore(seed = {}) {
  const data = { ...seed };
  return {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
  };
}

const linked = { id: 1, registered: true, archived: false };
const pending = { id: 2, registered: false, archived: false };
const linkedArchived = { id: 3, registered: true, archived: true };
const archived = { id: 4, registered: false, archived: true };

describe("filterSubjectList (Show registered)", () => {
  it("default off leaves the fetched list unchanged", () => {
    const list = [linked, pending, archived];
    assert.equal(filterSubjectList(list), list);
    assert.deepEqual(filterSubjectList(list, { showRegistered: false }), list);
  });

  it("on keeps only currently linked/registered rows", () => {
    assert.deepEqual(
      filterSubjectList([linked, pending, archived], { showRegistered: true }),
      [linked],
    );
  });

  it("intersects with an already-fetched archived list", () => {
    // Server already applied include_archived; client keeps linked ∩ that set.
    assert.deepEqual(
      filterSubjectList([linked, pending, linkedArchived, archived], { showRegistered: true }),
      [linked, linkedArchived],
    );
  });
});

describe("Subjects / Export localStorage prefs", () => {
  it("uses dedicated wh-* keys (same 1/0 encoding as Hide PHI and dark mode)", () => {
    assert.equal(SHOW_REGISTERED_KEY, "wh-show-registered");
    assert.equal(SHOW_ARCHIVED_KEY, "wh-show-archived");
    assert.equal(EXPORT_OPEN_KEY, "wh-export-open");
  });

  it("defaults Show registered and Show archived off when unset", () => {
    const store = memoryStore();
    assert.equal(readStoredFlag(SHOW_REGISTERED_KEY, false, store), false);
    assert.equal(readStoredFlag(SHOW_ARCHIVED_KEY, false, store), false);
  });

  it("defaults Export expanded when unset", () => {
    const store = memoryStore();
    assert.equal(readStoredFlag(EXPORT_OPEN_KEY, true, store), true);
  });

  it("round-trips saved choices", () => {
    const store = memoryStore();
    writeStoredFlag(SHOW_REGISTERED_KEY, true, store);
    writeStoredFlag(SHOW_ARCHIVED_KEY, true, store);
    writeStoredFlag(EXPORT_OPEN_KEY, false, store);
    assert.equal(readStoredFlag(SHOW_REGISTERED_KEY, false, store), true);
    assert.equal(readStoredFlag(SHOW_ARCHIVED_KEY, false, store), true);
    assert.equal(readStoredFlag(EXPORT_OPEN_KEY, true, store), false);
  });
});
