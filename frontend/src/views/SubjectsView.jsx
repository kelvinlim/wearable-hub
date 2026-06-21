import React, { useEffect, useMemo, useState, useCallback } from "react";
import {
  Plus, Trash2, Lock, Pencil, X, ChevronUp, ChevronDown,
  BatteryFull, BatteryWarning, AlertTriangle,
} from "lucide-react";
import { api } from "../api";
import { ALL_PROVIDERS, providerLabel } from "../lib";
import { Card, Button, Badge, Input, Th, Td, Empty } from "../ui";
import SubjectDetail from "./SubjectDetail";

// Compact "start → end" window label for the table; "—" when no window is set.
function windowLabel(s) {
  if (!s.collection_start && !s.collection_end) return null;
  return `${s.collection_start || "…"} → ${s.collection_end || "…"}`;
}

const dash = <span className="text-gray-300 dark:text-neutral-600">—</span>;

// Per-subject device registrations: a chip per device (provider + entry code + linked dot), plus
// an "Add device" control for the providers not yet registered.
function DevicesCell({ s, canAdmin, guard, onChanged }) {
  const regs = s.registrations || [];
  const present = new Set(regs.map((r) => r.provider));
  const missing = ALL_PROVIDERS.filter((p) => !present.has(p));
  return (
    <div className="flex flex-col items-start gap-1" onClick={(e) => e.stopPropagation()}>
      {regs.map((r) => (
        <Badge key={r.id} tone={r.registered ? "green" : "gray"} className="gap-1">
          <span className="font-semibold">{providerLabel(r.provider)}</span>
          <code className="rounded bg-black/5 px-1 text-[11px] dark:bg-white/10">{r.entry_code}</code>
          {r.registered ? "✓" : ""}
        </Badge>
      ))}
      {regs.length === 0 && <span className="text-xs text-gray-300">no devices</span>}
      {canAdmin && missing.length > 0 && (
        <div className="flex gap-1">
          {missing.map((p) => (
            <button
              key={p}
              title={`Add ${providerLabel(p)} registration`}
              onClick={() => guard(async () => { await api.addRegistration(s.id, p); onChanged(); })}
              className="inline-flex items-center gap-0.5 rounded border border-dashed border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-500 hover:border-maroon hover:text-maroon dark:border-neutral-700 dark:hover:border-gold dark:hover:text-gold"
            >
              <Plus className="h-3 w-3" />{providerLabel(p)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Sorting ---------------------------------------------------------------
const SORTERS = {
  label: (s) => (s.subject_label || "").toLowerCase(),
  status: (s) => s.status || "",
  linked: (s) => (s.registered ? 1 : 0),
};
const DEFAULT_DIR = { label: "asc", status: "asc", linked: "desc" };

function SortTh({ label, sortKey, sort, onSort, className }) {
  const active = sort.key === sortKey;
  return (
    <Th className={className}>
      <button
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider hover:text-maroon dark:hover:text-gold"
      >
        {label}
        {active && (sort.dir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
      </button>
    </Th>
  );
}

// --- Compact health indicators ---------------------------------------------
const BATT_TONE = { High: "green", Medium: "gold", Low: "red", Empty: "red" };

function relDay(d) {
  if (!d) return null;
  const then = new Date(d + "T00:00:00");
  const days = Math.round((new Date(new Date().toDateString()) - new Date(then.toDateString())) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return d;
}

function BatteryCell({ s }) {
  if (!s.registered || s.battery_level == null) return dash;
  const Icon = s.battery_low ? BatteryWarning : BatteryFull;
  return (
    <Badge tone={s.battery_low ? "red" : BATT_TONE[s.battery_status] || "gray"} className="gap-1">
      <Icon className="h-3.5 w-3.5" />
      {s.battery_level}%
    </Badge>
  );
}

// 7-pip bar of last-week coverage + the "n/7" count; flags a stale badge alongside.
function WeekDataCell({ s }) {
  if (!s.registered) return dash;
  const n = s.days_with_data_7 || 0;
  const tone = n >= 6 ? "bg-green-500" : n >= 3 ? "bg-gold" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5">
        {Array.from({ length: 7 }).map((_, i) => (
          <span key={i} className={"h-3 w-1.5 rounded-sm " + (i < n ? tone : "bg-gray-200 dark:bg-neutral-700")} />
        ))}
      </div>
      <span className="text-xs text-gray-500">{n}/7</span>
      {s.data_stale && (
        <Badge tone="red" className="gap-1"><AlertTriangle className="h-3 w-3" />stale</Badge>
      )}
    </div>
  );
}

function LatestCell({ s }) {
  if (!s.registered) return dash;
  const rel = relDay(s.last_data_date);
  if (!rel) return <span className="text-xs text-red-600">none</span>;
  return <span className={"whitespace-nowrap text-xs " + (s.data_stale ? "text-red-600" : "text-gray-500")}>{rel}</span>;
}

export default function SubjectsView({ studyId, canAdmin, guard }) {
  const [subjects, setSubjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [pid, setPid] = useState("");
  const [provider, setProvider] = useState("fitbit_gh");
  const [editing, setEditing] = useState(null); // subject being edited, or null
  const [sort, setSort] = useState({ key: "linked", dir: "desc" }); // linked-first by default

  const onSort = (k) =>
    setSort((s) => (s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: DEFAULT_DIR[k] }));

  const sorted = useMemo(() => {
    const f = SORTERS[sort.key];
    return [...subjects].sort((a, b) => {
      const av = f(a), bv = f(b);
      let c = av < bv ? -1 : av > bv ? 1 : 0;
      if (c === 0) c = a.id - b.id;
      return sort.dir === "asc" ? c : -c;
    });
  }, [subjects, sort]);

  const load = useCallback(() => {
    if (studyId != null)
      guard(async () => {
        const list = await api.listSubjects(studyId);
        setSubjects(list);
        // Keep the open detail panel in sync after add-device / revoke / edit.
        setSelected((sel) => (sel ? list.find((x) => x.id === sel.id) || null : null));
      });
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
                  provider,
                });
                setLabel("");
                setPid("");
                setProvider("fitbit_gh");
                setAdding(false);
                load();
              });
            }}
          >
            <Input placeholder="Study ID (optional)" value={pid} onChange={(e) => setPid(e.target.value)} autoFocus />
            <Input placeholder="Label — account (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            >
              {ALL_PROVIDERS.map((p) => (
                <option key={p} value={p}>{providerLabel(p)}</option>
              ))}
            </select>
            <Button type="submit">Create — generates entry code</Button>
            <Button type="button" variant="subtle" onClick={() => setAdding(false)}>Cancel</Button>
          </form>
        )}

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-100 dark:border-neutral-800">
              <tr>
                <Th>Devices</Th>
                <Th>Study ID</Th>
                <SortTh label="Label" sortKey="label" sort={sort} onSort={onSort} />
                <Th>Battery</Th>
                <Th>Data (7d)</Th>
                <Th>Latest</Th>
                <Th>Collection window</Th>
                <SortTh label="Status" sortKey="status" sort={sort} onSort={onSort} />
                <SortTh label="Linked" sortKey="linked" sort={sort} onSort={onSort} />
                {canAdmin && <Th />}
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => {
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
                    <Td><DevicesCell s={s} canAdmin={canAdmin} guard={guard} onChanged={load} /></Td>
                    <Td className="font-medium">{s.participant_id || <span className="text-gray-300">—</span>}</Td>
                    <Td>{s.subject_label || <span className="text-gray-300">—</span>}</Td>
                    <Td><BatteryCell s={s} /></Td>
                    <Td><WeekDataCell s={s} /></Td>
                    <Td><LatestCell s={s} /></Td>
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
                                const who = s.participant_id || s.subject_label || `#${s.id}`;
                                if (!confirm(`Delete subject ${who} and its device registrations? This can't be undone.`)) return;
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
                <tr><td colSpan={canAdmin ? 10 : 9}><Empty>No subjects yet.</Empty></td></tr>
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
              Edit subject
              <code className="ml-1 rounded bg-gray-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">{subject.participant_id || subject.subject_label || `#${subject.id}`}</code>
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
