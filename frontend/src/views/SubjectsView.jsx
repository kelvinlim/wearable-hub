import React, { useEffect, useState, useCallback } from "react";
import { Plus, Trash2, Lock, Pencil, X } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Input, Th, Td, Empty } from "../ui";
import SubjectDetail from "./SubjectDetail";

// Compact "start → end" window label for the table; "—" when no window is set.
function windowLabel(s) {
  if (!s.collection_start && !s.collection_end) return null;
  return `${s.collection_start || "…"} → ${s.collection_end || "…"}`;
}

export default function SubjectsView({ studyId, canAdmin, guard }) {
  const [subjects, setSubjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [pid, setPid] = useState("");
  const [editing, setEditing] = useState(null); // subject being edited, or null

  const load = useCallback(() => {
    if (studyId != null) guard(async () => setSubjects(await api.listSubjects(studyId)));
  }, [studyId, guard]);
  useEffect(() => {
    setSelected(null);
    setSubjects([]);
    load();
  }, [load]);

  if (studyId == null)
    return (
      <Card className="p-10 text-center text-sm text-gray-400">
        Select a study from the header dropdown to view its subjects.
      </Card>
    );

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-gray-100 p-4 dark:border-neutral-800">
          <h3 className="font-display text-base font-semibold text-maroon dark:text-gold">Subjects</h3>
          {canAdmin && (
            <Button onClick={() => setAdding((a) => !a)}>
              <Plus className="h-4 w-4" /> Add subject
            </Button>
          )}
        </div>

        {adding && canAdmin && (
          <form
            className="flex flex-wrap items-center gap-2 border-b border-gray-100 bg-gray-50 p-4 dark:border-neutral-800 dark:bg-neutral-800/40"
            onSubmit={(e) => {
              e.preventDefault();
              guard(async () => {
                await api.createSubject(studyId, {
                  subject_label: label.trim() || null,
                  participant_id: pid.trim() || null,
                });
                setLabel("");
                setPid("");
                setAdding(false);
                load();
              });
            }}
          >
            <Input placeholder="Study ID (optional)" value={pid} onChange={(e) => setPid(e.target.value)} autoFocus />
            <Input placeholder="Label — Google account (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
            <Button type="submit">Create — generates entry code</Button>
            <Button type="button" variant="subtle" onClick={() => setAdding(false)}>Cancel</Button>
          </form>
        )}

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-100 dark:border-neutral-800">
              <tr>
                <Th>Entry code</Th>
                <Th>Study ID</Th>
                <Th>Label</Th>
                <Th>Collection window</Th>
                <Th>Status</Th>
                <Th>Linked</Th>
                {canAdmin && <Th />}
              </tr>
            </thead>
            <tbody>
              {subjects.map((s) => {
                const win = windowLabel(s);
                return (
                  <tr
                    key={s.id}
                    onClick={() => setSelected(s)}
                    className={
                      "cursor-pointer border-b border-gray-50 transition-colors hover:bg-gray-50 dark:border-neutral-800/60 dark:hover:bg-neutral-800/50 " +
                      (selected?.id === s.id ? "bg-maroon/5 dark:bg-maroon/20" : "")
                    }
                  >
                    <Td><code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">{s.entry_code}</code></Td>
                    <Td className="font-medium">{s.participant_id || <span className="text-gray-300">—</span>}</Td>
                    <Td>{s.subject_label || <span className="text-gray-300">—</span>}</Td>
                    <Td className="whitespace-nowrap text-xs text-gray-500">{win || <span className="text-gray-300">—</span>}</Td>
                    <Td className="text-gray-500">{s.status}</Td>
                    <Td>{s.registered ? <Badge tone="green">linked</Badge> : <Badge>no</Badge>}</Td>
                    {canAdmin && (
                      <Td className="text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-3">
                          <button
                            title="Edit subject (Study ID, label, collection window)"
                            onClick={() => setEditing(s)}
                            className="text-gray-400 hover:text-maroon dark:hover:text-gold"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          {!s.registered ? (
                            <button
                              title="Delete subject (not yet linked)"
                              onClick={() => {
                                if (!confirm(`Delete subject ${s.entry_code}? This can't be undone.`)) return;
                                guard(async () => {
                                  await api.deleteSubject(s.id);
                                  if (selected?.id === s.id) setSelected(null);
                                  load();
                                });
                              }}
                              className="text-gray-400 hover:text-red-600"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          ) : (
                            <span
                              title="Linked — revoke this subject's access before it can be deleted"
                              className="inline-flex cursor-help text-gray-300 dark:text-neutral-600"
                            >
                              <Lock className="h-4 w-4" />
                            </span>
                          )}
                        </div>
                      </Td>
                    )}
                  </tr>
                );
              })}
              {subjects.length === 0 && (
                <tr><td colSpan={canAdmin ? 7 : 6}><Empty>No subjects yet.</Empty></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {selected && <SubjectDetail subject={selected} canAdmin={canAdmin} guard={guard} onChanged={load} />}

      {editing && (
        <EditSubjectModal
          subject={editing}
          guard={guard}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setEditing(null);
            if (selected?.id === updated.id) setSelected(updated);
            load();
          }}
        />
      )}
    </div>
  );
}

function EditSubjectModal({ subject, guard, onClose, onSaved }) {
  const [pid, setPid] = useState(subject.participant_id || "");
  const [label, setLabel] = useState(subject.subject_label || "");
  const [start, setStart] = useState(subject.collection_start || "");
  const [end, setEnd] = useState(subject.collection_end || "");
  const [busy, setBusy] = useState(false);

  const rangeBad = start && end && end < start;

  const save = () =>
    guard(async () => {
      setBusy(true);
      try {
        const updated = await api.updateSubject(subject.id, {
          participant_id: pid.trim() || null,
          subject_label: label.trim() || null,
          collection_start: start || null,
          collection_end: end || null,
        });
        onSaved(updated);
      } finally {
        setBusy(false);
      }
    });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <Card className="w-full max-w-md" >
        <div onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between border-b border-gray-100 p-4 dark:border-neutral-800">
            <h3 className="font-display text-base font-semibold text-maroon dark:text-gold">
              Edit subject <code className="ml-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">{subject.entry_code}</code>
            </h3>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="h-4 w-4" /></button>
          </div>

          <div className="space-y-4 p-4">
            <Field label="Study ID">
              <Input className="w-full" placeholder="Study's subject identifier" value={pid} onChange={(e) => setPid(e.target.value)} />
            </Field>
            <Field label="Label (Google account)">
              <Input className="w-full" placeholder="Google / Fitbit account" value={label} onChange={(e) => setLabel(e.target.value)} />
            </Field>

            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Data-collection window</div>
              <div className="flex items-center gap-2">
                <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
                <span className="text-gray-400">→</span>
                <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
              </div>
              <p className="mt-1.5 text-xs text-gray-400">
                Inclusive, subject-local days. Leave a side blank for open-ended. Pulls are clamped to this window across all triggers.
              </p>
              {rangeBad && <p className="mt-1 text-xs text-red-600">End date must be on or after the start date.</p>}
            </div>
          </div>

          <div className="flex justify-end gap-2 border-t border-gray-100 p-4 dark:border-neutral-800">
            <Button variant="subtle" onClick={onClose}>Cancel</Button>
            <Button onClick={save} disabled={busy || rangeBad}>{busy ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</div>
      {children}
    </label>
  );
}
