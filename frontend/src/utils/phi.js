/** Client-side Hide PHI helpers.
 *
 * Wearable Hub has no name/DOB/MRN columns like GRID. The subject-identifying
 * fields the console actually paints are `subject_label` (Google/Fitbit/Oura
 * account label) and `participant_id` (the study's own "Study ID"). When Hide
 * PHI is on, those are blanked at render time and the row falls back to
 * `su-{id}` — matching GRID's display-id fallback. The session API is
 * unchanged. See HIDE_PHI.md.
 */

export const HIDE_PHI_KEY = "wearable-hide-phi";

/** Stable, non-name fallback used whenever a subject needs a label. */
export function subjectFallbackId(subject) {
  return subject?.id != null ? `su-${subject.id}` : "";
}

/**
 * Read-only heading / filename stem: Study ID or account label when showing
 * PHI; `su-{id}` when hidden.
 */
export function subjectDisplayName(subject, hidePhi) {
  if (!subject) return "";
  if (hidePhi) return subjectFallbackId(subject) || "Subject";
  return subject.participant_id || subject.subject_label || subjectFallbackId(subject) || "Subject";
}

/**
 * Account-label cell. When hidden, fall back to `su-{id}` so the row stays
 * distinguishable (GRID's name column → display_id).
 */
export function maskSubjectLabel(subject, hidePhi) {
  if (hidePhi) return subjectFallbackId(subject);
  return subject?.subject_label || "";
}

/** Study ID / `participant_id`. Blank when hidden (GRID's MRN/SSN → —). */
export function maskParticipantId(value, hidePhi) {
  if (hidePhi) return "";
  return value == null ? "" : String(value);
}

/** Download basename; never embed a Study ID / account label while hidden. */
export function subjectExportBasename(subject, hidePhi) {
  const who = hidePhi
    ? subjectFallbackId(subject) || `subject-${subject?.id ?? "unknown"}`
    : subject?.participant_id || subject?.subject_label || `subject-${subject?.id ?? "unknown"}`;
  return String(who).replace(/\s+/g, "_");
}

/**
 * Study-wide CSV identifier columns. Name-like `subject_label` becomes
 * `su-{id}`; `participant_id` is blanked. JSON export bodies are left alone
 * (raw API payload).
 */
export function maskSubjectCsvFields(subject, hidePhi) {
  if (!hidePhi) {
    return {
      subject_label: subject?.subject_label ?? "",
      participant_id: subject?.participant_id ?? "",
    };
  }
  return {
    subject_label: subjectFallbackId(subject),
    participant_id: "",
  };
}
