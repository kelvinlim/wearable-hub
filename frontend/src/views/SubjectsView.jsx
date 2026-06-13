import React, { useEffect, useState, useCallback } from "react";
import { Plus, Trash2, Lock } from "lucide-react";
import { api } from "../api";
import { Card, Button, Badge, Input, Th, Td, Empty } from "../ui";
import SubjectDetail from "./SubjectDetail";

export default function SubjectsView({ studyId, canAdmin, guard }) {
  const [subjects, setSubjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");

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
                await api.createSubject(studyId, { subject_label: label.trim() || null });
                setLabel("");
                setAdding(false);
                load();
              });
            }}
          >
            <Input placeholder="Subject label (optional)" value={label} onChange={(e) => setLabel(e.target.value)} autoFocus />
            <Button type="submit">Create — generates entry code</Button>
            <Button type="button" variant="subtle" onClick={() => setAdding(false)}>Cancel</Button>
          </form>
        )}

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-100 dark:border-neutral-800">
              <tr>
                <Th>Entry code</Th>
                <Th>Label</Th>
                <Th>Status</Th>
                <Th>Linked</Th>
                {canAdmin && <Th />}
              </tr>
            </thead>
            <tbody>
              {subjects.map((s) => (
                <tr
                  key={s.id}
                  onClick={() => setSelected(s)}
                  className={
                    "cursor-pointer border-b border-gray-50 transition-colors hover:bg-gray-50 dark:border-neutral-800/60 dark:hover:bg-neutral-800/50 " +
                    (selected?.id === s.id ? "bg-maroon/5 dark:bg-maroon/20" : "")
                  }
                >
                  <Td><code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">{s.entry_code}</code></Td>
                  <Td className="font-medium">{s.subject_label || <span className="text-gray-300">—</span>}</Td>
                  <Td className="text-gray-500">{s.status}</Td>
                  <Td>{s.registered ? <Badge tone="green">linked</Badge> : <Badge>no</Badge>}</Td>
                  {canAdmin && (
                    <Td className="text-right" onClick={(e) => e.stopPropagation()}>
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
                    </Td>
                  )}
                </tr>
              ))}
              {subjects.length === 0 && (
                <tr><td colSpan={canAdmin ? 5 : 4}><Empty>No subjects yet.</Empty></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {selected && <SubjectDetail subject={selected} canAdmin={canAdmin} guard={guard} onChanged={load} />}
    </div>
  );
}
