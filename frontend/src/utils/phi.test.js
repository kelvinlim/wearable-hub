import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  HIDE_PHI_KEY,
  maskParticipantId,
  maskSubjectCsvFields,
  maskSubjectLabel,
  subjectDeleteConfirmTokens,
  subjectDeletePromptId,
  subjectDisplayName,
  subjectExportBasename,
  subjectFallbackId,
  typedDeleteConfirmationMatches,
} from "./phi.js";

const subject = {
  id: 42,
  participant_id: "P-001",
  subject_label: "alice@umn.edu",
};

describe("Hide PHI helpers", () => {
  it("uses a dedicated localStorage key", () => {
    assert.equal(HIDE_PHI_KEY, "wearable-hide-phi");
  });

  it("falls back to su-{id}", () => {
    assert.equal(subjectFallbackId(subject), "su-42");
    assert.equal(subjectFallbackId({}), "");
  });

  it("shows Study ID (then label) when PHI is visible", () => {
    assert.equal(subjectDisplayName(subject, false), "P-001");
    assert.equal(subjectDisplayName({ id: 7, subject_label: "bob" }, false), "bob");
    assert.equal(subjectDisplayName({ id: 7 }, false), "su-7");
  });

  it("shows only su-{id} when PHI is hidden", () => {
    assert.equal(subjectDisplayName(subject, true), "su-42");
    assert.equal(maskSubjectLabel(subject, true), "su-42");
    assert.equal(maskParticipantId(subject.participant_id, true), "");
    assert.equal(maskParticipantId(subject.participant_id, false), "P-001");
  });

  it("keeps the real label when PHI is visible", () => {
    assert.equal(maskSubjectLabel(subject, false), "alice@umn.edu");
    assert.equal(maskSubjectLabel({ id: 1 }, false), "");
  });

  it("strips identifiers from export filenames when hidden", () => {
    assert.equal(subjectExportBasename(subject, false), "P-001");
    assert.equal(subjectExportBasename(subject, true), "su-42");
    assert.equal(subjectExportBasename({ id: 9, subject_label: "Ann Adams" }, false), "Ann_Adams");
  });

  it("masks study-CSV identifier columns when hidden", () => {
    assert.deepEqual(maskSubjectCsvFields(subject, false), {
      subject_label: "alice@umn.edu",
      participant_id: "P-001",
    });
    assert.deepEqual(maskSubjectCsvFields(subject, true), {
      subject_label: "su-42",
      participant_id: "",
    });
  });

  it("delete confirm accepts Study ID or su-{id}", () => {
    assert.deepEqual(subjectDeleteConfirmTokens(subject), ["su-42", "P-001"]);
    assert.equal(subjectDeletePromptId(subject, false), "P-001");
    assert.equal(subjectDeletePromptId(subject, true), "su-42");
    assert.equal(subjectDeletePromptId({ id: 7 }, false), "su-7");
    assert.ok(typedDeleteConfirmationMatches(subject, "P-001"));
    assert.ok(typedDeleteConfirmationMatches(subject, "su-42"));
    assert.ok(typedDeleteConfirmationMatches(subject, "SU-42"));
    assert.equal(typedDeleteConfirmationMatches(subject, "p-001"), false);
    assert.equal(typedDeleteConfirmationMatches(subject, "P-999"), false);
    assert.equal(typedDeleteConfirmationMatches(subject, ""), false);
  });
});
